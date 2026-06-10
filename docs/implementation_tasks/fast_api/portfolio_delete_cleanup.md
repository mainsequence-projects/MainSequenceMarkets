# FastAPI v1 Portfolio Delete Cleanup Implementation Plan

## Success Condition

Portfolio deletion becomes dependency-safe and data-cleaning:

- a portfolio cannot be deleted while any `VirtualFundTable` row references it
- successful portfolio deletion removes all historical
  `PortfolioWeightsStorage` rows for that portfolio in the same atomic backend
  operation before deleting the `PortfolioTable` row
- a separate endpoint can delete only historical portfolio weights without
  deleting the portfolio identity row
- the FastAPI layer stays thin and delegates the protected delete logic to
  reusable source code under `src/`
- OpenAPI, frontend docs, and focused tests describe the new behavior

## Current Verified State

`DELETE /api/v1/portfolio/{uid}/` currently calls:

```text
apps/v1/routers/portfolios.py
  -> apps/v1/services/portfolios.py::delete_portfolio
  -> msm_portfolios.services.delete_portfolio_record
  -> delete_model(context, model=PortfolioTable, uid=uid)
```

That deletes only the core `PortfolioTable` row.

Historical portfolio weights are stored in
`msm_portfolios.data_nodes.portfolios.storage.PortfolioWeightsStorage`, keyed by:

```text
time_index
portfolio_identifier
asset_identifier
```

They are not keyed by `PortfolioTable.uid`, so there is no database cascade from
portfolio uid to historical weights. They are keyed by
`PortfolioTable.unique_identifier` through the `portfolio_identifier` storage
dimension.

The current virtual-fund model has:

```text
VirtualFundTable.target_portfolio_uid -> PortfolioTable.uid ON DELETE CASCADE
```

That is wrong for the desired API behavior. A virtual fund depends on its target
portfolio, so portfolio deletion must be protected when virtual funds reference
it.

## Required Behavior

### Protected Portfolio Delete

Endpoint:

```text
DELETE /api/v1/portfolio/{uid}/
```

New behavior:

1. confirm the portfolio exists
2. reject deletion with `409` when any `VirtualFundTable.target_portfolio_uid`
   equals the portfolio uid
3. resolve the historical weights coordinate:

```text
PortfolioTable.uid
  -> PortfolioTable.unique_identifier
  -> PortfolioWeightsStorage.portfolio_identifier
```

4. delete matching historical `PortfolioWeightsStorage` rows
5. delete the `PortfolioTable` row
6. perform steps 4 and 5 in one atomic backend operation

Response:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 42
}
```

Conflict response:

```json
{
  "detail": "Portfolio is referenced by virtual funds."
}
```

If the portfolio exists, its `unique_identifier` is the historical weight
coordinate. Missing matching weights are reported as `deleted_weights_count: 0`.

`PortfoliosStorage` value-series cleanup remains out of scope unless explicitly
added. This task only changes portfolio weights cleanup.

### Delete Only Portfolio Weights

Endpoint:

```text
DELETE /api/v1/portfolio/{uid}/weights/
```

Query params:

- `weights_date`: optional ISO timestamp. When omitted, delete all historical
  weights for the portfolio. When provided, delete only that timestamp snapshot.

Response:

```json
{
  "detail": "Portfolio weights deleted.",
  "portfolio_uid": "portfolio-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": null,
  "deleted_count": 42
}
```

If the portfolio exists but no matching weights are present, return `200` with
`deleted_count: 0`. Do not return `404` unless the portfolio uid itself does
not exist.

## Implementation Design

### Source-Level Helpers

Add or update helpers under `src/msm_portfolios/services/public_api.py`:

- `delete_portfolio_record(context, uid: str) -> dict[str, Any] | None`
- `delete_portfolio_weights(context, uid: str, weights_date: datetime | None) -> dict[str, Any] | None`
- `bulk_delete_portfolio_records(...)` should use the new protected delete
  helper and include weight cleanup counts in failed/successful records where
  useful

The FastAPI service in `apps/v1/services/portfolios.py` should only call these
helpers and validate the returned response model.

### Atomic SQL Operation

Do not use raw SQL strings.

Use SQLAlchemy Core and the existing compiled operation path. The portfolio
delete should compile as a top-level `DELETE` operation so the backend sees the
correct statement type.

Conceptual shape:

```text
portfolio_scope CTE:
  select PortfolioTable.uid, PortfolioTable.unique_identifier
  where PortfolioTable.uid = :uid
  and not exists (
    select 1 from VirtualFundTable
    where VirtualFundTable.target_portfolio_uid = PortfolioTable.uid
  )

deleted_weights CTE:
  delete from PortfolioWeightsStorage
  where PortfolioWeightsStorage.portfolio_identifier in (
    select unique_identifier from portfolio_scope
  )
  returning 1

top-level statement:
  delete from PortfolioTable
  where PortfolioTable.uid in (select uid from portfolio_scope)
  returning PortfolioTable.uid,
            (select count(*) from deleted_weights) as deleted_weights_count
