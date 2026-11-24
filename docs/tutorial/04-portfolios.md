# Portfolios

Construct an equal-weights portfolio end to end. The workflow runs in two
stages: a migration of the example's own interpolated-price table, then a run step
that publishes prices, computes weights, and publishes
the portfolio's signal weights, weights and values to Markets. It reuses the calendar from
[Calendars](02-calendars.md) as `Portfolio.calendar_uid`.

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Two-stage equal-weights workflow

With Markets' own migrations applied, run the two stages from the repository root:

```bash
metatables --local migrations upgrade --provider examples.msm_portfolios.portfolio_equal_weights_migrations:migration head
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

Both write only to the [local runtime](../concepts.md#namespaces-and-sandboxes). The
first stage applies a committed revision of the example's own provider. It creates one
table, the same in every database, and changes none of Markets'.

The example's source bars close daily from 2026-05-23. Its `FixedWeights` signal states
its weights once, at `signal_time_index` (`SIGNAL_TIME_INDEX`, 2026-05-23 12:00 UTC): after
the first close, because a rebalance sizes its shares with the last prices before its
earliest moment. The rebalance fills them at the next close, and the first run publishes
the signal, the portfolio's weights and its values. A second run writes nothing new.
`--no-run-updaters` builds the frames without publishing them.

Every asset the portfolio prices must be linked to a stored calendar with
`AssetCalendar` before interpolation runs. The run script creates the `CRYPTO_24_7`
calendar first, then registers the asset types and the assets with one `upsert_many`
each. Each crypto asset's payload names the calendar, so the upsert links it. An asset
with no link fails the price update, and the error names it; see
[An asset that gets price bars needs a trading calendar](01-assets.md#an-asset-that-gets-price-bars-needs-a-trading-calendar).

The example is a producer. It declares the interpolated-price table on its own base,
in its own namespace, in `portfolio_equal_weights_config.py`, keyed by its configuration:
the source's table name and cadence, the upsample frequency and the interpolation rule.
Change one of them and the table is a new one, with a new revision to commit:
autogenerate it with `metatables migrations revision` once the provider's earlier
revisions are applied. The run script publishes example OHLCV source bars to
`ExternalPricesStorage`, interpolates prices, runs `SignalWeights`,
`PortfolioCalendarEvents`, `PortfolioRebalance`, the portfolio's ledger
(`PortfolioEngine`), `PortfolioWeights` and `PortfolioValues`, creates or reuses the
crypto `CRYPTO_24_7` calendar, and stores the calendar and signal on the
`Portfolio` row. `SignalWeights`, `PortfolioWeights` and `PortfolioValues`
publish their rows through the series operations
([Published Series](../knowledge/msm_portfolios/portfolios/index.md#published-series)).
The price configuration holds the source bars updater, and `InterpolatedPrices`
receives the example's table as `output_table=`. The portfolio configuration receives that
`InterpolatedPrices` node as `valuation_source_instance` and sets
`valuation_column="close"`: the ledger values the portfolio at those closes, and
nothing creates interpolation storage internally. Real portfolio extensions can pass any compatible
asset-indexed valuation TimeIndexTableUpdater or TimeIndexTableRef and choose any numeric valuation
column, such as `fair_value` or `nav`, without reshaping the source into OHLC
bars. A focused configuration example is available at
`examples/msm_portfolios/portfolio_custom_valuation_column_example.py`:

```bash
python examples/msm_portfolios/portfolio_custom_valuation_column_example.py \
  --source-time-index-meta-table-uid <fair-value-time-index-meta-table-uid> \
  --calendar-events-time-index-meta-table-uid <calendar-events-time-index-meta-table-uid>
```

Its `CalendarEventSignal` reads the market opens and closes from the second table,
which `PortfolioCalendarEvents` publishes.

`InterpolatedPrices` reads the registered source table's name and cadence, computes
the key of its configuration, and refuses a table with another key or cadence, so
different sources, source cadences, upsample frequencies and interpolation rules do
not collide inside one price table. The script prints the workflow steps, created row UIDs, source valuation
row counts, explicit valuation-source dependency details, and published TimeIndexTableUpdater
storage UIDs.

Source-bar timestamp payloads are kept as timezone-aware datetimes and
normalized to nanosecond UTC before `InterpolatedPrices` publishes them. When
repairing rows written by an affected older runtime, upgrade `ms-markets`
before applying any `asset_identifier`-scoped tail delete, then replay the
interpolation updater and downstream portfolio graph immediately.

Asset-scope mappings use `asset_identifier` as their canonical identity key, and a
`calendar` key is refused; the example's scope holds identifiers only. Mapping payloads
containing
`unique_identifier` are rejected, even when `asset_identifier` is also present.

## Understand the independent clocks

The example intentionally keeps execution, valuation, and reporting separate:

```text
FixedWeights signal
  + PortfolioCalendarEvents publishes persisted CRYPTO_24_7 session events
  -> CalendarEventSignal selects market_close observations
  -> PortfolioRebalance persists complete or unfinished strategy state
  -> PortfolioEngine books the fills and values the holdings at valuation-source observations
  -> PortfolioWeights and PortfolioValues publish the ledger's weights and values
  -> optional PortfolioAnalytics samples canonical values for reporting
