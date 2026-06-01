# msm Knowledge

`msm` is the core package. It owns market reference data, asset extensions,
execution records, account records, platform bootstrap, repository helpers, and
shared DataNode conventions.

It does not own portfolio construction or pricing engines. Portfolio and
virtual-fund workflows live in `msm_portfolios`; optional pricing and QuantLib
integration live in `msm_pricing`.

## Core Areas

- [Accounts](accounts/index.md): account identity, holdings, groups, and target
  position assignments.
- [Assets](assets/index.md): asset identity, type registration, category
  membership, relational asset detail tables, OpenFIGI details, and
  asset-indexed DataNodes.
- [Client](client/index.md): client-facing wrappers around platform objects.
- [Derivatives](derivatives/index.md): futures and derivative details that
  extend canonical assets and may reference non-asset underlyings.
- [Execution](execution/index.md): orders, order targets, order events, trades,
  and execution errors.
- [Indexes](indices/index.md): non-tradable index reference data used by
  derivative underlyings and pricing workflows.
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

When a workflow needs portfolio construction, fund holdings, or virtual funds,
switch to [`msm_portfolios`](../msm_portfolios/index.md). When it needs pricing
models, curves, fixings, or QuantLib-backed valuation, switch to
[`msm_pricing`](../msm_pricing/index.md).