```

Attach `deleted_weights` with `.add_cte(...)` so weight deletion executes before
the portfolio delete in the same statement.

The delete-only-weights endpoint should use a top-level `DELETE` against
`PortfolioWeightsStorage`, optionally filtered by `weights_date`.

### Virtual Fund Protection

Add a source-level conflict check using `VirtualFundTable`.

The atomic operation must also guard the weight delete and portfolio delete with
the same virtual-fund condition so a race cannot delete weights when the
portfolio delete is blocked.

### Schema-Level Protection

Change `VirtualFundTable.target_portfolio_uid` from `ondelete="CASCADE"` to
`ondelete="RESTRICT"` in the SQLAlchemy model.

This requires a new migration through the normal Main Sequence migration
workflow. Do not edit existing migration revisions manually.

Reason: API/service preflight protects `apps/v1`, but the current database
constraint still allows cascade deletion from any lower-level delete path.

## Endpoint Contract Changes

### `DELETE /api/v1/portfolio/{uid}/`

Response model should be extended from:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1
}
```

to:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 42
}
```

Add `409` behavior for virtual-fund references in addition to existing
protected target-position references.

### `DELETE /api/v1/portfolio/{uid}/weights/`

New response model:

```json
{
  "detail": "Portfolio weights deleted.",
  "portfolio_uid": "portfolio-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": "2026-06-07T10:30:00Z",
  "deleted_count": 4
}
```

## Implementation Tasks

- [x] Add `PortfolioWeightsDeleteResponse` to
      `apps/v1/schemas/portfolios.py`.
- [x] Extend `PortfolioDeleteResponse` with `deleted_weights_count: int`.
- [x] Add `DELETE /api/v1/portfolio/{uid}/weights/` to
      `apps/v1/routers/portfolios.py`.
- [x] Add thin FastAPI service wrapper
      `delete_portfolio_weights(...)` in `apps/v1/services/portfolios.py`.
- [x] Add source helper to resolve
      `PortfolioTable.uid -> PortfolioTable.unique_identifier`.
- [x] Add source helper to count/check `VirtualFundTable` references.
- [x] Replace `delete_portfolio_record(...)` with a protected atomic delete that
      deletes `PortfolioWeightsStorage` first and `PortfolioTable` second.
- [x] Ensure protected delete returns `None` only for missing portfolio, and
      raises `PortfolioDeleteConflictError` for virtual-fund references.
- [x] Update `bulk_delete_portfolio_records(...)` to use the protected delete
      helper and preserve per-uid failure reasons.
- [x] Change `VirtualFundTable.target_portfolio_uid` FK declaration from
      `CASCADE` to `RESTRICT`.
- [ ] Create a new migration for the FK contract change through the Main
      Sequence migration provider. Do not edit old revisions.
- [x] Update tests in `tests/msm/models/test_metatable_models.py` to expect
      `RESTRICT`.
- [x] Add service tests for the atomic portfolio delete statement shape.
- [x] Add service tests that virtual-fund references block portfolio deletion.
- [x] Add service tests that portfolio delete removes matching weights by
      `portfolio_identifier`.
- [x] Add route tests for `DELETE /api/v1/portfolio/{uid}/weights/`.
- [x] Add route tests for `DELETE /api/v1/portfolio/{uid}/` returning
      `deleted_weights_count`.
- [x] Add OpenAPI tests for the new weights-delete route and updated response
      model.
- [x] Update `docs/fast_api/v1/portfolio.md`.
- [x] Update `docs/fast_api/v1/index.md`.
- [x] Update `docs/implementation_tasks/fast_api/portfolio_routes.md` so it no
      longer says portfolio delete leaves historical weights untouched.

## Validation

Run focused validation:

```bash
uv run --extra dev python -m pytest \
  tests/msm/fastapi/v1/test_portfolios.py \
  tests/msm/fastapi/v1/test_openapi.py \
  tests/msm/models/test_metatable_models.py
```

Run focused lint/format checks:

```bash
uv run --extra dev python -m ruff check \
  apps/v1/routers/portfolios.py \
  apps/v1/schemas/portfolios.py \
  apps/v1/services/portfolios.py \
  src/msm_portfolios/services/public_api.py \
  src/msm/models/accounts/virtual_funds.py \
  tests/msm/fastapi/v1/test_portfolios.py \
  tests/msm/models/test_metatable_models.py

uv run --extra dev python -m ruff format --check \
  apps/v1/routers/portfolios.py \
  apps/v1/schemas/portfolios.py \
  apps/v1/services/portfolios.py \
  src/msm_portfolios/services/public_api.py \
  src/msm/models/accounts/virtual_funds.py \
  tests/msm/fastapi/v1/test_portfolios.py \
  tests/msm/models/test_metatable_models.py

git diff --check
```

Migration validation must also verify the resulting backend FK behavior before
claiming the schema-level protection is complete.

## Risks And Decisions

- If the FK remains `CASCADE`, `apps/v1` can protect its own route, but lower
  level delete paths can still cascade-delete virtual funds. The robust fix is
  the FK migration to `RESTRICT`.
- Portfolio weight cleanup is scoped by `PortfolioTable.unique_identifier`.
  Optional `published_index_uid` values are not involved in ordinary portfolio
  deletion.
