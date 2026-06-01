# 0019. msm_portfolios Package Boundary

## Status

Proposed

## Context

`msm.portfolios` has grown beyond a small core submodule. It is effectively a
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
  - `PortfolioAssetDetailTable`
  - `PortfolioMetadataTable`
- virtual-fund registry MetaTables:
  - `FundTable` initially, with a future naming decision on whether the public
    row API should become `VirtualFund`;
- portfolio construction metadata:
  - `SignalMetadataTable`
  - `RebalanceStrategyMetadataTable`
- portfolio and virtual-fund public row APIs:
  - `Portfolio`
  - `PortfolioAssetDetail`
  - `PortfolioMetadata`
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
  enums.py
  models.py
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
from msm.api.execution import Order
```

No new `msm.portfolios` compatibility module should be added unless a later
explicit compatibility decision requires it.

## Implementation Plan

### Stage 0: ADR And Boundary Audit

- [ ] Record this ADR.
- [ ] Audit every import of `msm.portfolios`, `msm.api.portfolios`,
  `msm.models.portfolios`, `msm.models.funds`, `SignalMetadataTable`,
  `RebalanceStrategyMetadataTable`, `FundHoldingsStorage`, and
  `VirtualFundHoldings`.
- [ ] Confirm whether public row naming remains `Fund` or moves to
  `VirtualFund`.
- [ ] Confirm no compatibility shims are required.

### Stage 1: Package Skeleton And Bootstrap

- [ ] Add `src/msm_portfolios`.
- [ ] Add `msm_portfolios.start_engine(...)` and runtime objects.
- [ ] Reuse `msm.maintenance.catalog` and core repository context machinery.
- [ ] Add `msm_portfolios.models.portfolio_sqlalchemy_models()` or equivalent
  model graph resolver in dependency order.
- [ ] Add package-boundary tests proving `import msm` does not import
  `msm_portfolios`.

### Stage 2: Move Portfolio And Virtual-Fund MetaTables

- [ ] Move `PortfolioTable`, `PortfolioAssetDetailTable`, and
  `PortfolioMetadataTable`.
- [ ] Move `FundTable`.
- [ ] Move `SignalMetadataTable` and `RebalanceStrategyMetadataTable`.
- [ ] Remove those models from core `msm.models.markets_sqlalchemy_models()`.
- [ ] Remove those exports from core `msm.models`.
- [ ] Update model tests under `tests/msm_portfolios/models`.

### Stage 3: Resolve Execution/Fund Coupling

- [ ] Remove hard `MetaTableForeignKey(FundTable, ...)` declarations from core
  execution models.
- [ ] Remove `related_fund_uid` from core execution models, APIs, DataNode
  storage classes, services, tests, and docs.
- [ ] Update execution API required table lists so execution does not require
  portfolio/virtual-fund tables.
- [ ] Keep execution itself in core `msm`; only virtual-fund-specific extension
  behavior belongs in `msm_portfolios`.
- [ ] Add tests proving core execution bootstrap does not require `FundTable`.

### Stage 4: Move Row APIs, Repositories, And Services

- [ ] Move portfolio row APIs to `msm_portfolios.api.portfolios`.
- [ ] Move virtual-fund row APIs to `msm_portfolios.api.virtual_funds`.
- [ ] Move signal/rebalance metadata row APIs to
  `msm_portfolios.api.market_metadata`.
- [ ] Move portfolio and fund repositories/services into `msm_portfolios`.
- [ ] Move fund holdings frame builders into `msm_portfolios.services.holdings`.
- [ ] Update public API tests under `tests/msm_portfolios/api`.

### Stage 5: Move DataNodes And Storage

- [ ] Move portfolio DataNode storage classes into `msm_portfolios`.
- [ ] Move portfolio DataNode logic into `msm_portfolios`.
- [ ] Move `VirtualFundHoldings` and `FundHoldingsStorage` into
  `msm_portfolios`.
- [ ] Remove portfolio and virtual-fund DataNode handles from core
  `msm.bootstrap.DATA_NODE_HANDLE_NAMES` and `MarketsRuntime.data_nodes`.
- [ ] Remove portfolio storage classes from core model registration.
- [ ] Update DataNode tests under `tests/msm_portfolios/data_nodes`.

### Stage 6: Move Contrib And Strategy Code

- [ ] Move contributed price nodes under `msm_portfolios.contrib.prices`.
- [ ] Move contributed signal nodes under `msm_portfolios.contrib.signals`.
- [ ] Move rebalance strategies under `msm_portfolios.rebalance_strategy`.
- [ ] Update imports inside strategy/configuration modules.
- [ ] Validate that portfolio contrib imports do not load from core
  `msm.portfolios`.

### Stage 7: Documentation, Examples, And Skills

- [ ] Update `docs/knowledge/portfolios/index.md` to describe
  `msm_portfolios`.
- [ ] Update `docs/knowledge/virtualfunds/index.md` to describe
  `msm_portfolios`.
- [ ] Update docs navigation and tutorial portfolio workflow imports.
- [ ] Move or update portfolio examples to import from `msm_portfolios`.
- [ ] Fix the typo in `examples/portfolios/portflio_equal_weights_example.py`
  during the example migration.
- [ ] Update packaged skills that reference portfolio or virtual-fund imports.
- [ ] Add a changelog entry.

### Stage 8: Validation

- [ ] Run focused `py_compile` for moved modules.
- [ ] Run focused `ruff` for `src/msm_portfolios`, touched `src/msm` modules,
  and moved tests.
- [ ] Run focused tests for core import boundaries, core bootstrap,
  portfolio bootstrap, DataNode storage contracts, row APIs, repositories, and
  examples.
- [ ] Run `git diff --check`.
- [ ] Run MkDocs strict build when docs are updated.
- [ ] Build the wheel and verify `msm`, `msm_pricing`, and `msm_portfolios` are
  packaged.

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
