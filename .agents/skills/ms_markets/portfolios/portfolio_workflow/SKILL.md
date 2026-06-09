---
name: mainsequence-markets-portfolio-workflow
description: Use this skill when creating, extending, reviewing, or documenting msm_portfolios workflows, including portfolio DataNodes, portfolio metadata, portfolio construction examples, contributed price/signal nodes, and portfolio calculations that depend on core PortfolioTable identity.
---

# Main Sequence Markets Portfolio Workflow

Use this skill for `msm_portfolios` concepts: portfolio calculation DataNodes,
portfolio metadata, rebalance/signal workflows, and contributed portfolio price
sources. Core `msm` owns `PortfolioTable` identity, account target-position
exposure rows, and virtual-fund allocation state.

## Read First

Before changing portfolio workflow code, inspect:

1. `src/msm/models/portfolios/core.py`
2. `src/msm_portfolios/models/portfolios/metadata.py`
3. `src/msm_portfolios/data_nodes/portfolios/storage.py`
4. `src/msm_portfolios/data_nodes/portfolios/__init__.py`
5. `docs/knowledge/msm_portfolios/portfolios/index.md`
6. `docs/knowledge/msm/accounts/index.md`

## Account Target Exposure Boundary

Core `msm` owns account registry rows:

```text
AccountAllocationModelTable
AccountTargetAllocationTable
PositionSetTable
```

Core `msm` owns account target exposure storage:

```text
TargetPositionsStorage
  time_index
  position_set_uid -> PositionSetTable.uid
  target_type      asset | portfolio
  target_uid       canonical non-null target UID
  asset_uid        nullable -> AssetTable.uid
  portfolio_uid    nullable -> PortfolioTable.uid
```

Rules:

- Do not create `AssetTable` rows for portfolios.
- Do not use `PortfolioTable.portfolio_index_uid` as account target identity.
- Do not write target-position rows with `asset_identifier`.
- Asset target rows use `target_type="asset"`, `target_uid=asset_uid`, and
  `portfolio_uid=None`.
- Portfolio target rows use `target_type="portfolio"`, `target_uid=portfolio_uid`,
  and `asset_uid=None`.
- Exactly one exposure column must be present:
  `weight_notional_exposure`, `constant_notional_exposure`, or
  `single_asset_quantity`.

## Runtime Pattern

Use `msm.start_engine(...)` for account target positions that reference
portfolios. Use `msm_portfolios.start_engine(...)` only when attaching
portfolio calculation, portfolio metadata, or portfolio storage tables.

```python
import msm

msm.start_engine(
    models=[
        "AssetType",
        "Asset",
        "IndexType",
        "Index",
        "AccountAllocationModel",
        "AccountGroup",
        "Account",
        "AccountTargetAllocation",
        "PositionSet",
        "Portfolio",
        "TargetPositionsStorage",
    ]
)
```

Example workflows should stay chainable. The reusable portfolio example exposes
`build_equal_weight_portfolio(run_data_nodes=True, runtime_models=None)` so
other examples can pass a superset model list and avoid starting a second
incompatible runtime.

Configured interpolation storage is dynamic and must stay out of static runtime
model lists. For the equal-weight portfolio example, run:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation step derives the configured interpolation table from the
registered source `TimeIndexMetaTable` UID and cadence, creates/applies the dynamic
Alembic revision if needed, and verifies the `TimeIndexMetaTable`. If an older
registered source storage row is missing cadence metadata, the preparation step
may patch only that source metadata to the model-declared cadence before
deriving the dynamic table. Normal runtime code then attaches only static models
and fails clearly if the dynamic table has not been prepared.

Portfolio construction must consume prices through an explicit dependency:

```text
source price DataNode -> InterpolatedPrices -> SignalWeights -> PortfoliosDataNode
```

`PortfoliosDataNode` must not construct `InterpolatedPrices` from
`AssetsConfiguration`/`PricesConfiguration`. If persistent interpolation is
needed, prepare or attach the interpolation node first and pass it as
`PortfolioBuildConfiguration.price_source_instance`. Keep any local price
alignment inside portfolio calculation as a temporary calculation step only.

Current portfolio build contract:

```text
PortfolioBuildConfiguration
  price_source_instance     DataNode | APIDataNode
  price_column              close | open | vwap | ...
  price_alignment_policy    PriceAlignmentPolicy
  portfolio_prices_frequency
  execution_configuration
  backtesting_weights_configuration
```

Rules:

