# 0019. msm_portfolios Package Boundary

## Status

Accepted

## Context

`msm_portfolios` has grown beyond a small core submodule. It is effectively a
portfolio application layer inside `msm`: it owns portfolio registry rows,
portfolio DataNode storage, virtual funds, portfolio construction logic,
contributed price and signal nodes, rebalance strategies, and public row APIs.

That shape makes core `msm` harder to reason about. A user who only needs
assets, accounts, indices, execution, or reference data still gets portfolio and
virtual-fund concerns pulled into the main model graph and runtime surface. The
current coupling points are concrete:

- `src/msm/models/__init__.py` registers `PortfolioTable`, `FundTable`,
  `SignalMetadataTable`, `RebalanceStrategyMetadataTable`, and portfolio
  DataNode storage classes through core `markets_sqlalchemy_models()`.
- `src/msm/bootstrap.py` exposes portfolio DataNode handles from the core
  runtime: `PortfolioWeights`, `PortfoliosDataNode`, `SignalWeights`, and
  `VirtualFundHoldings`.
- `src/msm/api/portfolios.py` mixes portfolio row APIs and virtual-fund row APIs.
- `src/msm/data_nodes/storage.py` contains `FundHoldingsStorage`, although that
  storage table is owned by virtual-fund workflows.
- `src/msm/models/execution.py` has hard MetaTable foreign keys to `FundTable`,
  which currently forces execution to know about the fund registry.

The package already has one precedent for separating a larger optional surface:
`msm_pricing`. Pricing has its own top-level package, model graph, bootstrap,
tests, docs, and optional dependencies while still depending on core `msm`
models and maintenance/catalog primitives.

Portfolios should follow the same direction. Core `msm` should own the common
markets reference layer and platform machinery. Portfolio construction and
virtual funds should live in their own top-level package so users can import,
bootstrap, test, and document that surface explicitly.

The Main Sequence SDK documentation treats DataNodes as stable data products
with storage/update identity and describes Virtual Fund Builder as a portfolio
construction layer over DataNodes. That matches the intended split:
portfolio/virtual-fund functionality should be an explicit library surface built
on top of core markets models, not an implicit part of every core `msm`
bootstrap.

## Decision

Introduce a new top-level package named `msm_portfolios`.

The first migration will keep `msm_portfolios` inside the existing `ms-markets`
distribution, similar to `msm_pricing`. This reduces release and dependency risk
while still creating the correct Python import and bootstrap boundary. A later
ADR can decide whether `msm_portfolios` should become a separately distributed
package.

The dependency direction is one-way:

```text
+------------------+        imports/depends on        +------------------+
| msm_portfolios   | -------------------------------> | msm              |
|                  |                                  | core markets     |
+------------------+                                  +------------------+
```

Core `msm` must not import `msm_portfolios`.

Portfolio and virtual-fund code should be moved to `msm_portfolios` without
compatibility shims unless backward compatibility is explicitly requested in a
separate decision. The migration should update imports directly in examples,
docs, and tests.

### Core `msm` Ownership

The following stay in core `msm`:

- assets, asset types, asset details, asset categories, and asset snapshots;
- indices and index snapshots;
- issuers, calendars, accounts, account groups, account model portfolios,
  account target portfolios, and position sets;
- execution models and execution DataNodes;
- shared DataNode bases and utilities such as `AssetIndexedDataNode`,
  `StampedDataNode`, namespace helpers, datetime normalization, and storage
  schema helpers;
- bootstrap, maintenance catalog, model registration, repository context, and
  generic CRUD helpers.

`AccountModelPortfolioTable`, `AccountTargetPortfolioTable`, and
`PositionSetTable` remain core account models. Despite their names, they model
account mandates and target positions, not the portfolio construction engine.

### `msm_portfolios` Ownership

The new package owns:

- portfolio registry MetaTables:
  - `PortfolioTable`
  - `PortfolioMetadataTable`
  - optional portfolio-index linkage through core `IndexTable`, not
    `AssetTable`;
- virtual-fund registry MetaTables:
  - `FundTable` initially, with a future naming decision on whether the public
    row API should become `VirtualFund`;
- portfolio construction metadata:
  - `SignalMetadataTable`
  - `RebalanceStrategyMetadataTable`
- portfolio and virtual-fund public row APIs:
  - `Portfolio`
  - `PortfolioMetadata`
  - portfolio-index creation/linking helpers that produce `Index` rows when a
    portfolio needs index-like publication;
  - `Fund` or `VirtualFund`
  - `SignalMetadata`
  - `RebalanceStrategyMetadata`
