# Portfolios

Construct an equal-weights portfolio end to end. The workflow runs in two
stages: a schema-preparation step that provisions the interpolated price
storage, then a run step that publishes prices, computes weights, and stores the
portfolio TimeIndexTableUpdater results. It reuses the calendar from
[Calendars](02-calendars.md) as `Portfolio.calendar_uid`.

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Two-stage equal-weights workflow

Run the portfolio workflow in two stages:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation script derives the configured interpolated price storage from
the registered `ExternalPricesStorage` table and the example interpolation
policy, finds or generates the real dynamic Alembic revision under the active
migration namespace, and runs the dynamic provider upgrade before portfolio
DataNodes write. If an older registered `ExternalPricesStorage` table is missing
cadence metadata, the preparation step repairs that source metadata before
deriving the dynamic interpolation table. The run script creates the
optional portfolio `Index`, publishes example OHLCV source bars to
`ExternalPricesStorage`, interpolates prices, runs `SignalWeights`,
`PortfolioCalendarEvents`, `PortfolioRebalance`, `PortfolioWeights`, and
`PortfoliosDataNode`, creates or reuses the crypto
`CRYPTO_24_7` calendar, and stores the calendar, index, and TimeIndexTableUpdater UIDs on the
`Portfolio` row. The price configuration stores the
`ExternalPricesStorage` TimeIndexMetaTable UID on `InterpolatedPricesConfig`, so
the explicit upstream interpolation node can recover the price source through
the SDK TimeIndexTableRef lookup path. The portfolio configuration receives that
`InterpolatedPrices` node as `valuation_source_instance` and sets
`valuation_column="close"`; `PortfoliosDataNode` does not create interpolation
storage internally. Real portfolio extensions can pass any compatible
asset-indexed valuation TimeIndexTableUpdater or TimeIndexTableRef and choose any numeric valuation
column, such as `fair_value` or `nav`, without reshaping the source into OHLC
bars. A focused configuration example is available at
`examples/msm_portfolios/portfolio_custom_valuation_column_example.py`:

```bash
python examples/msm_portfolios/portfolio_custom_valuation_column_example.py \
  --source-time-index-meta-table-uid <fair-value-time-index-meta-table-uid>
```

The source bar frequency is read from the registered source table's cadence
metadata, then used with `__metatable_extra_hash_components__` to select a
configured output storage table, so different source cadence, upsample
frequency, and interpolation rule combinations do not collide inside one price
table. The script prints the workflow steps, created row UIDs, source valuation
row counts, explicit valuation-source dependency details, and published TimeIndexTableUpdater
storage UIDs.

Source-bar timestamp payloads are kept as timezone-aware datetimes and
normalized to nanosecond UTC before `InterpolatedPrices` publishes them. When
repairing rows written by an affected older runtime, upgrade `ms-markets`
before applying any `asset_identifier`-scoped tail delete, then replay the
interpolation updater and downstream portfolio graph immediately.

## Understand the independent clocks

The example intentionally keeps execution, valuation, and reporting separate:

```text
FixedWeights signal
  + PortfolioCalendarEvents publishes persisted CRYPTO_24_7 session events
  -> CalendarEventSignal selects market_close observations
  -> PortfolioRebalance persists complete or unfinished strategy state
  -> PortfolioWeights projects only executed-weight changes
  -> PortfoliosDataNode values current holdings at valuation-source observations
  -> optional PortfolioAnalytics samples canonical values for reporting
```

`PortfoliosDataNode` never creates a calendar or frequency-based index. A
weekly `CalendarEventSignal` can therefore produce sparse weight rows while a
daily valuation source produces daily portfolio values. `ImmediateSignal` is
reserved for true execution at a signal's original observation timestamp.
`CalendarEventSignal` requires an explicit persisted calendar identifier and
an explicit calendar-event updater or table reference. It does not read a
calendar behind the dependency graph or fall back to a process-local calendar.
Ensure the required `CalendarSession` horizon exists before executing the
graph.

Each execution or valuation window is seeded with the latest eligible row for
every required asset using one set-based `get_last_observation(...)` request.
For shared signal storage, each range coordinate includes both `signal_uid` and
`asset_identifier`, preventing another signal's rows from entering the seed.

This example uses one concrete strategy; it does not define the architecture.
Under [ADR 0040](../ADR/0040-portfolio-temporal-ownership.md), every strategy
declares the observations it needs and implements the same state transition
contract. `TimeWeighted` consumes observed price bars,
`VolumeParticipation` consumes price and volume bars, and
`TrailingAverageDailyVolumeParticipation` uses completed historical daily
VWAP-times-volume only to estimate a daily notional cap while executing at an
observable intraday price, and
`LiquidityConstrained` consumes price plus available-liquidity observations.
Missing capacity leaves persisted work pending or partial. Adding a strategy
does not add a branch or date generator to `PortfolioRebalance`,
`PortfolioWeights`, or `PortfoliosDataNode`.

For a bounded five-percent trailing daily participation policy:

```python
from mainsequence.meta_tables import TimeIndexTableRef
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
    total_notional=50_000_000,
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

The core configuration uses `valuation_alignment_policy` to bound per-asset
as-of freshness. In strict mode, freshness is required when the current or
immediately preceding executed weight is nonzero. This keeps entry and exit
prices mandatory without making an unchanged zero-weight row economically
required or removing that row from the stored signal. It does not accept
`portfolio_prices_frequency`; configure a
separate `PortfolioAnalytics` node when a chart or analysis needs daily,
weekly, or monthly sampling. Analytical rows keep the actual selected source
observation in both `time_index` and `source_time_index`, with bucket boundaries
in `period_start` and `period_end`.

**Next →** [Pricing Instruments](05-pricing.md)
