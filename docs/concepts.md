# Core Concepts

This page is the single canonical explanation of the `ms-markets` runtime model.
Other pages state the one-line rule they need and link here instead of
re-explaining it. Read this once; the rest of the docs assume it.

## Three layers: row objects, `*Table` declarations, DataNodes

`ms-markets` is meant to feel like a typed market-domain API, not a pile of
SQLAlchemy internals. There are three distinct layers, and each has an owner:

- **Row objects** — user-facing Pydantic models under `msm.api.*` (and
  `msm_portfolios.api.*` for portfolio construction). Application code works
  here: `Asset`, `Account`, `Portfolio`, `OrderManager`. Row classes expose
  class methods such as `upsert(...)`, `filter(...)`, and domain lookups.
- **`*Table` declarations** — SQLAlchemy MetaTable classes under
  `msm.models.*Table`: `AssetTable`, `AccountTable`, `OrderManagerTable`.
  Schema, registration, and migration code works here. A row class names its
  backing table through `__table__` and its required schema set through
  `__required_tables__`.
- **DataNodes** — timestamped storage contracts for execution facts and
  observations (orders, events, trades, holdings, fixings, curve points). These
  are *not* duplicate row MetaTables; they are time-indexed tables described by
  `PlatformTimeIndexMetaTable` storage classes.

```python
from msm.api.assets import Asset       # row object — application code
from msm.models import AssetTable       # SQLAlchemy declaration — schema code
```

Rule of thumb: **user workflows talk about `Asset.upsert(...)`; schema and
registration text talks about `AssetTable`.** Timestamped facts go to DataNodes,
never to a second row table.

## `start_engine()` is runtime attachment, not schema creation

`msm.start_engine(...)` (and `msm_portfolios.start_engine(...)` for the
portfolio package) is the explicit runtime-attachment entrypoint. It resolves
already-registered backend `MetaTable` and `TimeIndexMetaTable` resources by
each selected model's SQLAlchemy table name, then binds those backend objects to
the row APIs.

It does **not** create or evolve schema. Row operations use the active runtime
created during process initialization; **they do not attach to MetaTables or
register schemas on first row use.**

Treat attachment as process-startup work: run it once during application
initialization, after admin migrations are current. Repeated calls with the same
arguments return the cached runtime; different arguments are rejected for that
process.

```python
import msm

runtime = msm.start_engine(models=["Asset"])   # attach a subset
asset_table = runtime.table("Asset")            # low-level handle (internals only)
```

Pass `models=[...]` to attach a subset; it expands foreign-key dependencies and
attaches each selected model. Missing backend tables fail startup and must be
fixed through the migration flow below — startup never silently creates them.

## Migrations before runtime

Schema mutation belongs to the SDK migration command, not to row operations or
`start_engine()`. Run admin migrations to finalize schema **before** application
startup:

```bash
mainsequence migrations current --provider migrations:migration --json
mainsequence migrations upgrade --provider migrations:migration head
```

Only after migrations are current does `start_engine(...)` resolve and bind the
finalized backend tables. Do not call model `.register()` methods or local
registration helpers from application code.

## `MSM_AUTO_REGISTER_NAMESPACE`

`MSM_AUTO_REGISTER_NAMESPACE` is a **namespace default for examples and local
development only**. Set it before importing `msm.api` (or `msm.models`) when an
example should use an example-scoped namespace, then call `start_engine(...)`
during startup.

It does two things, and nothing more:

- it namespaces example/local MetaTable identities and the physical table-name
  suffix;
- it becomes the default namespace for markets DataNode identifiers and
  `hash_namespace` values created in the same process.

It does **not** make row operations register schemas, and a different namespace
or registration configuration is rejected once the process is initialized. In
production, leave it unset; the runtime uses the default markets namespace from
`msm.settings.markets_namespace()`.

## Package boundaries

- **`msm`** — core market reference data, assets, accounts, account allocation,
  virtual funds, calendars, execution, indexes, platform bootstrap,
  repositories, and services.
- **`msm_portfolios`** — portfolio construction workflows and portfolio
  DataNodes. Optional extra `ms-markets[portfolios]`.
- **`msm_pricing`** — priceable instruments, QuantLib helpers, curves, fixings,
  market-data sets, and valuation. Optional extra `ms-markets[pricing]`.

Repository helpers remain lower-level building blocks for compiled MetaTable
operations; services own broader workflows that compose providers,
repositories, DataNodes, and row APIs. The split is recorded in
[ADR 0008](ADR/0008-metatable-table-and-api-model-split.md) and should guide new
MetaTable-facing APIs unless a more specific ADR overrides it.

## Related pages

- [Getting Started](getting-started.md) — install and a first example.
- [msm Knowledge](knowledge/msm/index.md) — core concept reference.
- [Migrations](knowledge/msm/migrations/index.md) — the schema-evolution flow.
- [MetaTable Registration](knowledge/msm/platform/meta_table_registration.md) —
  how backend tables are resolved and bound.