- portfolio and virtual-fund repositories and services;
- portfolio DataNodes and storage:
  - `PortfolioWeights`
  - `SignalWeights`
  - `PortfoliosDataNode`
  - `PortfolioWeightsStorage`
  - `SignalWeightsStorage`
  - `PortfoliosStorage`
  - `InterpolatedPrices`
  - `ExternalPrices`
  - `InterpolatedPricesStorage`
  - `ExternalPricesStorage`
  - `VirtualFundHoldings`
  - `FundHoldingsStorage`
- portfolio configuration models, asset scope helpers, contributed price/signal
  nodes, utilities, and rebalance strategies;
- portfolio/virtual-fund examples, docs, skills, and tests.

### Portfolio Identity Model Correction

The initial migration preserved `PortfolioAssetDetailTable`, but that model is
wrong for the intended portfolio domain.

`PortfolioTable` must be the source of truth for portfolio identity and the
DataNode UIDs used to build or publish the portfolio. It must not store
construction-mode booleans, portfolio statistics, or generic JSON metadata.
Those are workflow/configuration or derived-output concerns, not portfolio
identity.

Target shape:

```text
+-----------------------------+
| PortfolioTable              |
|-----------------------------|
| uid PK                      |
| unique_identifier unique    |
| calendar_name               |
| portfolio_weights_node_uid  |-----> PortfolioWeights DataNode / storage
| signal_weights_node_uid     |-----> SignalWeights DataNode / storage
| portfolio_values_node_uid   |-----> PortfoliosDataNode / storage
| optional portfolio_index_uid|-----> IndexTable.uid
+-----------------------------+       optional PortfolioIndex, not an Asset
```

Portfolios are not assets. A portfolio may optionally create or link a
portfolio index, but that index must be modeled through core `IndexTable`, not
through `AssetTable`. The optional index is a representation of the portfolio as
an index-like observable series; it is not required for the portfolio row to
exist and it is not a portfolio constituent.

The following relationship should be removed from the target model:

```text
+-----------------------------+        optional canonical asset  +-----------------------------+
| PortfolioAssetDetailTable   |--------------------------------->| AssetTable                  |
|-----------------------------| asset_uid                       |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| portfolio_uid unique FK     |                                  | unique_identifier unique    |
| asset_uid nullable FK       |                                  +-----------------------------+
| asset_unique_identifier     |
+-----------------------------+
```

This table duplicates portfolio-index identity and points it at the wrong core
concept. If a workflow needs to describe holdings, constituents, or target
weights, those belong in portfolio DataNode storage or a future explicit
constituent model, not in a one-to-one "asset detail" row.

Portfolio DataNode storage should also stop using asset-language identity such
as `portfolio_index_asset_unique_identifier`. Storage keys should be expressed
in portfolio/index terms:

- portfolio weights: portfolio identity plus held asset identity;
- portfolio values: portfolio identity;
- optional portfolio index publication: linked `IndexTable` identity.

The cleanup should avoid compatibility shims unless a later explicit
compatibility decision requires them.

### Bootstrap Boundary

`msm_portfolios` will expose its own startup boundary:

```python
import msm_portfolios

msm_portfolios.start_engine(models=["Portfolio", "Fund"])
```

The bootstrap must reuse core `msm` maintenance/catalog machinery. It must not
create a parallel catalog, UID map, or registration path.

`msm_portfolios.start_engine(...)` should:

1. resolve portfolio model selectors into SQLAlchemy model classes;
2. expand required core dependencies such as `AssetTable` and `AccountTable`;
3. register or attach selected models through the same catalog bootstrap used by
   `msm.start_engine(...)`;
4. register portfolio DataNode storage classes only when requested by the
   portfolio graph;
5. cache runtime initialization once per process with the same explicit-startup
   semantics as core `msm`;
6. return a portfolio runtime/context that row APIs and DataNodes can use.

Core `msm.start_engine(...)` should not register portfolio/virtual-fund tables
or portfolio DataNode storage by default after the migration.

### Execution And Fund References

Execution currently references `FundTable` through hard `MetaTableForeignKey`
columns such as `related_fund_uid`. Once `FundTable` moves to
`msm_portfolios`, core execution cannot keep a hard foreign key to it without
making core import `msm_portfolios`.

The migration should remove the hard MetaTable FK from core execution to
`FundTable` and remove `related_fund_uid` from core execution models, APIs, and
storage contracts entirely. Core execution stays in `msm`, but it should not
carry virtual-fund-specific columns after `FundTable` moves to
`msm_portfolios`.

This preserves the package direction:

```text
core execution rows do not expose related_fund_uid
core execution rows must not import FundTable from msm_portfolios
```

If fund-linked execution semantics are needed later, add them in
`msm_portfolios` through an extension table or workflow that depends on both core
execution and virtual funds.

