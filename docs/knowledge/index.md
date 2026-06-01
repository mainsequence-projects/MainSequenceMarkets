# Knowledge Base

The knowledge base describes the domain concepts in `ms-markets`. It is
organized around package boundaries so implementation details, workflows, and
future tutorials have a stable place to live.

Use these pages before adding new modules. They define what each concept owns,
what it should not own, and which package should be extended for common changes.

## General Library Spirit

The library should feel like a typed market-domain API to users, not like a
collection of SQLAlchemy internals. For row-oriented MetaTable data:

- user-facing code imports core Pydantic row objects from `msm.api.*` and
  portfolio Pydantic row objects from `msm_portfolios.api.*`;
- schema/bootstrap code imports SQLAlchemy declarations from `msm.models.*Table`;
- row classes declare their backing table through `__table__` and required
  schema set through `__required_tables__`;
- `msm.start_engine(...)` is the preferred core schema/bootstrap surface, while
  `msm_portfolios.start_engine(...)` is the portfolio and virtual-fund package
  surface;
- row class methods such as `upsert(...)`, `filter(...)`, and lookups are the
  preferred ergonomic row-operation surface;
- row operations use the active process runtime created by explicit startup
  bootstrap and never register or attach MetaTables on first row use;
- `MSM_AUTO_REGISTER_NAMESPACE` is a namespace default for examples and local
  development, and it also drives default markets DataNode namespacing;
- repository helpers remain lower-level building blocks for compiled MetaTable
  operations and can return raw platform payloads;
- services own broader workflows that compose providers, repositories,
  DataNodes, and row APIs.

This split is enforced across the markets MetaTables. `msm.models` exports
core `*Table` declarations only; row names such as `Asset`, `Account`, and
`OrderManager` live in `msm.api.*`. Timestamped execution facts such as orders,
order events, and trades live in DataNode storage, not duplicate row tables.
Portfolio row names such as `Portfolio` and `Fund` live in
`msm_portfolios.api.*`.

This pattern is recorded in
[ADR 0008](../ADR/0008-metatable-table-and-api-model-split.md) and should guide
new MetaTable-facing APIs unless a more specific ADR overrides it.

## Package Map

- [msm](msm/index.md): core market reference data, assets, accounts,
  execution, indexes, platform bootstrap, repositories, and services.
- [msm_portfolios](msm_portfolios/index.md): portfolio construction,
  portfolio DataNodes, virtual funds, and fund holdings.
- [msm_pricing](msm_pricing/index.md): optional pricing package with priceable
  instruments, QuantLib helpers, curves, fixings, market-data context bindings,
  and pricing data interfaces.

## Documentation Pattern

Each concept page should keep the same structure:

1. Scope: what the concept owns.
2. Primary modules: where the implementation lives.
3. Key contracts: data shapes, identifiers, and runtime assumptions.
4. Extension notes: where new behavior should be added.
5. Related concepts: adjacent pages that commonly interact with it.

When a design decision changes a concept boundary, capture it in an ADR and link
the ADR from the relevant concept page.
