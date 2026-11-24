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
4. `src/msm_portfolios/time_index/portfolios/storage.py`
5. `src/msm_portfolios/time_index/portfolios/__init__.py`
6. `docs/knowledge/msm_portfolios/portfolios/index.md`
7. `docs/knowledge/msm/accounts/index.md`

For the calendar a portfolio references (getting one, reading its sessions,
correcting it), read
`.agents/skills/ms_markets/calendars/calendar_workflow/SKILL.md`.

For an application that computes or receives signals or runs portfolios, read
`.agents/skills/ms_markets/platform/producer_boundary/SKILL.md` first (ADR 0060):
signal weights, portfolio weights and values are published to Markets through
`SignalWeightsSeries`, `PortfolioWeightsSeries` and `PortfolioValuesSeries` and the
recipes of `msm_portfolios.recipes`; a producer keeps no table for them, registers no
table with Markets and grants Markets no role.

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
- Exactly one exposure column must be present: `weight_notional_exposure`, or
  `single_asset_quantity` on an asset row.

## Retiring A Portfolio

Account history is never rewritten to remove a portfolio (ADR 0049). Target
snapshots and virtual funds reference `PortfolioTable` with `RESTRICT`; do not
delete them, relax those foreign keys, or delete a portfolio that accounts
referenced. Retire it instead:

- `MarketsClient.portfolio_account_targets(uid)`
  (`GET /api/v1/portfolio/{uid}/account-targets/`) lists the accounts whose
  current target names the portfolio. Write their targets without it first.
- `MarketsClient.retire_portfolio(uid)` (`POST /api/v1/portfolio/{uid}/retire/`)
  sets `Portfolio.retired_at`; it is refused while that list is not empty.
  `reinstate_portfolio(uid)` clears it.
- While retired, no target snapshot may name the portfolio, whatever its date,
  no virtual-fund holdings are written for it from `retired_at` on, lists and
  target search hide it unless `include_retired=true`, and the portfolio
  updaters write nothing dated at or after `retired_at`.
- Delete a portfolio only when nothing references it.
  `DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/`
  delete it with its rows in its seven datasets (weights, values, rebalance
  state, analytics, event ledger, state, cash flows), in one transaction.
  `MarketsClient.delete_portfolio(uid)` and `bulk_delete_portfolios(uids)` call
  them. They refuse with `409`, deleting nothing, while virtual funds or
  account target rows name it, or while another application's table with a
  `RESTRICT` key to it holds rows of it; that application deletes its rows
  first.
  `POST /api/v1/portfolio/bulk-delete/preflight/` reports the rows per dataset
  and every blocker. These routes are the only portfolio delete:
  `Portfolio.delete` raises `MarketsOperationUnsupported` under both backends
  and deletes nothing; a test double for it should refuse the same way.

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

Before `InterpolatedPrices` runs, every asset it prices must be linked to a
stored calendar (ADR 0056):

```python
from msm.api.assets import AssetCalendar

result = AssetCalendar.link_many(
    [asset.unique_identifier for asset in assets],
    calendar_uid=calendar.uid,
)
assert not result.unknown
```

One call links them all in one transaction. Do not loop over
`AssetCalendar.upsert`.

- There is no default calendar. An asset with no `AssetCalendar` link fails the
  whole price update, and the error names it. Link the asset; do not catch the
  error.
- The `asset_list` of `InterpolatedPricesConfig` holds identifiers only. A
  `calendar` key in a scope mapping is refused.
- An `ImmediateSignal` or `CalendarEventSignal` must use the calendar of
  `Portfolio.calendar_uid`. `PortfolioValues` refuses to run when its
  `calendar_identifier` names another calendar.
- Attach `AssetCalendar` in the runtime models where price updates run.

Example workflows should stay chainable. The reusable portfolio example exposes
`build_equal_weight_portfolio(run_updaters=True, runtime_models=None)` so
other examples can pass a superset model list and avoid starting a second
incompatible runtime.

`InterpolatedPrices` writes only the table of its configuration, which the producer
owns. Declare it on the producer's own base, migrate it with the producer's provider,
and pass it as `output_table=`:

