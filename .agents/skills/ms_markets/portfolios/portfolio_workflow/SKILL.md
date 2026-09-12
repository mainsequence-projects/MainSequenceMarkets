---
name: mainsequence-markets-portfolio-workflow
description: Use this skill when creating, extending, reviewing, or documenting msm_portfolios workflows, including portfolio TimeIndexTableUpdaters, portfolio metadata, signals and rebalancing, position-aware accounting, lifecycle cash flows, price/FX valuation, canonical ledgers, and portfolio calculations that depend on core PortfolioTable identity.
---

# Main Sequence Markets Portfolio Workflow

Use this skill for `msm_portfolios` concepts: portfolio calculation TimeIndexTableUpdaters,
portfolio metadata, rebalance/signal workflows, contributed portfolio price
sources, and portfolio classification workflows. Core `msm` owns
`PortfolioTable` identity, `PortfolioGroupTable` classification rows, account
target-position exposure rows, and virtual-fund allocation state.

Route theoretical spreads, baskets, ratios, butterflies, and hedged market
indexes to the derived-index workflow skill. A Portfolio may reference one as
a benchmark or signal input, but must not reuse portfolio weights or holdings
as calculation legs or resolved-index provenance.

## Read First

Before changing portfolio workflow code, inspect:

1. `src/msm/models/portfolios/core.py`
2. `src/msm/models/portfolios/groups.py`
3. `src/msm_portfolios/models/portfolios/metadata.py`
4. `src/msm_portfolios/data_nodes/portfolios/storage.py`
5. `src/msm_portfolios/data_nodes/portfolios/__init__.py`
6. `docs/knowledge/msm_portfolios/portfolios/index.md`
7. `docs/knowledge/msm/accounts/index.md`

For position-aware accounting, lifecycle cash flows, or portfolio valuation,
also read:

8. `docs/knowledge/msm_portfolios/portfolios/accounting.md`
9. `docs/ADR/0042-position-cash-flow-portfolio-accounting.md`
10. [references/position_accounting.md](references/position_accounting.md)

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
- Do not use `PortfolioTable.published_index_uid` as account target identity or
  as the portfolio weights/values storage key.
- Use `PortfolioTable.uid` for account target identity and
  `PortfolioTable.unique_identifier` as `portfolio_identifier` in portfolio
  storage.
- Every `PortfolioTable` row must have a non-null `calendar_uid` that
  references `CalendarTable.uid`. Do not add or write redundant calendar-name
  fields on portfolio rows.
- `PortfolioTable.signal_uid` is nullable because portfolio rows can be created
  before a signal workflow runs, but when present it must be a real foreign key
  reference to `SignalMetadataTable.signal_uid`.
- `PortfolioWeightsStorage.portfolio_identifier` and
  `PortfoliosStorage.portfolio_identifier` must reference
  `PortfolioTable.unique_identifier`. `PortfolioWeightsStorage.asset_identifier`
  must reference `AssetTable.unique_identifier`.
- Do not write target-position rows with `asset_identifier`.
- Asset target rows use `target_type="asset"`, `target_uid=asset_uid`, and
  `portfolio_uid=None`.
- Portfolio target rows use `target_type="portfolio"`, `target_uid=portfolio_uid`,
  and `asset_uid=None`.
- Exactly one exposure column must be present:
  `weight_notional_exposure`, `constant_notional_exposure`, or
  `single_asset_quantity`.

## Portfolio Group Boundary

Portfolio groups are optional classification metadata, not portfolio identity
and not portfolio construction state.

```text
PortfolioGroupTable
  uid
  unique_identifier
  display_name

PortfolioGroupMembershipTable
  portfolio_group_uid -> PortfolioGroupTable.uid
  portfolio_uid       -> PortfolioTable.uid
  unique(portfolio_group_uid, portfolio_uid)
```

Rules:

