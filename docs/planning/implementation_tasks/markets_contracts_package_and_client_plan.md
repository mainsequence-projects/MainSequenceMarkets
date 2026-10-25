# Markets Contracts Package And `msm.client` Plan

## Status

Design note, drafted 2026-10-25 for [ADR 0047](../../ADR/0047-markets-api-application-boundary.md)
decision 2 and migration path step 2. Nothing in it is implemented. Step 1
(the acting identity, the portfolio dataset catalog, the catalog-aware reads
and the missing routes) is on `development`; this note is the hand-off for
the packaging split. It records what the split must preserve, where the
current code resists it and the order in which to do it. It does not start
the split.

## Success Condition

The split is complete when:

- a consumer that only reads and writes registry rows installs
  `ms-markets-contracts` and nothing else from this repository, holds no
  MetaTables grants and no table classes, and `Portfolio.get_by_uid()` works
  against a deployed `markets-api` release;
- `ms-markets-contracts` imports neither SQLAlchemy, `metatables` nor
  QuantLib, and its wire contract is versioned by a `>=2,<3` range that the
  Markets API honours;
- `ms-markets` depends on `ms-markets-contracts` with an exact pin and keeps
  every table class, repository, migration, time-index updater and the FastAPI
  application;
- `msm.client` is a typed HTTP client generated from, or checked against,
  `apps/v1`'s OpenAPI document, that returns the `msm.api` row models, and
  that discovers and authenticates against the `markets-api` release exactly
  as `metatables.endpoint` does for MetaTables;