```python
from metatables import sqlalchemy_naming_convention
from msm.storage_instances import configured_time_index_instance
from msm_portfolios.time_index.prices.storage import (
    InterpolatedPricesStorage,
    interpolated_prices_instance_key,
)
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


ProjectInterpolatedPrices = configured_time_index_instance(
    InterpolatedPricesStorage,
    instance_key=interpolated_prices_instance_key(
        source_table_name="my_project__bars_1d",  # ProjectBars.__table__.name
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    ),
    cadence="1d",  # the upsample frequency
    namespace="my-project",
    storage_app="my_project",
    base=Base,
)
```

- The four arguments of `interpolated_prices_instance_key` are the table's whole key.
  The source is its physical table name, never its UID, so one committed revision
  creates the table in every Environment. Never generate a revision per Environment.
- `InterpolatedPrices` computes the same key when it runs and refuses a class of
  another contract, key or cadence. Never invent a key or give the table another name.
- A changed configuration is a new table and a new committed revision of the same
  provider. Apply that provider's earlier revisions, then autogenerate with
  `metatables migrations revision`. Never use another provider's history instead.
- A first run fills the table from `offset_start` (2017-07-20 by default), as far as the
  source still holds bars. Set an earlier one before that run when older bars matter.
- A table registered with the wrong cadence is refused. Correct its class and run its
  provider's `metatables migrations upgrade`, which registers the class's cadence.
- `namespace`, `storage_app` and `base` have no default. A producer never passes
  Markets' own, and never applies or extends Markets' migrations for this table.
- This is the price source's schema, not portfolio core registration, and it does
  not mean a portfolio node may construct prices internally.

The equal-weight example is such a producer, with its provider and committed revision
in `examples/msm_portfolios/portfolio_equal_weights_migrations/`. From the repository
root, after Markets' own migrations:

```bash
metatables --local migrations upgrade --provider examples.msm_portfolios.portfolio_equal_weights_migrations:migration head
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

Both write only to MetaTables' local SQLite runtime: a sandbox is a separate database,
never another namespace. With updaters on, the example currently stops in the rebalance
(`FixedWeights` dates its signal 2018-01-02, the example's bars begin in May 2026);
`--no-run-updaters` runs to the end. Normal runtime code still builds the graph explicitly as
source price or valuation node -> interpolation when needed -> signal node -> portfolio node. If
the backend dependency tree was created by an older graph, run the top-level
portfolio node once with `refresh_dependency_tree=True`, or call
`set_relation_tree(force_rebuild=True)` during setup, so stale backend edges are
cleared before dependency execution.

Portfolio construction must expose execution and valuation as separate temporal owners:

```text
SignalWeights --------------------+
calendar events / execution bars -+--> PortfolioRebalance --> rebalance state (fills)
                                                                |
valuation source, FX, lifecycle inputs --------------> PortfolioEngine --> event ledger
                                                                |
                                        +-----------------------+-----------------------+
                                        v                                               v
                         PortfolioWeights --> PortfolioWeightsStorage    PortfolioValues --> PortfoliosStorage
                                                                                          |
                                                                                          v
                                                                                optional PortfolioAnalytics
```

No portfolio node constructs `InterpolatedPrices` from
`AssetsConfiguration`/`PricesConfiguration`. If persistent interpolation is
needed, prepare or attach the interpolation node first and pass it as
`PortfolioBuildConfiguration.valuation_source_instance`. The ledger values each
held asset at its last observation at or before each ledger time, at source
observation timestamps only.

Current portfolio build contract:

```text
PortfolioBuildConfiguration
  valuation_source_instance TimeIndexTableUpdater | TimeIndexTableRef
  valuation_column          str, defaults to close
  valuation_asset_identifier the portfolio's currency
  fx_source_instance        optional
  backtesting_weights_configuration
  accounting_configuration  PortfolioAccountingConfiguration, required (ADR 0065)
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
- Persistent interpolation belongs to `msm_portfolios.contrib.prices`, not to a
  portfolio node.
- `PortfolioRebalance.dependencies()` is the valuation source (and FX source) it
  trades at, unless the strategy has bars of its own, plus the strategy's declared
  inputs; it reads the signal, a published series, without running it. It owns
  event selection, signal cutoff and the rebalance state.