```

The ledger never creates a calendar or frequency-based index. A
weekly `CalendarEventSignal` can therefore produce sparse weight rows while a
daily valuation source produces daily portfolio values. `ImmediateSignal`
rebalances at every new signal.

A signal can arrive at any hour; it is not a trade. Prices are stamped at the
moment they were observed (the end of a bar), and a trade happens only at an
observed price ([ADR 0058](../ADR/0058-trade-at-the-next-observed-price.md)). The earliest moment a target may trade is its signal's
time (for `CalendarEventSignal`, the selected open or close) while the
portfolio's calendar is in session, otherwise the next session start. Each asset
then trades at the first row of the valuation source at or after that moment,
strictly after the signal and inside a session (`market_open < time_index <=
market_close`). Interpolated rows never count, the fill column must be a close or
a mark, assets fill independently, and a missing price makes the trade wait. On
`CRYPTO_24_7` every moment is in session.

Those are facts. How the trade is sized and paid for is the strategy's
`execution_policy` (`ExecutionPolicy`), whose defaults are the owner's decisions:
shares fixed at the decision, no negative cash, sells before buys, buys short of
cash at one instant filling the same fraction, and a buy cash cannot cover
filling what it can, waiting for the rebalance's pending sells, then cut with the
rest cancelled (`insufficient_cash`).

The build configuration names the portfolio's currency
(`valuation_asset_identifier`). A portfolio holding an asset quoted in another
currency declares one `fx_source_instance`, and its valuation source names each
price's currency in `price_asset_identifier`; prices convert at the last observed
rate. Every portfolio keeps a ledger
([ADR 0065](../ADR/0065-every-portfolio-keeps-a-ledger.md)): the example's starts
with 1,000,000 USD in cash (`initial_nav`) on 2026-05-22 and pays 0.018% of each
trade's notional (`ProportionalExecutionCostModel`). The ledger values the
portfolio from its positions at their prices, so its weights drift with prices
between rebalances ([ADR 0059](../ADR/0059-portfolio-currency-fx-and-drifting-weights.md)).
The prices are adjusted unless the valuation source states otherwise
(`events_in_price`), so the example needs no dividend or split model.

Both strategies require an explicit persisted calendar identifier and an
explicit calendar-event updater or table reference that publishes `market_open`
and `market_close`, and the calendar must be the portfolio's `calendar_uid`.
Neither reads a calendar behind the dependency graph or falls back to a
process-local calendar.
Create the calendar with its session rules and exceptions before executing the
graph; see [Calendars](02-calendars.md).

Each execution window is seeded with the latest eligible row for every required
asset using one set-based `get_last_observation(...)` request. For shared signal
storage, each range coordinate includes both `signal_uid` and `asset_identifier`,
preventing another signal's rows from entering the seed.

This example uses one concrete strategy; it does not define the architecture.
Under [ADR 0040](../ADR/0040-portfolio-temporal-ownership.md), every strategy
declares the observations it needs and implements the same state transition
contract. `TimeWeighted` consumes observed price bars,
`VolumeParticipation` consumes price and volume bars, and
`TrailingAverageDailyVolumeParticipation` uses completed historical daily
VWAP-times-volume only to estimate a daily notional cap while executing at an
observable intraday price, and
`LiquidityConstrained` consumes price plus available-liquidity observations.
Each sizes its order once, at the decision, as `ImmediateSignal` does, and fills
it in slices, one per bar, under the same `execution_policy`; missing capacity
leaves the order open until a later bar
([#90](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/90)).
The book's unit is the ledger's `initial_nav`: it turns a bar's volume or
liquidity into shares of the order. Adding a strategy does not add a branch or
date generator to `PortfolioRebalance`, `PortfolioEngine`, `PortfolioWeights` or
`PortfolioValues`.

For a bounded five-percent trailing daily participation policy:

```python
from metatables import TimeIndexTableRef
from msm_portfolios.rebalance_strategy import (
    TrailingAverageDailyVolumeParticipation,
)

strategy = TrailingAverageDailyVolumeParticipation(
    daily_liquidity_instance=TimeIndexTableRef.from_uid(daily_table_uid),
    execution_bars_instance=TimeIndexTableRef.from_uid(intraday_table_uid),
    daily_vwap_column="vwap",
    daily_volume_column="volume",
    execution_price_column="close",
    execution_volume_column="volume",
    lookback_observations=20,
    history_lookback_days=60,
    session_timezone="America/New_York",
    execution_start="09:30",
    execution_end="16:00",
    max_daily_participation=0.05,
    max_bar_participation=0.10,
)
```

Inject `strategy` as `BacktestingWeightsConfig.rebalance_strategy_instance`.
The daily source must timestamp each row when the completed bar is available;
the intraday source supplies the actual price used by the execution
assumption. See
`examples/msm_portfolios/portfolio_trailing_adv_participation_example.py` for
the focused configuration helper. To preview real transitions against two
registered source tables without persisting portfolio state, run:

```bash
python examples/msm_portfolios/portfolio_trailing_adv_participation_preview.py \
  --daily-liquidity-table-uid <daily-table-uid> \
  --execution-bars-table-uid <intraday-table-uid> \
  --signal-time 2026-01-05T14:25:00Z \
  --start 2026-01-05T14:30:00Z \
  --end 2026-01-05T21:00:00Z \
  --target BTC-USD=0.60 \
  --target ETH-USD=0.40