### Initial Package Layout

Target layout:

```text
src/msm_portfolios/
  __init__.py
  bootstrap.py
  models/
    __init__.py
    portfolios/
      __init__.py
      core.py
      metadata.py
    virtual_funds.py
    signals.py
    rebalancing.py
  api/
    __init__.py
    portfolios.py
    virtual_funds.py
    market_metadata.py
  repositories/
    __init__.py
    portfolios.py
    virtual_funds.py
    market_metadata.py
  services/
    __init__.py
    portfolios.py
    virtual_funds.py
    market_metadata.py
    holdings.py
  data_nodes/
    __init__.py
    base.py
    constants.py
    metadata.py
    portfolio_identity.py
    portfolio_weights.py
    portfolios.py
    signal_weights.py
    storage.py
    virtual_funds.py
  contrib/
    prices/
    signals/
  rebalance_strategy/
  asset_scope.py
  configuration.py
  enums.py
  utils.py
```

### Import Surface

Preferred user imports after migration:

```python
from msm_portfolios.api.portfolios import Portfolio
from msm_portfolios.api.virtual_funds import Fund
from msm_portfolios.data_nodes import PortfolioWeights, PortfoliosDataNode
from msm_portfolios.contrib.signals.fixed_weights import FixedWeights
```

Core imports should remain focused:

```python
from msm.api.assets import Asset
from msm.api.accounts import Account
from msm.api.execution import OrderManager
```

No new `msm.portfolios` compatibility module should be added unless a later
explicit compatibility decision requires it.

## Implementation Plan

### Stage 0: ADR And Boundary Audit

- [x] Record this ADR.
- [x] Audit imports of `msm.portfolios`, `msm.api.portfolios`,
  `msm.models.portfolios`, `msm.models.funds`, `SignalMetadataTable`,
  `RebalanceStrategyMetadataTable`, `FundHoldingsStorage`, and
  `VirtualFundHoldings`.
- [x] Confirm public row naming remains `Fund` for this migration.
- [x] Confirm no compatibility shims are required.

### Stage 1: Package Skeleton And Bootstrap

- [x] Add `src/msm_portfolios`.
- [x] Add `msm_portfolios.start_engine(...)` and runtime helpers.
- [x] Reuse `msm.maintenance.catalog` and core repository context machinery.
- [x] Add `msm_portfolios.models.portfolio_sqlalchemy_models()` model graph
  resolver in dependency order.
- [x] Add package-boundary tests proving core `msm` does not import
  `msm_portfolios`.

### Stage 2: Move Portfolio And Virtual-Fund MetaTables

- [x] Move `PortfolioTable`, `PortfolioAssetDetailTable`, and
  `PortfolioMetadataTable`.
- [x] Move `FundTable`.
- [x] Move `SignalMetadataTable` and `RebalanceStrategyMetadataTable`.
- [x] Remove those models from core `msm.models.markets_sqlalchemy_models()`.
- [x] Remove those exports from core `msm.models`.
- [x] Update model tests under `tests/msm_portfolios/models`.

### Stage 3: Resolve Execution/Fund Coupling

- [x] Remove hard `MetaTableForeignKey(FundTable, ...)` declarations from core
  execution models.
- [x] Remove `related_fund_uid` from core execution models, APIs, repository
  filters, tests, and docs.
- [x] Update execution API required table lists so execution does not require
  portfolio/virtual-fund tables.
- [x] Keep execution itself in core `msm`; only virtual-fund-specific extension
  behavior belongs in `msm_portfolios`.
- [x] Add tests proving core execution bootstrap does not require `FundTable`.

### Stage 4: Move Row APIs, Repositories, And Services

- [x] Move portfolio row APIs to `msm_portfolios.api.portfolios`.
- [x] Move virtual-fund row APIs to `msm_portfolios.api.virtual_funds`.
- [x] Move signal/rebalance metadata row APIs to
  `msm_portfolios.api.market_metadata`.
- [x] Move portfolio and fund repositories/services into `msm_portfolios`.
- [x] Move fund holdings frame builders into `msm_portfolios.services.holdings`.
- [x] Update public API tests under `tests/msm_portfolios/api`.

### Stage 5: Move DataNodes And Storage

- [x] Move portfolio DataNode storage classes into `msm_portfolios`.
- [x] Move portfolio DataNode logic into `msm_portfolios`.
- [x] Move `VirtualFundHoldings` and `FundHoldingsStorage` into
  `msm_portfolios`.
- [x] Remove portfolio and virtual-fund DataNode handles from core
  `msm.bootstrap.DATA_NODE_HANDLE_NAMES` and `MarketsRuntime.data_nodes`.