- Do not add `portfolio_group_uid` to `PortfolioTable`.
- Use `msm.api.portfolios.PortfolioGroup.add(...)` to create or upsert groups.
- Use `PortfolioGroup.add_portfolio(...)`,
  `PortfolioGroup.remove_portfolio(...)`, `PortfolioGroup.get_portfolios(...)`,
  and `PortfolioGroup.get_groups_for_portfolio(...)` for relationship
  workflows.
- Deleting a group removes only membership rows through cascade. It must not
  delete portfolios.
- Deleting a portfolio removes only membership rows through cascade. It must not
  delete groups.
- FastAPI portfolio-group operations live under `/api/v1/portfolio-group/`.

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

The equal-weight example uses contributed `InterpolatedPrices`, whose output
storage is a dynamic `PlatformTimeIndexMetaTable` keyed from the source
`TimeIndexMetaTable` UID and cadence. That schema preparation belongs to
`msm_portfolios.contrib.prices`; it is not portfolio core registration and it
does not mean `PortfoliosDataNode` may construct prices internally. For the
example, prepare that interpolation storage before the normal run:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation step derives only the contributed interpolation output table,
creates/applies its dynamic Alembic revision if needed, and verifies the
`TimeIndexMetaTable`. Normal runtime code still builds the graph explicitly as
source price or valuation node -> interpolation when needed -> signal node -> portfolio node. If
the backend dependency tree was created by an older graph, run the top-level
portfolio node once with `refresh_dependency_tree=True`, or call
`set_relation_tree(force_rebuild=True)` during setup, so stale backend edges are
cleared before dependency execution.

Portfolio construction must expose execution and valuation as separate temporal owners:

```text
SignalWeights --------------------+
                                   +--> PortfolioWeights --> PortfolioWeightsStorage
calendar events / execution bars -+           |
execution valuations --------------+           |
                                               v
valuation source ----------------------> PortfoliosDataNode --> PortfoliosStorage
                                                               |
                                                               v
                                                     optional PortfolioAnalytics
```

`PortfoliosDataNode` must not construct `InterpolatedPrices` from
`AssetsConfiguration`/`PricesConfiguration`. If persistent interpolation is
needed, prepare or attach the interpolation node first and pass it as
`PortfolioBuildConfiguration.valuation_source_instance`. Keep any local
valuation alignment inside portfolio calculation as bounded per-asset as-of
selection at source observation timestamps only.

Current portfolio build contract:

```text
PortfolioBuildConfiguration
  valuation_source_instance TimeIndexTableUpdater | TimeIndexTableRef
  valuation_column          str, defaults to close
  valuation_alignment_policy ValuationAlignmentPolicy
  execution_configuration
  backtesting_weights_configuration
```

Rules:

- `PortfolioBuildConfiguration` must not contain `assets_configuration`.
- `valuation_source_instance` is the recoverable upstream valuation dependency.
  It may be `InterpolatedPrices`, another compatible TimeIndexTableUpdater, or an
  `TimeIndexTableRef` built from a registered TimeIndexMetaTable UID.
- `portfolio_prices_frequency` is not part of the core contract. Canonical
  execution and valuation nodes must not create a generic date range or
  resample their outputs. Reporting frequency belongs to `PortfolioAnalytics`.
- `valuation_column` is a strict string column name. Portfolio core must not
  force `close`, `open`, `vwap`, or any other OHLC enum. Specific contributed
  strategies may validate additional OHLC fields only when they truly need
  those fields.
- For custom valuation sources, keep the source column name as published. For
  example, pass `valuation_column="fair_value"` for a fair-value table instead
  of renaming the column to `close`. Use
  `examples/msm_portfolios/portfolio_custom_valuation_column_example.py` as the
  reference configuration path.
- `InterpolatedPricesConfig` accepts either `source_price_instance` or
  `source_time_index_meta_table_uid`. Use the instance path when the raw/source
  price node is already in the graph; use the UID path only to attach an
  already registered compatible source table through `TimeIndexTableRef`.
- `InterpolatedPrices.dependencies()` must expose the resolved source price
  object in both cases.
- Persistent interpolation belongs to `msm_portfolios.contrib.prices`, not to
  `PortfoliosDataNode`.