- `PortfolioBuildConfiguration` must not contain `assets_configuration`.
- `price_source_instance` is the recoverable upstream price dependency. It may
  be `InterpolatedPrices`, another compatible DataNode, or an `APIDataNode`
  built from a registered TimeIndexMetaTable UID.
- `InterpolatedPricesConfig` accepts either `source_price_instance` or
  `source_time_index_meta_table_uid`. Use the instance path when the raw/source
  price node is already in the graph; use the UID path only to attach an
  already registered compatible source table through `APIDataNode`.
- `InterpolatedPrices.dependencies()` must expose the resolved source price
  object in both cases.
- Persistent interpolation belongs to `msm_portfolios.contrib.prices`, not to
  `PortfoliosDataNode`.
- `PortfoliosDataNode.dependencies()` must expose both `signal_weights` and
  `price_source`.
- The authoritative portfolio universe is the signal output frame. A signal
  `get_asset_list()` is preflight/context only.
- Required priced assets are derived from signal output, previous portfolio
  weights that still need valuation or liquidation, and any explicit portfolio
  value override asset.
- Price sources may contain extra assets; portfolio calculation filters to the
  required signal universe.
- Missing required price assets must be logged with the price source, date
  range, price column, and policy. Strict policy fails; permissive policy logs
  and continues when the downstream calculation can still produce a usable
  frame.
- Local reindex/forward-fill inside `PortfoliosDataNode` is only calculation
  alignment. It must not create persistent storage or hide a price DataNode.

Contributed signal rules:

- `FixedWeightsConfig` must not require asset/price configuration for portfolio
  core behavior.
- External weights and market-cap signals must receive their asset universe or
  market-data dependencies explicitly.
- ETF replication must expose both basket and ETF price sources explicitly.
- Intraday trend must receive its price source explicitly.
- Contributed signals must not call `get_interpolated_prices_timeseries(...)`
  internally.

The legacy `get_interpolated_prices_timeseries(...)` helper may remain as a
non-core transition/helper path in the contributed price package. Do not use it
from portfolio core or contributed signals.

## Write Pattern

```python
from msm.api.portfolios import Portfolio
from msm.data_nodes.accounts import TargetPositions
from msm.services import build_target_positions_frame

portfolio_sleeve = Portfolio.upsert(unique_identifier="example-sleeve")

frame = build_target_positions_frame(
    target_positions_date=position_set.position_set_time,
    position_set_uid=position_set.uid,
    positions=[
        {"asset_uid": btc_asset.uid, "weight_notional_exposure": 0.6},
        {"portfolio_uid": portfolio_sleeve.uid, "weight_notional_exposure": 0.4},
    ],
)

node = TargetPositions(config=TargetPositions.default_config())
node.set_frame(frame)
error_on_last_update, persisted = node.run(debug_mode=True, force_update=True)
if error_on_last_update:
    raise RuntimeError("TargetPositions update failed.")
```

Portfolio target rows store mandate intent. They are not custody holdings and
they are not expanded automatically.

## Expansion Pattern

Use `expand_portfolio_target_positions(...)` only when a downstream workflow
explicitly needs asset-level exposure:

```python
from msm.services import expand_portfolio_target_positions

expanded = expand_portfolio_target_positions(
    frame,
    portfolio_weight_resolver=lambda portfolio_uid: [
        {"asset_uid": btc_asset.uid, "weight": 0.25},
        {"asset_uid": eth_asset.uid, "weight": 0.75},
    ],
)
```

The resolver boundary is intentional. It forces the caller to choose the
portfolio composition source and valuation time instead of hiding that policy in
the account target-position table.

## Validation

For explicit portfolio price-source changes, run:

```bash
uv run --extra portfolios --extra dev ruff check src/msm_portfolios/configuration.py src/msm_portfolios/data_nodes/portfolios src/msm_portfolios/contrib/signals examples/msm_portfolios tests/msm_portfolios/data_nodes/test_portfolio_contracts.py
uv run --extra portfolios --extra dev pytest tests/msm_portfolios/data_nodes/test_portfolio_contracts.py tests/msm_portfolios/examples/test_equal_weight_portfolio_schema.py tests/msm_portfolios/configuration/test_prices_configuration.py
uv run --extra portfolios --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
```

For portfolio target-position changes, run:

```bash
uv run --extra dev ruff check src/msm/data_nodes/accounts src/msm/services/target_positions.py tests/msm/data_nodes/test_target_positions_contracts.py
uv run --extra dev pytest tests/msm/data_nodes/test_target_positions_contracts.py tests/msm_portfolios/models/test_model_graph.py
```
