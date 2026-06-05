---
name: mainsequence-markets-portfolio-workflow
description: Use this skill when creating, extending, reviewing, or documenting msm_portfolios workflows, including PortfolioTable, portfolio DataNodes, and account target-position exposure rows that reference portfolios.
---

# Main Sequence Markets Portfolio Workflow

Use this skill for `msm_portfolios` concepts: portfolio identity, portfolio
DataNode storage, virtual-fund allocation, and account target-position exposure
to portfolio sleeves.

## Read First

Before changing portfolio/account target exposure code, inspect:

1. `src/msm_portfolios/models/portfolios/core.py`
2. `src/msm_portfolios/data_nodes/storage.py`
3. `src/msm_portfolios/data_nodes/target_positions.py`
4. `src/msm_portfolios/services/target_positions.py`
5. `docs/knowledge/msm_portfolios/portfolios/index.md`
6. `docs/knowledge/msm/accounts/index.md`

## Account Target Exposure Boundary

Core `msm` owns account registry rows:

```text
AccountModelPortfolioTable
AccountTargetPortfolioTable
PositionSetTable
```

`msm_portfolios` owns portfolio-aware target exposure storage:

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

Use `msm_portfolios.start_engine(...)` when target positions reference
portfolios:

```python
import msm_portfolios

msm_portfolios.start_engine(
    models=[
        "AssetType",
        "Asset",
        "IndexType",
        "Index",
        "AccountModelPortfolio",
        "AccountGroup",
        "Account",
        "AccountTargetPortfolio",
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
registered source price storage hash and cadence, creates/applies the dynamic
Alembic revision if needed, and verifies the `TimeIndexMetaTable`. Normal
runtime code then attaches only static models and fails clearly if the dynamic
table has not been prepared.

## Write Pattern

```python
from msm_portfolios.api.portfolios import Portfolio
from msm_portfolios.data_nodes import TargetPositions
from msm_portfolios.services import build_target_positions_frame

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
from msm_portfolios.services import expand_portfolio_target_positions

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

For portfolio target-position changes, run:

```bash
uv run --extra dev ruff check src/msm_portfolios/data_nodes/target_positions.py src/msm_portfolios/services/target_positions.py tests/msm_portfolios/data_nodes/test_target_positions_contracts.py
uv run --extra dev pytest tests/msm_portfolios/data_nodes/test_target_positions_contracts.py tests/msm_portfolios/models/test_model_graph.py
```