- `PortfolioEngine.dependencies()` is the rebalance state, the valuation source, the
  FX source and the valuation and lifecycle models' inputs.
  `PortfolioWeights.dependencies()` is the engine, and
  `PortfolioValues.dependencies()` the weights node.
- Prices are stamped at the moment they were observed, and a trade happens only
  at an observed price (ADR 0058). Every strategy follows it: the earliest moment
  is the strategy's moment while the portfolio calendar is in session, otherwise
  the next session start; each asset then trades at the first valuation-source row
  at or after it, strictly after the signal and inside a session
  (`market_open < time_index <= market_close`). Interpolated rows never count, the
  fill column must be a close or a mark (`open`, `high`, `low`, `vwap` are refused),
  assets fill independently, only a fill writes a rebalance-state row, and a
  missing price makes the trade wait. Strategies with their own bars trade at them
  under the same conditions.
- `TimeWeighted`, `VolumeParticipation`, `LiquidityConstrained` and
  `TrailingAverageDailyVolumeParticipation` fill each order over several of their own
  bars (#90). The order is sized once, at the decision: target weight x NAV / price,
  with each asset's last bar strictly before the earliest moment, which is the first of
  the strategy's bars after the signal. Each bar fills a slice the strategy decides
  (elapsed time, volume, liquidity, trailing daily volume), never more than the order
  has open, and their `execution_policy` applies the cash setting to the slices. Their
  rows record the book (`held_shares`, `cash`) like `ImmediateSignal`'s, with the
  strategy's facts under `strategy_state["bar"]`; no `pending` or `superseded` rows.
  The book's unit is the ledger's `initial_nav` (ADR 0065); it turns a bar's capacity
  into shares of the order.
- `ImmediateSignal` rebalances at every new signal. It requires
  `calendar_events_instance` (a `PortfolioCalendarEvents` publishing both
  `market_open` and `market_close`) and `calendar_identifier`, the portfolio's
  calendar (`CRYPTO_24_7` for 24/7 assets).
- `PortfolioEngine` books exactly the fills `PortfolioRebalance` recorded
  (`portfolio_rebalance_instance`); it builds no schedule and looks up no mark for
  a fill. Share counts are fixed once at the decision (weight x NAV / price, with
  the last prices before the earliest moment) and each asset fills them at its own
  price. The decision reads the last prices and FX rates before the earliest moment,
  however old.
- A held asset is always valued at its last observed price (and FX at its last
  rate), however old. Past `maximum_staleness` it is marked stale; only a held asset
  with no observed price at all raises. `fail_on_missing_values=True` on
  `MarketPriceValuationModel` refuses a stale price instead (default `False`).
- `execution_policy` (`ExecutionPolicy`), on every built-in strategy, holds the
  execution choices; its defaults are the owner's decisions: shares sized at the decision, no negative
  cash (`negative_cash`: `fraction_of_nav`, or `fixed_amount`, converted with the
  ledger's `initial_nav`),
  sells before buys, pro-rata allocation of too little cash, cut-and-cancel of an
  uncovered buy once the
  rebalance's sells have filled (reason `insufficient_cash`), and the portfolio
  calendar gating trades. The facts (observed price strictly after the signal, at or
  after the earliest moment, in session) are not settings.
- Every rebalance strategy has `signal_lifetime` (a `timedelta`, default `None`: a
  signal never expires). An event at `t` acts only on the latest signal, and not at
  all when `t - signal time_index > signal_lifetime` (exactly that old is still
  valid); there is no fallback to an earlier signal. The age is economic time from
  the signal's `time_index`, never the job's clock. A target too old at its earliest
  moment (or first bar) never trades; a running rebalance stops at its next event,
  keeps what it filled, and each unfinished order writes an `expired` row without a
  price; the ledger records it as progress. A lifetime is hashed; `None` leaves the
  strategy's and the portfolio's identities unchanged.
- `PortfolioBuildConfiguration.valuation_asset_identifier` (required) is the
  portfolio's currency; the accounting configuration has none. Declare
  `fx_source_instance` when an asset is quoted in another currency: the valuation
  source then needs `price_asset_identifier`, and prices convert at the last
  observed rate. Without it, a foreign quote is refused.
- Every portfolio keeps a ledger (ADR 0065): `accounting_configuration` states its
  `initial_nav`, `initial_state_time_index`, valuation model and lifecycle models.
  The ledger values positions at their prices, so weights drift with prices between
  rebalances. Costs are the strategy's `execution_cost_model_instances`.
- A valuation source's prices are at the level its producer chose; the source states
  it in `events_in_price` (`"adjusted"`, the default: every event of the asset is in
  the price; a tuple names exactly what is; `()` for unadjusted). A
  `TimeIndexTableRef` is adjusted. `InterpolatedPrices` adjusts nothing. On prices
  that do not include an event, a run refuses while the portfolio holds or buys an
  asset whose type lists it (`AssetType.event_types`) and no lifecycle model books it
  (`booked_event_types`); a model that books an event the prices include is refused
  at configuration, since it would count it twice.
- Use `CalendarEventSignal` when the latest eligible signal should execute at a
  persisted market open or close. Its calendar identifier, session label,
  event, offset, cadence, signal selection, and execution valuation convention
  are hash-bearing configuration. The calendar identifier is required and must
  be the `unique_identifier` of a stored `Calendar`; a `source_identifier` does
  not name one. Sessions are computed from the calendar's `CalendarSessionRule`
  and `CalendarException` rows with `Calendar.sessions(...)`. Missing or failed
  governed lookups must not fall back to a local pandas or synthetic calendar.
  A window outside the calendar's `valid_from`..`valid_to` raises
  `CalendarRangeError`.
- The authoritative portfolio universe is the signal output frame. A signal
  `get_asset_list()` is preflight/context only.
- The ledger reads the valuation source's rows of the assets the portfolio's fills
  trade; valuation sources may contain extra assets.
- `SignalWeights`, `PortfolioWeights` and `PortfolioValues` are not
  `TimeIndexTableUpdater`s (ADR 0060): they take no `output_table=` and publish
  through the series row classes. Their progress is the published series itself
  (`bounds`, `last`), scoped by key: a portfolio's start is its latest published
  value for the resolved `PortfolioTable.unique_identifier`; a later row for another
  portfolio never moves it. Running the same window twice publishes nothing.
- Portfolio value timestamps are ledger times: fills, lifecycle events and actual
  valuation-source observations, so sparse weekly rebalances can drive daily
  valuation without daily weight rows. A weights row is published for each ledger
  event that changes a position.
- Seed reads must fetch the latest eligible observation for every required asset in
  one set-based request.
- Contributed signal progress is scoped by `signal_uid`: the signal's published
  `SignalWeightsSeries` (`bounds`, and `last(by="asset")` per asset). `signal_uid`
  references `SignalMetadataTable.signal_uid`, so a signal's metadata exists before
  its weights are published (`SignalWeights.run()` and `publish_signal_weights`
  create it). `asset_identifier` must reference `AssetTable.unique_identifier`.
  Markets refuses an observation at or before the signal's last stored time, and
  closes at `0` an asset the signal held that a new observation leaves out.
- `SignalMetadataTable.signal_description` and signal `get_explanation()` text
  must be plain text or Markdown. Do not return or document HTML tags for signal
  descriptions; rendering belongs to the consuming UI.
- A held asset with no observed price fails the event; nothing manufactures a
  timestamp.
- As-of selection may reindex to explicit signal, calendar, bar, or valuation
  timestamps. It must not introduce any additional economic timestamp.
- `PortfolioAnalytics` is the only portfolio component that may resample. Its
  `time_index` is the actual selected source-observation timestamp; analytical
  bucket boundaries live in `period_start` and `period_end`, and
  `source_time_index` preserves lineage.
- Repair legacy midnight-indexed `PortfoliosStorage` rows only through a
  dry-run-validated, `portfolio_identifier`-scoped inclusive tail delete using
  `TimeIndexMetaTable.delete_after_date(...)`, followed immediately by a
  deterministic portfolio replay. Require agreement between the session closes
  computed from the stored calendar and the historical `close_time`, prove the
  inspection reaches the latest stored row, and apply one portfolio at a time.
  Never update indexed coordinates in place or use raw SQL.
- `PortfolioValues.run(..., update_pointers=True)` is the default portfolio
  workflow behavior: after it publishes, it upserts the resolved `PortfolioTable`
  row with its `signal_uid`. The three `*_table_update_uid` pointers name update
  records of bound tables, which a publishing node does not have; they are left as
  they are (ADR 0060 leaves their replacement undecided). Prefer
  `msm_portfolios.recipes.run_portfolio`, which runs the chain in order.
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
- Weights an application receives (not computes) use `ApplicationWeights`, or
  `msm_portfolios.recipes.publish_signal_weights` directly; do not write a signal
  class for them. Its identity is `ApplicationWeightsConfig(provider, key)`, never the
  weights; Markets refuses unknown assets and observations at or before the last
  stored time.
- External weights and market-cap signals must receive their asset universe or
  market-data dependencies explicitly.
- ETF replication must expose both basket and ETF price sources explicitly.
- Intraday trend must receive its price source explicitly.
- Contributed signals must not build `InterpolatedPrices` internally: they receive
  the price source, and the producer binds its table.

## Position-Aware Accounting

Every portfolio keeps a ledger, which `PortfolioEngine` books: instrument
quantities, currency balances, obligations, and position-driven lifecycle events.
`PortfolioWeights` and `PortfolioValues` publish projections of it.

A Portfolio is a backtest model. It has no Account and must not ingest broker
orders, trades, fills, account holdings, custody balances, or actual account
cash. The configured signal and `RebalanceStrategy` are the only source of
simulated portfolio executions. The strategy emits internal execution facts to
`PortfolioAccounting`; do not expose an external execution-fact input lane or a
compatibility fallback for one.

A strategy without `execution_model_instance` trades with the default model:
fractional units (`quantity_step=None`), multiplier 1, cash settlement, quoted in
the currency of the asset's valuation rows. To change that, configure a
`TargetWeightExecutionModel` on the strategy with an explicit
`InstrumentExecutionSpec` for every simulated Asset. Keep fill-time
`ExecutionCostModel`s on the strategy and
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
`TimeIndexTableUpdater`, `PlatformTimeIndexMetaTable`, and MetaTables-managed migration
contracts are sufficient; ADR 0042 has no `mainsequence-sdk` blocker.

Read [references/position_accounting.md](references/position_accounting.md)
before changing the accounting engine, lifecycle-model boundary, valuation/FX
contract, canonical ledger, projections, restart behavior, accounting examples,
or the ADR.

## Write Pattern

```python
from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio
from msm.time_index.accounts import TargetPositions
from msm.services import build_target_positions_frame

calendar = Calendar.create_from_pandas_calendar(
    "24/7",
    "EXAMPLE_CRYPTO_24_7",
    display_name="Example Crypto 24/7",
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
uv run --extra portfolios --extra dev ruff check src/msm_portfolios/configuration.py src/msm_portfolios/time_index/portfolios src/msm_portfolios/contrib/signals examples/msm_portfolios tests/msm_portfolios/time_index/test_portfolio_contracts.py
uv run --extra portfolios --extra dev pytest tests/msm_portfolios/time_index/test_portfolio_contracts.py tests/msm_portfolios/examples/test_equal_weight_portfolio_schema.py tests/msm_portfolios/configuration/test_prices_configuration.py
uv run --extra portfolios --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
```

For position-aware accounting changes, also run:

```bash
uv run --extra portfolios --extra dev ruff check src/msm_portfolios/accounting src/msm_portfolios/time_index/portfolios examples/msm_portfolios tests/msm_portfolios/accounting
uv run --extra portfolios --extra dev pytest tests/msm_portfolios/accounting/test_accounting.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_custom_cashflow_model_example.py
uv run --extra portfolios python examples/msm_portfolios/portfolio_perpetual_funding_example.py
```

For portfolio target-position changes, run:

```bash
uv run --extra dev ruff check src/msm/time_index/accounts src/msm/services/target_positions.py tests/msm/time_index/test_target_positions_contracts.py
uv run --extra dev pytest tests/msm/time_index/test_target_positions_contracts.py tests/msm_portfolios/models/test_model_graph.py
```