- [x] Remove portfolio storage classes from core model registration.
- [x] Update DataNode tests under `tests/msm_portfolios/data_nodes`.

### Stage 6: Move Contrib And Strategy Code

- [x] Move contributed price nodes under `msm_portfolios.contrib.prices`.
- [x] Move contributed signal nodes under `msm_portfolios.contrib.signals`.
- [x] Move rebalance strategies under `msm_portfolios.rebalance_strategy`.
- [x] Move portfolio configuration models to `msm_portfolios.configuration`.
- [x] Update imports inside strategy/configuration modules.
- [x] Validate that portfolio contrib imports do not load from core `msm`.

### Stage 7: Documentation, Examples, And Skills

- [x] Update `docs/knowledge/msm_portfolios/portfolios/index.md` to describe
  `msm_portfolios`.
- [x] Update `docs/knowledge/msm_portfolios/virtualfunds/index.md` to describe
  `msm_portfolios`.
- [x] Update docs navigation and tutorial portfolio workflow imports.
- [x] Move or update portfolio examples to import from `msm_portfolios`.
- [x] Collapse `examples/msm_portfolios/` to the single
  `examples/msm_portfolios/portfolio_equal_weights_example.py` workflow.
- [x] Verify packaged skills do not reference stale portfolio or virtual-fund
  imports.
- [x] Add a changelog entry.

### Stage 8: Validation

- [x] Run focused `py_compile` for moved modules and examples.
- [x] Run focused `ruff` for `src/msm_portfolios`, touched `src/msm` modules,
  moved tests, and touched examples.
- [x] Run focused tests for core import boundaries, core bootstrap, portfolio
  bootstrap, DataNode storage contracts, row APIs, repositories, and catalog
  bootstrap fallout.
- [x] Run `git diff --check`.
- [x] Run MkDocs strict build.
- [x] Build the wheel and verify `msm`, `msm_pricing`, and `msm_portfolios` are
  packaged.

### Stage 9: Portfolio Identity Relationship Cleanup

- [x] Remove `PortfolioAssetDetailTable` from `msm_portfolios.models`.
- [x] Remove `PortfolioAssetDetail` row API, create/update/search/delete
  repository helpers, service wrappers, exports, and tests.
- [x] Remove `asset_detail` nested payload handling from `Portfolio.upsert`.
- [x] Replace `PortfolioTable.portfolio_index_uid` with an optional
  `portfolio_index_uid` foreign key to core `IndexTable.uid`.
- [x] Remove `PortfolioTable.portfolio_index_unique_identifier`; the direct
  `IndexTable` foreign key is enough for table identity.
- [x] Remove unnecessary `PortfolioTable` fields:
  `builds_from_target_weights`, `builds_from_predictions`,
  `builds_from_target_positions`,
  `tracking_funds_expected_exposure_from_latest_holdings`, `stats_json`, and
  `metadata_json`.
- [ ] Add or reuse a typed helper workflow that creates an `Index` row for
  portfolios that need index-like publication; do not create portfolio assets.
- [x] Rename portfolio DataNode storage columns and helpers from
  `portfolio_index_asset_unique_identifier` to
  `portfolio_index_unique_identifier`.
- [x] Update `get_or_create_portfolio_index(...)` and related DataNode
  code to use portfolio index terminology and `IndexTable`, not `AssetTable`.
- [x] Update `examples/msm_portfolios/` so portfolio examples no longer pass
  asset-detail payloads or create portfolio assets.
- [x] Update `docs/knowledge/msm_portfolios/portfolios/index.md` with the
  corrected ASCII diagrams showing `PortfolioTable` owning the portfolio details
  and DataNode UID links, plus optional `PortfolioTable -> IndexTable`.
- [x] Update tests under `tests/msm_portfolios/` for the new model graph,
  bootstrap dependency order, row APIs, and DataNode storage identity columns.
- [x] Run focused compile, ruff, tests, strict MkDocs build, and
  `git diff --check`.

## Consequences

The refactor makes the package boundary cleaner and makes startup behavior less
surprising. Core `msm` users will no longer register or import portfolio
machinery unless they opt into `msm_portfolios`.

The main migration cost is import churn. Tests, examples, docs, and skills must
be updated in the same change so the public workflow stays coherent.

The execution/fund relationship becomes less strictly enforced in core because
core execution can no longer own a direct FK to a virtual-fund table. That is the
right package-boundary tradeoff. Strict fund-linked execution semantics should
be implemented in `msm_portfolios` if needed.

This ADR does not change the underlying Main Sequence DataNode or MetaTable
semantics. It changes package ownership and bootstrap composition.