- `PortfolioWeights.dependencies()` exposes `signal_weights` and the explicit
  execution valuation source. It owns event selection, signal cutoff, previous
  executed state, and `PortfolioWeightsStorage` production.
- `PortfoliosDataNode.dependencies()` exposes canonical `portfolio_weights` and
  `valuation_source`. Signal weights are a transitive execution dependency, not
  a direct valuation dependency.
- `ImmediateSignal` executes only at original signal observation timestamps.
  Use `CalendarEventSignal` when the latest eligible signal should execute at a
  persisted market open or close. Its calendar identifier, session label,
  event, offset, cadence, signal selection, and execution valuation convention
  are hash-bearing configuration. The calendar identifier is required and must
  resolve to persisted `CalendarSession` rows; missing, ambiguous, or failed
  governed lookups must not fall back to a local pandas or synthetic calendar.
- `TimeWeighted` and `VolumeParticipation` are not supported public strategies
  until their bar-driven execution implementations are complete.
- The authoritative portfolio universe is the signal output frame. A signal
  `get_asset_list()` is preflight/context only.
- Required valuation assets are derived from signal output, previous portfolio
  weights that still need valuation or liquidation, and any explicit portfolio
  value override asset.
- Valuation sources may contain extra assets; portfolio calculation filters to
  the required signal universe.
- Existing portfolio output progress must be scoped by `portfolio_identifier`;
  `PortfoliosStorage` is shared and keyed by `(time_index, portfolio_identifier)`.
  A later row for another portfolio must not move this portfolio's start date.
  The authoritative portfolio update start is this portfolio's latest
  `PortfoliosStorage` timestamp for the resolved `PortfolioTable.unique_identifier`.
- Portfolio valuation timestamps come from actual valuation-source observations.
  Executed weights are selected as-of each valuation timestamp, so sparse weekly
  rebalances can drive daily valuation without daily weight rows.
- Seed valuation reads must fetch the latest eligible observation for every
  required asset in one set-based request. Enforce
  `ValuationAlignmentPolicy.maximum_staleness` per asset.
- Contributed signal progress must be scoped by `signal_uid`; `SignalWeightsStorage`
  is shared and keyed by `(time_index, signal_uid, asset_identifier)`.
  `signal_uid` is a required reference to `SignalMetadataTable.signal_uid`, so
  signal metadata must be registered before signal weights are published.
  `asset_identifier` must reference `AssetTable.unique_identifier`. A later row
  for another signal must not move this signal's start date.
- `SignalMetadataTable.signal_description` and signal `get_explanation()` text
  must be plain text or Markdown. Do not return or document HTML tags for signal
  descriptions; rendering belongs to the consuming UI.
- Missing or stale required valuation assets fail under the default strict
  policy. A permissive policy may yield no eligible rows, but it must never
  manufacture a timestamp.
- As-of selection may reindex to explicit signal, calendar, bar, or valuation
  timestamps. It must not introduce any additional economic timestamp.
- `PortfolioAnalytics` is the only portfolio component that may resample. Its
  `time_index` is the actual selected source-observation timestamp; analytical
  bucket boundaries live in `period_start` and `period_end`, and
  `source_time_index` preserves lineage.
- Repair legacy midnight-indexed `PortfoliosStorage` rows only through a
  dry-run-validated, `portfolio_identifier`-scoped inclusive tail delete using
  `TimeIndexMetaTable.delete_after_date(...)`, followed immediately by a
  deterministic portfolio replay. Require persisted `CalendarSession` and
  historical `close_time` agreement, prove the inspection reaches the latest
  stored row, and apply one portfolio at a time. Never update indexed
  coordinates in place or use raw SQL.
- `PortfoliosDataNode.run(..., update_pointers=True)` is the default portfolio
  workflow behavior. After the graph publishes, it must upsert the resolved
  `PortfolioTable` row with `signal_uid`, `signal_weights_data_node_uid`,
  `portfolio_weights_data_node_uid`, and `portfolio_data_node_uid`. Examples
  should not perform this final pointer upsert manually.
