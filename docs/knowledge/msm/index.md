# msm Knowledge

`msm` is the core package. It owns market reference data, asset extensions,
execution records, account records, account allocation and virtual-fund state,
platform bootstrap, repository helpers, and shared DataNode conventions.

It does not own portfolio construction or pricing engines. Portfolio
construction workflows live in `msm_portfolios`; optional pricing and QuantLib
integration live in `msm_pricing`.

## Core Areas

- [Accounts](accounts/index.md): account identity, holdings, groups, and target
  position assignments.
- [Virtual Funds](virtualfunds/index.md): account-owned allocation views over
  real account holdings.
- [Assets](assets/index.md): asset identity, type registration, category
  membership, relational asset detail tables, OpenFIGI details, and
  asset-indexed DataNodes.
- [Calendars](calendars/index.md): bounded calendar identities, daily facts,
  sessions, and calendar-level events used by portfolios, execution, and
  pricing adapters.
- [Client](client/index.md): client-facing wrappers around platform objects.
- [Derivatives](derivatives/index.md): futures and derivative details that
  extend canonical assets and may reference non-asset underlyings.
- [Execution](execution/index.md): order-manager intent rows and timestamped
  order, event, and trade DataNodes.
- [Indexes](indices/index.md): non-tradable index reference data used by
  derivative underlyings and pricing workflows.
- [Migrations](migrations/index.md): admin-owned schema evolution through the SDK
  Alembic provider and automatic catalog finalization.
- [Models](models/index.md): SQLAlchemy MetaTable declarations and registration
  order for core market tables.
- [Platform](platform/index.md): Main Sequence integration primitives,
  MetaTable bootstrap, and shared DataNode behavior.
- [Repositories](repositories/index.md): compiled SQL operations and CRUD
  boundaries over market-domain tables.
- [Services](services/index.md): application-level orchestration over
  repository operations.

## Package Boundary

Core row APIs should import from `msm.api.*` and core table declarations should
import from `msm.models.*Table`.

When a workflow needs portfolio construction, switch to
[`msm_portfolios`](../msm_portfolios/index.md). Virtual-fund identity and
holdings allocation remain in core `msm`. When a workflow needs pricing models,
curves, fixings, or QuantLib-backed valuation, switch to
[`msm_pricing`](../msm_pricing/index.md).