- every `msm.api` row class works unchanged under two backends, `runtime`
  (compiled SQL, today's path) and `remote` (the client), selected by the
  application and never mixed in one process;
- a consumer API can replace an exact `ms-markets[portfolios]` pin with the
  contracts range for a portfolio-reading route family without importing a
  table class.

## What Moves Where

`ms-markets-contracts` (distribution name; import packages stay `msm.api`,
`msm.api.http`, `msm.constants` so consumer code does not change):

| Today | Destination | Note |
| --- | --- | --- |
| `msm.api.base.MarketsMetaTableRow`, `MarketsRow` | contracts | Becomes backend-neutral; see "The row base class" |
| `msm.api.accounts`, `assets`, `calendars`, `derivatives`, `execution`, `indices`, `issuers`, `portfolios`, `virtual_funds` row and payload models | contracts | Row and `*Create`/`*Update`/`*Upsert` Pydantic models only |
| `msm.api.formula_indices.FormulaIndex` | split | The model (`index`, `definition`, `inputs`) is a contract; `upsert`, `activate`, `retire`, `calculate_from_sources` are service calls behind the backend |
| `msm.analytics.indices` contracts (`IndexFormulaDefinition`, `IndexFormulaInput`, `IndexFormulaSourceReference`) | contracts | Pure Pydantic plus the formula parser; no table access |
| `msm.services.indices.contracts` (`IndexFormulaDetail`, `IndexDatasetState`, ...) | contracts | API response models; move under `msm.api.indices` or a new `msm.api.contracts.indices` |
| `msm_portfolios.services.portfolio_datasets` models (`PortfolioDatasetRegistration`, `PortfolioDatasetState`, `PortfolioDatasetReconciliationResult`) | contracts | Response models of the catalog routes |
| `msm.api.http` | contracts | Collection, discovery, bulk-action, tabular-frame, error and operation contracts; see "FastAPI in the contracts" |
| `msm.constants` | contracts | Static keys |
| Storage layout contracts: column names, dtypes, index names of `PortfoliosTS`, `PortfolioWeightsTS`, `SignalWeightsTS`, `IndexValuesTS` | contracts | As data (a frozen mapping per contract), not as SQLAlchemy tables; `contract_instances.py` keeps building tables from them |
| `msm.models`, `msm.repositories`, `msm.bootstrap`, `msm_migrations`, `msm.time_index`, `msm_portfolios` (updaters, strategies, services), `msm_pricing`, `apps/v1`, `msm_cli` | `ms-markets` | Unchanged location |

`msm.client` (new, in the contracts distribution so a consumer needs one
package):

- `msm.client.MarketsClient`: discovery, authentication, one `httpx` or
  `requests` session, typed methods per operation id;
- `msm.client.backend`: the `remote` implementation of the row-backend
  protocol;
- `msm.client.openapi`: the pinned OpenAPI document snapshot the client was
  built from, and a check that a running release's document is compatible.

## The Row Base Class

`msm.api.base.MarketsMetaTableRow` today binds a row class to its table with
`__table__: ClassVar[type[MarketsBase]]` and `__required_tables__`, resolves
the runtime with `msm.bootstrap.resolve_runtime`, compiles SQL with
`msm.repositories.crud` and validates field names against
`cls.__table__.columns` in `_require_column`. Every method except
`model_validate` goes through one of those. The split replaces that with a
backend protocol:

```python
class RowBackend(Protocol):
    def create(self, row_cls, values) -> Mapping[str, Any]: ...
    def upsert(self, row_cls, values, *, keys) -> Mapping[str, Any]: ...
    def update(self, row_cls, uid, values) -> Mapping[str, Any]: ...
    def delete(self, row_cls, uid) -> Mapping[str, Any]: ...
    def get_by_uid(self, row_cls, uid) -> Mapping[str, Any] | None: ...
    def get_by_unique_identifier(self, row_cls, value) -> Mapping[str, Any] | None: ...
    def get_many_by_uids(self, row_cls, uids) -> list[Mapping[str, Any]]: ...
    def filter(self, row_cls, *, filters, contains_filters, limit) -> list[Mapping[str, Any]]: ...
```

- Each row class declares `__resource__` (the API path segment, for example
  `"account"`) and `__upsert_keys__`; `__table__` and `__required_tables__`
  move to a registry that `ms-markets` fills at import
  (`msm.models.registration.bind_row_tables()`), so the contracts package
  never names a table.
- `_require_column` validates against the row model's fields, which are the
  table's columns by construction (ADR 0008). `extra="ignore"` stays, so a
  newer API may return columns an older contracts release does not know.
- The active backend is process-wide and set once:
  `msm.api.use_backend(RuntimeBackend())` by `msm.bootstrap.start_engine`,
  `msm.api.use_backend(MarketsClient(...).backend)` by a consumer, or by
  `MSM_API_BACKEND=remote` at import. Mixing backends in one process is an
  error; the Markets deployment and producers use `runtime`, everyone else
  `remote`.
- `start_engine()` on a row class remains for producers. Under the `remote`
  backend it is a no-op that logs, because a consumer attaches nothing.

The `runtime` backend is today's code moved behind the protocol: `resolve_runtime`,
`compile_markets_statement` and the `crud` helpers, unchanged.

## The Remote Backend

Each protocol method maps to one `apps/v1` operation. The routes added in
step 1 close the gaps the mapping needs:

| Backend method | Operation |
| --- | --- |
| `create` | `create<Resource>` (`POST /<resource>/`) |
| `update` | `update<Resource>` (`PATCH /<resource>/{uid}/`) |
| `delete` | `delete<Resource>` |
| `get_by_uid` | `get<Resource>` |
| `get_many_by_uids` | `get<Resources>ByUids` (`GET /<resource>/by-uids/?uid__in=`) |
| `filter` | `list<Resources>` with the collection's filters |
| `upsert` | `get_by_unique_identifier` then `create` or `update`; a server-side upsert route is a later addition |

Rows without a create or update route yet (asset, asset type, issuer, index
type, order manager, virtual fund, account group, allocation model, target
allocation, position set, calendar dates in bulk) are listed as the remaining
route work before the remote backend can claim parity. Time-index facts are
not row API calls: `portfolio_values`, `latest_portfolio_weights` and
`signal_weights` become `MarketsClient.portfolio_values(uids, ...)` over
`getPortfoliosValuesFrame` and `getPortfoliosWeightsFrame`, returning the
`core.tabular_frame@v1` frame or a pandas frame built from it.

Discovery and authentication copy `metatables.endpoint`:
`ResourceRelease.filter_admin(name="markets-api")` in the caller's
Environment, `resolve_runtime_access` for the bearer token, the same
pinning and refresh behaviour, and `MARKETS_API_URL` plus
`MARKETS_API_TOKEN` as the local override. A requester-bound call passes the
caller assertion through unchanged; the client never fabricates identity.

Errors map from `msm.api.http.errors`: `404` to `None` on gets and
`LookupError` on mutations, `400` and `422` to `ValueError`, `409` to a
`ConflictError` subclass of `ValueError`, `401` and `403` to a
`MarketsAccessError`, so service code that catches `ValueError` or
`LookupError` behaves the same under both backends.

## FastAPI In The Contracts

`msm.api.http.errors` and `msm.api.http.collections` import
`fastapi.HTTPException`. A contracts package cannot require FastAPI, so the
helpers that raise it (`api_http_error`, `bad_request`, `conflict`,
`not_found`, `dependency_unavailable`, `resource_collection_response`'s
error path) move to `msm.api.http.fastapi`, imported only by `apps/v1`, or
take an `exception_cls` argument that defaults lazily. The Pydantic contracts
themselves have no FastAPI dependency.

## Compatibility Promise

- The wire contract is the `apps/v1` OpenAPI document. Its `info.version`
  tracks the contracts package major and minor; a breaking change to a row
  model, a route or a tabular frame bumps the major and keeps the old route
  for one minor.
- `ms-markets-contracts` is `2.x` from the first release so that the
  consumer range `>=2,<3` matches the current ms-markets major.
- A contracts test fixture pins the OpenAPI document; `tests/msm/fastapi`
  fails when a route changes without a contracts bump.
- Consumers never see a table schema change: `PortfolioDatasetAvailability`
  and every future column reach them as response fields, with
  `extra="ignore"` on the way in.

## Repository Layout

One repository, two distributions, as hatchling supports with two build
configurations:

```text
pyproject.toml                  ms-markets (unchanged name), depends on ms-markets-contracts==X.Y.Z
contracts/pyproject.toml        ms-markets-contracts, packages src/msm/api, src/msm/client, src/msm/constants
src/msm/api/...                 shared source, built into the contracts wheel only
src/msm/models/..., src/msm/repositories/..., ...   ms-markets wheel only
```

`src/msm/__init__.py` becomes a namespace-friendly package: it must not import
models or `metatables` at import time (today it does not), and both wheels
ship `msm/__init__.py` only if it stays empty, otherwise the contracts wheel
owns it and `ms-markets` lists `msm` as a namespace. The release workflow
publishes the contracts wheel first and then `ms-markets`, which pins the
contracts version it was built against. `docs/releasing.md` gains the second
PyPI project and the ordering rule.

## Order Of Work

1. Introduce the `RowBackend` protocol and the `runtime` backend behind it,
   with no behaviour change. Move `__table__` and `__required_tables__` into
   the registry that `msm.models` fills. Tests: every `msm.api` test passes
   with the registry bound; `_require_column` tests move to field names.
2. Split FastAPI out of `msm.api.http` (`msm.api.http.fastapi`). Tests: the
   contracts modules import without FastAPI installed.
3. Add the remaining create and update routes the remote backend needs, in
   the step 1 pattern (schema, service with `registry_write`, router,
   adapter registration, docs, tests).
4. Build `msm.client` against the OpenAPI snapshot: discovery,
   authentication, the `remote` backend, the frame helpers, the error
   mapping. Tests: an in-process `TestClient` of `apps/v1` serves as the
   remote, so the whole `msm.api` test matrix runs under both backends.
5. Add `contracts/pyproject.toml`, the two-wheel build, the version pin and
   the release ordering. Tests: `tests/packaging` installs each wheel in a
   clean environment and imports it; the contracts wheel has no SQLAlchemy,
   `metatables` or QuantLib in its resolved set.
6. Switch one consumer's portfolio reads to the client (migration path step
   4) as the first external proof, then document the consumer pattern in the
   FastAPI guide and the README.

## Out Of Scope

- Moving signals, strategies or engines; they stay in `msm_portfolios` and
  with providers (ADR 0047 non-goals).
- A generic SQL endpoint or a MetaTables pass-through in `msm.client`.
- Provider namespace moves and backfills (migration path step 3); the
  contract instances and the catalog from step 1 are what they build on.