- Rerunning before a new execution event or valuation observation must return an
  empty incremental update. Job run time is never an economic timestamp.
- API reads for a portfolio's signal weights must filter by
  `PortfolioTable.signal_uid`. Do not derive the signal from
  `TimeIndexTableUpdate.build_configuration`, runtime update statistics, or distinct
  `SignalWeightsStorage.signal_uid` values because signal storage is shared by
  many signals.

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

## Position-Aware Accounting

Use `PortfolioEngine` only when the portfolio needs instrument quantities,
currency balances, obligations, or position-driven lifecycle events. Preserve
`PortfoliosDataNode` as the unchanged default when accounting configuration is
omitted or explicitly `None`.

A Portfolio is a backtest model. It has no Account and must not ingest broker
orders, trades, fills, account holdings, custody balances, or actual account
cash. The configured signal and `RebalanceStrategy` are the only source of
simulated portfolio executions. The strategy emits internal execution facts to
`PortfolioAccounting`; do not expose an external execution-fact input lane or a
compatibility fallback for one.

For the built-in position-aware path, configure a `TargetWeightExecutionModel`
on that existing strategy and provide an explicit `InstrumentExecutionSpec` for
every simulated Asset. Keep fill-time `ExecutionCostModel`s on the strategy and
holding-period funding/dividend/coupon economics in `LifecycleEventModel`s.
Variation-margin instruments change quantity without a full-notional cash leg;
their valuation model must implement the corresponding instrument-value
semantics.

`PortfolioEventLedgerStorage` is the sole authoritative position-accounting
output. `PortfolioAccounting` is the pure reducer, not a MetaTable or updater.
State, cash-flow, weights, values, and analytics are ledger-derived read models.
Do not introduce a second authoritative checkpoint or claim a cross-table
transaction requirement.

All accounting implementation work belongs to `msm_portfolios`. The existing
`TimeIndexTableUpdater`, `PlatformTimeIndexMetaTable`, and SDK-managed migration
contracts are sufficient; ADR 0042 has no `mainsequence-sdk` blocker.

Read [references/position_accounting.md](references/position_accounting.md)
before changing the accounting engine, lifecycle-model boundary, valuation/FX
contract, canonical ledger, projections, restart behavior, accounting examples,
or the ADR.

## Write Pattern

```python
from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio
from msm.data_nodes.accounts import TargetPositions
from msm.services import build_target_positions_frame

calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="EXAMPLE_CRYPTO_24_7",
    display_name="Example Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)
portfolio_sleeve = Portfolio.upsert(
    unique_identifier="example-sleeve",
    calendar_uid=calendar.uid,
)

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

For explicit portfolio valuation-source changes, run:

```bash
uv run --extra portfolios --extra dev ruff check src/msm_portfolios/configuration.py src/msm_portfolios/data_nodes/portfolios src/msm_portfolios/contrib/signals examples/msm_portfolios tests/msm_portfolios/data_nodes/test_portfolio_contracts.py
uv run --extra portfolios --extra dev pytest tests/msm_portfolios/data_nodes/test_portfolio_contracts.py tests/msm_portfolios/examples/test_equal_weight_portfolio_schema.py tests/msm_portfolios/configuration/test_prices_configuration.py
uv run --extra portfolios --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
```

For position-aware accounting changes, also run:

```bash
uv run --extra portfolios --extra dev ruff check src/msm_portfolios/accounting src/msm_portfolios/data_nodes/portfolios examples/msm_portfolios tests/msm_portfolios/accounting
uv run --extra portfolios --extra dev pytest tests/msm_portfolios/accounting/test_accounting.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_custom_cashflow_model_example.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_perpetual_funding_example.py
```

For portfolio target-position changes, run:

```bash
uv run --extra dev ruff check src/msm/data_nodes/accounts src/msm/services/target_positions.py tests/msm/data_nodes/test_target_positions_contracts.py
uv run --extra dev pytest tests/msm/data_nodes/test_target_positions_contracts.py tests/msm_portfolios/models/test_model_graph.py
```