```

The preview filters both reads to the requested target assets, expands only
the strategy's bounded daily-history window, and prints execution price,
quantity, remaining target weight, trailing capacity, and consumed daily cap.
Use the full `PortfolioRebalance` graph when those transitions should be
persisted and projected into canonical portfolio weights.

## Migrate values produced by the former daily resampler

If an existing portfolio has midnight-indexed values from the former combined
portfolio path, run `examples/msm_portfolios/portfolio_midnight_timestamp_repair.py`
without `--apply` first. Set `--end` at or after the latest stored portfolio
value; the plan refuses to delete a tail it has not fully inspected and
validates every candidate against the portfolio's persisted calendar and
historical `close_time`. After reviewing the plan, run it with `--apply` for one
portfolio while scheduled writers are paused, then immediately rerun the
portfolio workflow to rebuild the scoped tail. A post-replay dry run must
report no rollback.

The ledger's valuation model bounds per-asset as-of freshness: a held asset is
valued at its last observed price, marked stale past `maximum_staleness`, and
`fail_on_missing_values` refuses a stale one instead. The portfolio has no
reporting frequency; configure a separate `PortfolioAnalytics` node when a chart
or analysis needs daily, weekly, or monthly sampling. Analytical rows keep the actual selected source
observation in both `time_index` and `source_time_index`, with bucket boundaries
in `period_start` and `period_end`.

## Preview position cash flows and FX valuation

The full configuration, input-grain, ledger, restart, and extension contracts
are documented in
[Position-Aware Portfolio Accounting](../knowledge/msm_portfolios/portfolios/accounting.md).

Every portfolio writes a canonical event ledger, the equal-weights example's too.
Start with the offline fixture to see what a ledger books:

```bash
uv run --extra portfolios python \
  examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
```

The fixture starts with USD cash, buys ten shares quoted in EUR, recognizes a
EUR 1-per-share dividend, sells the shares, and then settles the retained EUR
receivable. Explicit EUR/USD observations value every component in USD. Inspect
the event-level summary rows: entitlement recognizes income once; the later
cash receipt has zero recognized P&L because it only exchanges receivable state
for settled cash.

The ledger books exactly the fills `PortfolioRebalance` recorded, each at its
time and observed price. A rebalance fixes every asset's share count once, at its
decision: target weight x NAV / price, with the NAV and the prices last observed
before its earliest moment. Each asset then fills that count at its own price; a
fill that trades part of its order trades that part of the ledger's. The ledger
builds no schedule of its own and looks up no mark for a fill. A held
asset is always valued at its last observed price, however old; past
`maximum_staleness` it is marked stale, never refused.

The same example also normalizes an exact retry and rejects a duplicated
economic record moved to another timestamp. Keep economic identity stable;
changing time alone is not a new event. Hosted publication compares the complete
event revision with existing digests before adding a ledger tail. Apply provider
head (including `0019`) through the local migration command or the hosted
deployment Job before attaching these tables; never bypass validation with raw
SQL ledger writes.

To see the user-extension boundary, run:

```bash
uv run --extra portfolios python \
  examples/msm_portfolios/portfolio_custom_cashflow_model_example.py
```

That example defines a module-level `PositionCashFlowModel` subclass and emits
two royalty events in one vectorized calculation partition. Production models
must inject every source as a declared `TimeIndexTableUpdater` or
`TimeIndexTableRef`; the in-memory example passes frames directly so it remains
deterministic and safe to run without platform writes.

To verify derivative settlement and same-time event ordering, run:

```bash
uv run --extra portfolios python \
  examples/msm_portfolios/portfolio_perpetual_funding_example.py
```

This fixture configures `TargetWeightExecutionModel` on the existing
`ImmediateSignal` rebalance strategy on the `CRYPTO_24_7` calendar: each signal
trades at the first mark observed after it. Explicit instrument terms declare
notional-weight sizing, contract units and rounding, USD quote currency, and
variation-margin settlement. The strategy opens ten contracts without deducting
their full notional from cash and applies commission once. A funding lifecycle
model then reduces NAV; the next signal is sized from the NAV after it, so the
position is reduced to eight contracts; a later funding event changes cash and
NAV without a rebalance. Portfolios never accept broker executions or
Account holdings; all execution facts in this path are internal deterministic
simulation output.

**Next →** [Pricing Instruments](05-pricing.md)
