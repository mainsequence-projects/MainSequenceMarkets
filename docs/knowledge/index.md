# Knowledge Base

The knowledge base describes the domain concepts inside `msm`. It is organized
around the package boundaries in `src/msm` so implementation details, workflows,
and future tutorials have a stable place to live.

Use these pages before adding new modules. They define what each concept owns,
what it should not own, and which package should be extended for common changes.

## General Library Spirit

The library should feel like a typed market-domain API to users, not like a
collection of SQLAlchemy internals. For row-oriented MetaTable data:

- user-facing code imports Pydantic row objects from `msm.api.*`;
- schema/bootstrap code imports SQLAlchemy declarations from `msm.models.*Table`;
- row classes declare their backing table through `__table__` and required
  schema set through `__required_tables__`;
- row class methods such as `create_schemas(...)`, `upsert(...)`, `filter(...)`,
  and lookups are the preferred ergonomic surface;
- row operations attach to already-registered MetaTables by default, with
  `MSM_AUTO_REGISTER_NAMESPACE` reserved for opt-in example/development
  auto-registration;
- repository helpers remain lower-level building blocks for compiled MetaTable
  operations and can return raw platform payloads;
- services own broader workflows that compose providers, repositories,
  DataNodes, and row APIs.

This split is enforced across the markets MetaTables. `msm.models` exports
`*Table` declarations only; row names such as `Asset`, `Portfolio`, `Fund`,
`Order`, and `Trade` live in `msm.api.*`.

This pattern is recorded in
[ADR 0008](../ADR/0008-metatable-table-and-api-model-split.md) and should guide
new MetaTable-facing APIs unless a more specific ADR overrides it.

## Concept Map

- [Accounts](accounts/index.md): account identity, holdings, virtual funds, and
  account-to-target assignments.
- [Assets](assets/index.md): asset identity, category membership, DataNode
  snapshots, pricing details, and provider services such as OpenFIGI.
- [Client](client/index.md): client-facing models and HTTP/platform object
  wrappers.
- [Execution](execution/index.md): order managers, target quantities, orders,
  order events, trades, and execution errors.
- [Models](models/index.md): SQLAlchemy market-domain models and MetaTable
  registration order.
- [Platform](platform/index.md): shared Main Sequence integration primitives,
  MetaTable helpers, and market DataNode base behavior.
- [Portfolios](portfolios/index.md): portfolio configuration, signal weights,
  rebalance strategies, canonical portfolio data, and VFB workflows.
- [Pricing](pricing/index.md): priceable instruments, QuantLib helpers, curves,
  fixings, and pricing data interfaces.
- [Repositories](repositories/index.md): compiled database operations and CRUD
  boundaries over market-domain models.
- [Services](services/index.md): application-level orchestration over repository
  operations.

## Documentation Pattern

Each concept page should keep the same structure:

1. Scope: what the concept owns.
2. Primary modules: where the implementation lives.
3. Key contracts: data shapes, identifiers, and runtime assumptions.
4. Extension notes: where new behavior should be added.
5. Related concepts: adjacent pages that commonly interact with it.

When a design decision changes a concept boundary, capture it in an ADR and link
the ADR from the relevant concept page.
