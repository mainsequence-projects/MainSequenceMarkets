# Portfolios

The portfolios concept owns portfolio construction workflows. It connects
assets, signals, rebalance strategies, portfolio weights,
portfolio metadata, and portfolio value time series.

## Scope

Portfolios answer these questions:

- Which assets are eligible for a portfolio?
- Which valuation source provides the asset values used for returns?
- Which signals produce target weights?
- Which rebalance strategy converts signals into portfolio weights?
- Which DataNodes store canonical portfolio values, signal weights, and
  portfolio weights?
- Which metadata identifies portfolios, signals, and rebalance strategies?

## Primary Modules

- `msm_portfolios.configuration`: portfolio configuration models.
- `msm_portfolios.data_nodes`: canonical DataNodes for portfolios, portfolio
  weights, signal weights, storage initialization, and identity helpers.
- `msm_portfolios.rebalance_strategy`: rebalance strategy base classes and
  built-in strategies.
- `msm.models.portfolios`: core SQLAlchemy MetaTable declaration for portfolio
  identity/reference data.
- `msm_portfolios.models.portfolios`: SQLAlchemy MetaTable declarations for
  portfolio descriptive metadata.
- `msm_portfolios.models.rebalancing` and `msm_portfolios.models.signals`:
  SQLAlchemy MetaTable declarations for rebalance strategy metadata and signal
  metadata.
- `msm.api.portfolios`: typed row API for core `Portfolio` identity rows.
- `msm_portfolios.api.portfolios`: typed row API for `PortfolioMetadata`.
- `msm_portfolios.api.market_metadata`: typed row APIs for `SignalMetadata` and
  `RebalanceStrategyMetadata`.
- `msm.services.portfolios`: service helpers for portfolio identity rows.
- `msm_portfolios.contrib`: contributed price and signal DataNodes.
- `msm_portfolios.utils`: small shared logging and time constants only.
- `msm_portfolios.contrib.signals.regression_utils`: regression helpers used by
  contributed replicator-style signals.

## Key Contracts

Portfolio DataNodes use canonical time-indexed frames. Portfolio identity should
be deterministic: configuration hashes and signal/rebalance UIDs must be stable
for equivalent configuration payloads.

Canonical markets DataNodes derive their published identifiers from the same
rule as MetaTables: the default markets namespace keeps bare logical
identifiers, while a non-default `MSM_AUTO_REGISTER_NAMESPACE` prefixes them.
That namespace also becomes the default TimeIndexTableUpdater `hash_namespace`. Pass an
explicit namespace only for isolated tests or experiments.

Signal observation, rebalance decision, execution, valuation, and analytical
time are separate concepts. Every canonical timestamp must come from a signal,
persisted calendar event, execution bar, or valuation observation. Job time and
generic frequency strings are not economic clocks.

Use the typed row API for registry records:

```python
import msm

from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio

msm.start_engine(models=["Calendar", "CalendarDate", "CalendarSession", "Portfolio"])

calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)

portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_uid=calendar.uid,
)
```

`PortfolioCalendarEvents` publishes persisted `CalendarSession` opens or closes
at their actual UTC timestamps, including early closes and DST shifts.
`CalendarEventSignal` declares that published table as an observed dependency.
`ImmediateSignal` instead selects original signal observations and declares no
additional event source. Event selection and state transitions occur in the
strategy below `PortfolioRebalance`; neither `PortfolioWeights` nor
`PortfoliosDataNode` builds a rebalance index.

`calendar_identifier` and `calendar_events_instance` are required for
`CalendarEventSignal`. The event producer requires the canonical persisted
`Calendar.unique_identifier`; a `source_identifier` alias is rejected because
published rows carry a foreign key to that canonical value. Missing and failed
calendar lookups raise an error; neither the producer nor the strategy
substitutes a local pandas or synthetic calendar. Materialize the calendar
horizon before running the portfolio graph.

`Portfolio.upsert(...)` writes only the portfolio identity row. Portfolio
constituents, weights, values, and optional index publication are separate
portfolio workflows.

## General Rebalance Architecture

[ADR 0040](../../../ADR/0040-portfolio-temporal-ownership.md) records the
implemented general strategy boundary. `ImmediateSignal`,
`CalendarEventSignal`, `TimeWeighted`, `VolumeParticipation`, and
`LiquidityConstrained` are concrete strategies below that boundary; none of
them defines the architecture itself.

```text
SignalWeights target intent --------------------------+
                                                       |
strategy-declared observed inputs ---------------------+--> PortfolioRebalance
  calendar events, bars, volume, quotes, book depth,          generic stateful updater
  available liquidity, schedules, or fills                         |
                                                                   v
                                                     PortfolioRebalanceStateStorage
                                                     active intent, partial progress,
                                                     remaining target, provenance
                                                                   |
                                                                   v
                                                        PortfolioWeights
                                                        executed-weight projection
                                                                   |
                                                                   v
                                                        PortfolioWeightsStorage
                                                                   |
valuation observations --------------------------------------------+--> PortfoliosDataNode
                                                                        valuation only
                                                                            |
                                                                            v
                                                                     PortfoliosStorage
                                                                            |
                                                                            v
                                                                     PortfolioAnalytics
```

The portfolio composes the rebalance strategy and includes its serialized
policy and declared dependency identities in portfolio/update hashing. It does
not subclass the strategy and does not copy or generate strategy dates.

The strategy contract owns dependency declaration, input validation, target
cutoff and succession, source-event selection, partial state transitions, and
completion. The generic rebalance updater contains no branch for immediate,
calendar, time, volume, or liquidity strategies. A missing future bar, quote,
liquidity observation, or fill leaves the target unfinished; it never forces a
completion timestamp.

`PortfolioTable.calendar_uid` remains required portfolio reference metadata;
it does not implicitly schedule rebalances. Calendar-aware strategies declare
their published calendar-event input explicitly. Strategies driven by bars,
volume, quotes, order-book depth, available liquidity, schedules, or fills do
not gain calendar events merely because the portfolio has a reference
calendar.

`PortfolioRebalanceStateStorage` is a portfolio-level state ledger, not a
broker order/fill ledger. `PortfolioWeights` projects only state transitions
that actually changed executed weights, and `PortfoliosDataNode` continues to
value those weights at independent valuation-source observations. Missing
future bars or liquidity leave a target `pending` or `partial`; they do not
create a completion timestamp.

### Trailing daily-liquidity participation

`TrailingAverageDailyVolumeParticipation` separates capacity estimation from
execution pricing. It declares two independent asset-indexed sources:

```text
completed daily liquidity bars (daily VWAP, daily volume)
  -> trailing average daily notional
  -> per-asset session cap

observable intraday execution bars (execution price, bar volume)
  -> per-bar cap
  -> actual execution price and quantity
```

For each asset, completed historical daily notional is
`daily_vwap * daily_volume`. The strategy averages the most recent configured
number of completed observations that were available strictly before the
session execution window began. A current-session or future daily VWAP is
never eligible because VWAP is an ex-post statistic. Daily input timestamps
must therefore represent the right edge/availability time of completed bars.

At each intraday bar, executable notional is the minimum of the remaining
target notional, remaining per-session daily cap, and the configured fraction
of the current observed bar's notional. The stored `execution_price` is always
the configured field from the intraday execution source, such as `close`,
`mid_price`, or an arrival-price observation. It is never the historical daily
VWAP. Daily capacity consumed is persisted per asset in `strategy_state`, so a
restart or a same-session target supersession cannot reset the participation
limit.

The history read is bounded by `history_lookback_days`. Rolling daily capacity,
signal targets, and timestamp-to-observation groups are prepared once per run;
the transition loop does not rescan the full daily history for each intraday
bar. Apart from sorting unsorted source frames, preparation is linear in the
daily and intraday input rows, followed by the unavoidable emitted state
transitions.

Use
`examples/msm_portfolios/portfolio_trailing_adv_participation_preview.py` to
preview this state machine against registered daily-liquidity and intraday-bar
tables. The example filters both source reads to the requested assets, applies
the strategy-owned bounded history window, and prints quantities and cap
consumption without writing `PortfolioRebalanceStateStorage`. Production
portfolio workflows inject the same strategy into
`BacktestingWeightsConfig.rebalance_strategy_instance` and let
`PortfolioRebalance` persist the resulting transitions.

## Portfolio Read Services

Reusable portfolio output reads live under
`src/msm_portfolios/services/portfolio_reads.py` and are exported from
`msm_portfolios.services`:

```python
from msm_portfolios.services import latest_portfolio_weights, portfolio_values

weights = latest_portfolio_weights(
    ["btc-eth-target"],
    weights_date="2026-05-25T00:00:00Z",
    as_of=True,
    repository_context=runtime.context,
)
values = portfolio_values(
    ["btc-eth-target"],
    start="2026-05-01T00:00:00Z",
    end="2026-05-31T00:00:00Z",
    repository_context=runtime.context,
)
```

`latest_portfolio_weights(...)` reads `PortfolioWeightsStorage` by
`PortfolioTable.unique_identifier`, which is the storage-facing
`portfolio_identifier`. It keeps `PortfolioTable.uid` in the returned
`portfolio_uid` field so consumers can retain canonical row identity while
reading historical storage rows. Pass `as_of=True` for latest-at-or-before
snapshot selection or `as_of=False` for exact timestamp matching.

`portfolio_values(...)` reads canonical portfolio value rows from
`PortfoliosStorage` for one or more portfolio identifiers, with optional
`start`, `end`, `latest_only`, and `limit` filters. These helpers return
market-domain row dictionaries. Command Center tabular frames, dashboard
formatting, and valuation-position construction are separate consumer concerns.

Use an explicit `repository_context` for live platform reads. Tests and
downstream adapters may pass an `executor` callable when they need to inspect or
control execution without relying on hidden row-class active context. See
`examples/msm_portfolios/portfolio_read_services.py` for an offline example that
uses injected executors.

## Repair legacy midnight-indexed portfolio values

Portfolio values written by the former daily resampling path may carry a UTC
midnight `time_index` while `close_time` records the real exchange close. Do
not rewrite those indexed coordinates directly. Plan a portfolio-scoped tail
rollback against the persisted calendar first:

```bash
PYTHONPATH=src:. python \
  examples/msm_portfolios/portfolio_midnight_timestamp_repair.py \
  --portfolio-identifier <portfolio-identifier> \
  --start 2026-01-01T00:00:00Z \
  --end <latest-portfolio-value-timestamp>
```

The default is a read-only dry run. It checks `Portfolio.calendar_uid`,
persisted `CalendarSession.closes_at`, the historical `close_time`, destination
conflicts, and whether `--end` reaches the latest stored value. Any uncertainty
is a blocking issue. Review the JSON plan, then apply exactly one portfolio:

```bash
PYTHONPATH=src:. python \
  examples/msm_portfolios/portfolio_midnight_timestamp_repair.py \
  --portfolio-identifier <portfolio-identifier> \
  --start 2026-01-01T00:00:00Z \
  --end <latest-portfolio-value-timestamp> \
  --apply
```

Apply performs an inclusive `PortfoliosStorage` tail delete scoped by
`portfolio_identifier`; it does not finish the repair by itself. Pause any
scheduled writer before apply, and keep it paused while you immediately rerun
the portfolio workflow with the migrated configuration to replay that tail
from canonical valuation observations. The result compares the deleted count
with the dry-run count and exits nonzero if they differ. Run the dry plan again
after replay: it should contain no rollback. Process another portfolio only
after the previous portfolio has been replayed and verified.

## Portfolio Registry Tables

Portfolio registry tables are regular platform-managed MetaTables. They describe
portfolio identity and relationships; they do not store historical portfolio
values. Historical values, weights, and signal outputs live in time-index-table output
tables.

Portfolio identity is core reference data and lives under:

```text
src/msm/models/portfolios/
├── __init__.py
├── core.py       PortfolioTable
├── groups.py     PortfolioGroupTable, PortfolioGroupMembershipTable
└── signals.py    SignalMetadataTable
```

`PortfolioTable` is the canonical portfolio identity row. It is keyed by
`unique_identifier` and stores optional `published_index_uid` linkage to
`IndexTable`, an optional `signal_uid` linkage to `SignalMetadataTable`, plus
TimeIndexTableUpdater UIDs for canonical portfolio outputs. A portfolio is not an asset. The
optional published index link is metadata for workflows that want to expose the
portfolio as an index-like observable; core portfolio weights, values, account
expansion, and virtual-fund allocation use `PortfolioTable.uid` /
`PortfolioTable.unique_identifier`.

Portfolio groups are core reference data too. `PortfolioGroupTable` stores
group identity and `PortfolioGroupMembershipTable` stores the many-to-many
relationship between groups and portfolios. There is no `portfolio_group_uid`
column on `PortfolioTable`; a portfolio can belong to several groups without
duplicating or changing the portfolio identity row.

Portfolio descriptive metadata remains in `msm_portfolios`:

```text
src/msm_portfolios/models/portfolios/
├── __init__.py
└── metadata.py   PortfolioMetadataTable
```

`PortfolioMetadataTable` is descriptive metadata keyed by portfolio
`unique_identifier`. It is intentionally not a foreign-key extension of
`PortfolioTable`; it is human-facing metadata that can be managed without
changing the portfolio identity row.

Rebalance strategy calendar keys resolve persisted core `CalendarTable` rows
first. Durable portfolio records must use `PortfolioTable.calendar_uid`; this
field is required and cannot be null. Legacy pandas-market calendar keys remain
a fallback path only for runtime calendar resolution, not for persisted
portfolio identity.

## Table Relationships

Portfolio identity, required calendar linkage, and optional published-index linkage:

```text
+-----------------------------+        optional published index  +-----------------------------+
| PortfolioTable              |--------------------------------->| IndexTable                  |
|-----------------------------| published_index_uid             |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| unique_identifier unique    |                                  | unique_identifier unique    |
| calendar_uid FK NOT NULL ---+----+                             | index_type                  |
| portfolio_weights_data_node_uid |--> PortfolioWeights           +-----------------------------+
| signal_weights_data_node_uid    |--> SignalWeights
| signal_uid FK nullable ---------+----------------------------+
| portfolio_data_node_uid         |--> PortfoliosDataNode
| backtest_table_price_column_name|
+-----------------------------+
                                  |
                                  | required durable calendar relationship
                                  v
                         +-----------------------------+
                         | CalendarTable               |
                         |-----------------------------|
                         | uid PK                      |
                         | unique_identifier unique    |
                         | valid_from / valid_to       |
                         +-----------------------------+

                                  optional signal pointer
                                  v
                         +-----------------------------+
                         | SignalMetadataTable         |
                         |-----------------------------|
                         | uid PK                      |
                         | signal_uid unique           |
                         | signal_description          |
                         +-----------------------------+
```

Portfolio metadata is a separate descriptive table:

```text
+-----------------------------+              same logical key              +-----------------------------+
| PortfolioTable              |------------------------------------------->| PortfolioMetadataTable      |
|-----------------------------| unique_identifier by convention           |-----------------------------|
| uid PK                      |              no database FK                | uid PK                      |
| unique_identifier unique    |                                           | unique_identifier unique    |
| registry/config fields      |                                           | description                 |
+-----------------------------+                                           +-----------------------------+
```

Portfolio groups are many-to-many classification metadata:

```text
+-----------------------------+        1..*        +-----------------------------------+
| PortfolioGroupTable         |------------------->| PortfolioGroupMembershipTable     |
|-----------------------------|                    |-----------------------------------|
| uid PK                      |                    | uid PK                            |
| unique_identifier unique    |                    | portfolio_group_uid FK cascade    |
| display_name                |                    | portfolio_uid FK cascade          |
| description                 |                    | unique(group, portfolio)          |
+-----------------------------+                    +------------------+----------------+
                                                                   |
                                                                   | *..1
                                                                   v
                                                        +-----------------------------+
                                                        | PortfolioTable              |
                                                        |-----------------------------|
                                                        | uid PK                      |
                                                        | unique_identifier unique    |
                                                        | calendar_uid FK NOT NULL    |
                                                        +-----------------------------+
```

Deleting a portfolio group removes only membership rows through cascade.
Deleting a portfolio removes only its membership rows through cascade. Neither
operation deletes the other side of the relationship.

Portfolio time-index-table output is separate from registry MetaTables. These storage
classes are registered through the same catalog bootstrap, after their FK target
MetaTables:

```text
+-----------------------------+             writes             +--------------------------------------+
| PortfolioCalendarEvents     |------------------------------->| PortfolioCalendarEventsStorage       |
| PortfolioRebalance          |------------------------------->| PortfolioRebalanceStateStorage       |
| PortfolioWeights            |------------------------------->| PortfolioWeightsStorage              |
| SignalWeights               |------------------------------->| SignalWeightsStorage                 |
| PortfoliosDataNode          |------------------------------->| PortfoliosStorage                    |
| PortfolioAnalytics         |------------------------------->| PortfolioAnalyticsStorage           |
| External price DataNodes    |------------------------------->| ExternalPricesStorage                |
| InterpolatedPrices          |------------------------------->| configured InterpolatedPricesStorage |
+-----------------------------+                                +--------------------------------------+
          TimeIndexTableUpdater update logic                                  PlatformTimeIndexMetaTable

+-----------------------------+        required parent          +--------------------------------------+
| SignalMetadataTable         |<-------------------------------| SignalWeightsStorage                 |
|-----------------------------| signal_uid FK                  |--------------------------------------|
| uid PK                      |                                | time_index                           |
| signal_uid unique           |                                | signal_uid                           |
| signal_description          |                                | asset_identifier                     |
+-----------------------------+                                +--------------------------------------+
```

`SignalMetadataTable.signal_description` is descriptive text for humans. Store
plain text or Markdown, not HTML tags; rendering belongs to the consuming UI.
`PortfolioTable.signal_uid` is nullable because portfolio rows can be registered
before a signal workflow runs. Once `PortfoliosDataNode.run(...,
update_pointers=True)` completes, the portfolio row should store the same
`signal_uid` that identifies the signal metadata and signal-weight rows. API
reads for portfolio signal weights must use this pointer; they must not infer a
signal by scanning the shared `SignalWeightsStorage` table.

`PortfoliosStorage.portfolio_identifier`,
`PortfolioRebalanceStateStorage.portfolio_identifier`, and
`PortfolioWeightsStorage.portfolio_identifier` reference
`PortfolioTable.unique_identifier`; portfolio value and weight rows must be
written for a real portfolio identity. Rebalance state and portfolio weights
also reference `AssetTable.unique_identifier`, so neither can point to unknown
assets. `PortfolioCalendarEventsStorage.calendar_identifier` references
`CalendarTable.unique_identifier`. `PortfoliosDataNode` resolves the portfolio identifier
from the attached `PortfolioTable` row or from the explicit runtime identifier
before normalizing rows.

`PortfolioRebalanceStateStorage.time_index` is the strategy-selected observed
event timestamp, including partial or pending events.
`PortfolioWeightsStorage.time_index` is an execution timestamp copied from a
state transition that changed executed weight.
`PortfoliosStorage.time_index` is the valuation observation timestamp. They do
not need to be equal: weekly execution can feed daily valuation. Optional
`PortfolioAnalyticsStorage.time_index` is the actual source observation chosen
for an analytical period; `period_start` and `period_end` carry bucket
boundaries without relabelling the source event.

Portfolio construction depends on a real valuation source, but portfolio logic
does not own valuation ingestion. Example workflows publish normalized OHLCV
bars to `ExternalPricesStorage` only so the example is self-contained.
Production users can point portfolio configurations at any registered
compatible valuation storage table, including one produced by another library,
vendor connector, model valuation process, or project TimeIndexTableUpdater.

## Valuation Source Resolution

Portfolio valuation inputs are not stored on `PortfolioTable`. They are provided
by the portfolio build configuration and consumed through TimeIndexTableUpdater dependencies.

The current portfolio path keeps execution and valuation dependencies explicit:

```text
SignalWeights --------------------------+
strategy-declared observations ---------+--> PortfolioRebalance
  bars, volume, liquidity, fills, events       | writes/restarts from
                                              v
                                  PortfolioRebalanceStateStorage
                                              |
                                              v
                                      PortfolioWeights
                                              |
                                              v
ValuationSource --------------------> PortfoliosDataNode
  bars, fair value, NAV                    |
                                          v
                                  canonical portfolio values
```

`PortfolioBuildConfiguration.valuation_source_instance` receives the valuation
source that portfolio construction consumes. The valuation source may be an
`InterpolatedPrices` instance, another TimeIndexTableUpdater, or an `TimeIndexTableRef` pointing at
compatible registered storage. The valuation source must expose rows keyed by
`(time_index, asset_identifier)` and include the configured numeric
`valuation_column`, for example `close`, `fair_value`, `nav`, or `mark_price`.
Execution observations are strategy inputs, not portfolio valuation inputs.
`ImmediateSignal` requires no execution market-data dependency.
`TimeWeighted` declares price bars, `VolumeParticipation` declares price and
volume bars, `TrailingAverageDailyVolumeParticipation` declares completed daily
liquidity plus observable intraday execution bars, and `LiquidityConstrained`
declares price plus available liquidity. Each uses actual observations from
its declared source; historical daily VWAP is capacity input only.

This producer boundary is intentional. Price collection, valuation modeling,
normalization, vendor mapping, and connector-specific scheduling are separate
concerns from portfolio construction. Portfolio extensions should focus on
universe selection, signals, rebalancing, execution assumptions, and portfolio
output storage. They should consume a registered valuation storage contract
instead of importing or constructing the producer that wrote it.

If persistent interpolation is needed, `InterpolatedPrices` is built before the
portfolio and then passed into `PortfolioBuildConfiguration` like any other
dependency. `InterpolatedPricesConfig` accepts either `source_price_instance`
or `source_time_index_meta_table_uid`. Use `source_price_instance` when the
source price `TimeIndexTableUpdater` or `TimeIndexTableRef` is already part of the graph. Use
`source_time_index_meta_table_uid` when attaching an already registered
compatible source table through `TimeIndexTableRef.from_uid(...)`.
`InterpolatedPrices` validates the registered source cadence, exposes the
resolved source from `dependencies()`, and writes the configured interpolation
output.

Timestamp-valued bar payloads such as `open_time`, `first_trade_time`, and
`last_trade_time` remain timezone-aware datetimes throughout interpolation and
are normalized to `datetime64[ns, UTC]` before publication. They are never
round-tripped through unit-ambiguous integers. This matters with pandas 3,
where parsed datetimes commonly retain microsecond resolution and an integer
cast therefore represents microseconds rather than nanoseconds.

Upgrading the library does not rewrite previously published interpolated rows.
If inspection finds corrupt timestamp payloads, install the corrected package
first, determine the earliest affected observation per asset, apply an
inclusive `asset_identifier`-scoped tail delete through
`TimeIndexMetaTable.delete_after_date(...)`, and immediately replay the
interpolation updater and affected downstream graph. Do not update persisted
time coordinates in place.

The interpolation policy is storage identity, not row metadata.
`InterpolatedPrices` builds a configured storage class whose
`__metatable_extra_hash_components__` include the source `TimeIndexMetaTable`
UID, the source table cadence, `upsample_frequency_id`, and
`intraday_bar_interpolation_rule`; those components determine the configured
physical table identity. The rows keep the normal price-bar grain
`(time_index, asset_identifier)`. The policy values are not repeated on every
price row.

Configured interpolation storage is a dynamic schema artifact. It is derived
from a real registered source price storage table and a concrete interpolation
policy, so it is not part of the package-wide static `start_engine(...)` model
list. Prepare it before the normal portfolio run:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation step attaches the static schema, reads the registered
`ExternalPricesStorage` UID and cadence metadata, builds the
configured `InterpolatedPricesStorage` class, and uses the active migration
namespace from the SDK migration provider to find or generate the real dynamic
Alembic revision. It then runs the dynamic provider upgrade before any portfolio
TimeIndexTableUpdater writes, even when a stale `TimeIndexMetaTable` metadata row already
exists. Metadata alone is not considered schema preparation; the physical table
must be created by the migration flow. If an older registered
`ExternalPricesStorage` row is missing cadence metadata, the preparation script
patches that metadata to the model-declared cadence before deriving the dynamic
table. Runtime portfolio code then uses the registered table; it does not
create or migrate dynamic storage.

`PortfolioBuildConfiguration.valuation_column` chooses which numeric column from
the explicit valuation source drives portfolio returns. It is a string, not an
OHLC enum. Bar-based workflows can use `valuation_column="close"`, while model
or vendor workflows can use fields such as `fair_value`, `nav`, or
`settlement_price`. Portfolio valuation performs bounded per-asset as-of
selection under `ValuationAlignmentPolicy`; alignment targets only explicit
valuation observations and never creates a timestamp. Execution-side event
selection and capacity are owned by the configured rebalance strategy.

For a custom valuation source, register or migrate the source storage outside
portfolio core, then pass the registered `TimeIndexMetaTable` UID through
`TimeIndexTableRef.from_uid(...)`. The source table must keep its real
value column name; it should not be reshaped to `close` just to satisfy
portfolio core. See
`examples/msm_portfolios/portfolio_custom_valuation_column_example.py` for the
`fair_value` configuration path.
The portfolio update start is always the latest `PortfoliosStorage` timestamp
for the resolved `PortfolioTable.unique_identifier`, stored as
`PortfoliosStorage.portfolio_identifier`. It is not derived from signal progress,
valuation-source progress, or the table-wide maximum of the shared
`PortfoliosStorage` table.

After resolving that portfolio-scoped start, `PortfoliosDataNode` reads
canonical executed weights and actual valuation observations. It selects the
latest weights as-of each eligible observation, validates per-asset staleness,
and writes one canonical value row per eligible source timestamp. Before the
window, it retrieves all required per-asset seed observations in one set-based
request. Shared multidimensional sources use complete coordinates; for signal
weights that means both `signal_uid` and `asset_identifier`. A rerun before new
source data arrives is an empty update.

Strict valuation coverage is exposure-aware at each asset and timestamp. A
valuation is required when either the current or immediately preceding
executed weight is nonzero: the current weight protects entries, and the
preceding weight protects exits. A zero-to-zero asset is optional, and after a
completed exit it becomes optional on the following valuation timestamp. The
complete signal and executed-weight snapshots are not filtered, so explicit
zero rows remain available for state reconstruction and auditing.

In code, the important wiring is:

```python
source_bars_node = ExampleDailyBars(asset_identifiers=["asset-btc", "asset-eth"])
source_bars_node.run(update_tree=False)

price_source = InterpolatedPrices(
    interpolation_config=InterpolatedPricesConfig(
        asset_list=["asset-btc", "asset-eth"],
        intraday_bar_interpolation_rule="ffill",
        source_price_instance=source_bars_node,
        upsample_frequency_id="1d",
    )
)

signal_weights = FixedWeights.from_signal_configuration(...)
calendar_events = PortfolioCalendarEvents(
    config=PortfolioCalendarEventsConfiguration(
        calendar_identifier="CRYPTO_24_7",
        event_types=("market_close",),
    )
)

portfolio_configuration = PortfolioConfiguration(
    portfolio_build_configuration=PortfolioBuildConfiguration(
        valuation_source_instance=price_source,
        valuation_column="close",
        execution_configuration=PortfolioExecutionConfiguration(...),
        backtesting_weights_configuration=BacktestingWeightsConfig(
            signal_weights_instance=signal_weights,
            rebalance_strategy_instance=CalendarEventSignal(
                calendar_events_instance=calendar_events,
                calendar_identifier="CRYPTO_24_7",
                rebalance_event="market_close",
            ),
        ),
    ),
    portfolio_markets_configuration=PortfolioMarketsConfig(...),
)
```

For a user-owned fair-value source, the same portfolio configuration uses the
source UID directly and keeps the valuation column explicit:

```python
valuation_source = TimeIndexTableRef.from_uid(fair_value_table_uid)

portfolio_configuration = PortfolioConfiguration(
    portfolio_build_configuration=PortfolioBuildConfiguration(
        valuation_source_instance=valuation_source,
        valuation_column="fair_value",
        execution_configuration=PortfolioExecutionConfiguration(...),
        backtesting_weights_configuration=BacktestingWeightsConfig(...),
    ),
    portfolio_markets_configuration=PortfolioMarketsConfig(...),
)
```

`PortfolioRebalance.dependencies()` merges signal weights with arbitrary typed
sources declared by the strategy, validates those observations against the
strategy's required grain and fields, and persists the resulting state.
`PortfolioWeights.dependencies()` exposes only that rebalance-state updater.
`PortfoliosDataNode.dependencies()` continues to expose canonical
executed weights and its independent valuation source. Valuation sources may
contain extra assets; required holdings are aligned independently using the
latest observation at or before the target within `maximum_staleness`.

`portfolio_prices_frequency` and `PriceAlignmentPolicy` were removed. Use
`ValuationAlignmentPolicy` for source freshness and `PortfolioAnalytics` for
daily, weekly, monthly, or other reporting frequency conversion.

Existing portfolio output progress is scoped by `portfolio_identifier` because
`PortfoliosStorage` is keyed by `(time_index, portfolio_identifier)`. A later
row for another portfolio in the shared storage table must not move this
portfolio's start date; if this portfolio has no progress entry, the workflow
treats it as a fresh portfolio rather than using the table-wide maximum.

Signal output progress is scoped by `signal_uid` because `SignalWeightsStorage`
is keyed by `(time_index, signal_uid, asset_identifier)`. `signal_uid` is a
required reference to `SignalMetadataTable.signal_uid`, and `asset_identifier`
is a required reference to `AssetTable.unique_identifier`, so signal metadata
and assets must exist before signal-weight rows are published. Contributed
signal nodes must read progress under their own `signal_uid`; a later row from
another signal in the shared table must not shorten this signal's source-data
window.

## Account Target-Position Exposure To Portfolios

Account allocation registry rows remain core `msm` account concepts:
`AccountAllocationModelTable`, `AccountTargetAllocationTable`, and
`PositionSetTable`. The timestamped target exposure rows that can reference a
constructed portfolio are also core account allocation storage. They live in
`msm.data_nodes.accounts.storage.TargetPositionsStorage`; portfolio workflows may read or
expand them, but they do not own the table.

```text
+-----------------------------+       position_set_uid       +-----------------------------+
| PositionSetTable            |<-----------------------------| TargetPositionsStorage      |
| owner: msm                  |                              | owner: msm                  |
|-----------------------------|                              |-----------------------------|
| uid PK                      |                              | time_index                  |
| account_target_allocation_uid|                              | target_type                 |
| position_set_time UTC       |                              | target_uid                  |
+-----------------------------+                              | asset_uid nullable FK       |
                                                               | portfolio_uid nullable FK   |
                                                               | exposure columns            |
                                                               +-------------+---------------+
                                                                             |
                                                                             | portfolio_uid
                                                                             v
                                                               +-----------------------------+
                                                               | PortfolioTable              |
                                                               | owner: msm                  |
                                                               | uid PK                      |
                                                               | unique_identifier unique    |
                                                               +-----------------------------+
```

A target row has exactly one target:

```text
target_type = asset
  target_uid = asset_uid
  asset_uid -> AssetTable.uid

target_type = portfolio
  target_uid = portfolio_uid
  portfolio_uid -> PortfolioTable.uid
```

Portfolio target rows are mandate exposure, not custody holdings and not
portfolio indices. They are expanded into asset-level exposure only when a
downstream workflow explicitly calls the portfolio expansion service and
provides a resolver for current portfolio weights.

## Portfolio Construction And Account Virtual-Fund Allocation Boundary

Portfolio construction produces portfolio artifacts. It does not own
virtual-fund identity, and it does not write virtual-fund allocation rows.
Virtual funds are account-owned allocation views that target a portfolio after
that portfolio exists. Their canonical docs live in core
[`msm` account virtual funds](../../msm/accounts/virtual_funds.md).

```text
Portfolio construction produces portfolio artifacts.
It does not own virtual-fund identity and it does not connect directly to
virtual-fund allocation rows.

+---------------------+      +-----------------------------+
| SignalWeights       |----->| PortfolioRebalance          |<----- strategy-declared
+---------------------+      | generic strategy runner     |      observed sources
                             +--------------+--------------+
                                            |
                                            v
                             +-----------------------------+
                             | RebalanceStateStorage       |
                             +--------------+--------------+
                                            |
                                            v
                             +-----------------------------+
                             | PortfolioWeights projection |
                             +--------------+--------------+
                                            |
                                            v
+---------------------+      +-----------------------------+
| ValuationSource     |----->| PortfoliosDataNode          |
+---------------------+      | valuation only              |
                             +--------------+--------------+
                                            |
                                            v
        +---------------------------------------------------------+
        | PortfolioTable                                          |
        | - portfolio identity                                    |
        | - signal_weights_data_node_uid                          |
        | - portfolio_weights_data_node_uid                       |
        | - portfolio_data_node_uid                               |
        | - optional published_index_uid -> IndexTable.uid        |
        +---------------------------------------------------------+
```

`PortfoliosDataNode.run(..., update_pointers=True)` updates the
`PortfolioTable` TimeIndexTableUpdater pointer fields after the portfolio graph has
published. This is enabled by default for portfolio-configuration runs, so
examples and callers do not need to manually re-upsert the portfolio row after
execution. Pass `update_pointers=False` only when deliberately running the graph
without updating portfolio registry links.

When a run publishes no new executed weights, the workflow must not require a
fresh `PortfolioWeights` TimeIndexTableUpdate. It preserves the existing
`PortfolioTable.portfolio_weights_data_node_uid` and still updates the signal
and portfolio-values pointers from the DataNodeUpdates produced by the current
graph run.

Virtual-fund allocation is a separate relationship over account holdings and a
target portfolio:

```text
+---------------------+        target_portfolio_uid        +---------------------+
| PortfolioTable      |<-----------------------------------| VirtualFundTable    |
| portfolio identity  |                                    | allocation identity |
+---------------------+                                    | account_uid         |
                                                           +----------+----------+
                                                                      |
                                                                      | account_uid
                                                                      v
+---------------------+        account_uid                +---------------------+
| AccountTable        |<-----------------------------------| AccountHoldingsSet |
| custody account     |                                    | source snapshot    |
+---------------------+                                    +----------+----------+
                                                                      |
                                                                      | source_account_holdings_set_uid
                                                                      v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsSetTable |
                                                           | allocation set identity     |
                                                           +-------------+---------------+
                                                                         |
                                                                         v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsStorage  |
                                                           | allocated_quantity          |
                                                           | direction                   |
                                                           | asset_identifier -> Asset   |
                                                           +-----------------------------+
```

The boundary is intentional:

- `PortfolioTable` identifies the portfolio and points at portfolio output
  storage.
- `VirtualFundTable` is core `msm` account-allocation state that binds an
  account to a target portfolio.
- `AccountHoldingsSetTable` is the source account snapshot.
- `VirtualFundHoldingsSetTable` records one allocation view from one source
  holdings set.
- `VirtualFundHoldingsStorage` stores allocated exposure rows, not custody.

Virtual funds are not assets. They should not appear as synthetic rows in
`AccountHoldingsStorage`; account-level virtual-fund exposure is reconstructed
from `VirtualFundTable`, `VirtualFundHoldingsSetTable`, and
`VirtualFundHoldingsStorage`.

Storage dimensions use explicit names instead of reusing bare
`unique_identifier`: `asset_identifier` for asset-keyed rows,
`portfolio_identifier` for rebalance state, portfolio value rows, and portfolio
weight rows. The `portfolio_identifier` value is
`PortfolioTable.unique_identifier` and is enforced by storage foreign keys.
Rebalance state and portfolio weights also enforce `asset_identifier` against
`AssetTable.unique_identifier`. Portfolio identity does not require a linked
`IndexTable` row.

See `examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` for the
schema-preparation stage and
`examples/msm_portfolios/portfolio_equal_weights_run.py` for the normal
portfolio run. The reusable implementation lives in
`examples/msm_portfolios/portfolio_equal_weights_example.py`; it reuses the
shared crypto `Asset` example rows, creates or reuses a `CRYPTO_24_7` calendar
from `pandas_market_calendars`, publishes example OHLCV bars to
`ExternalPricesStorage`, interpolates those prices, runs
`PortfolioCalendarEvents`, `SignalWeights`, `PortfolioRebalance`,
`PortfolioWeights`, and `PortfoliosDataNode`, and upserts the
`Portfolio` row with `calendar_uid` plus the published TimeIndexTableUpdater update UIDs.
The example narrates each setup, source-price
publication, and portfolio step so terminal output explains what was created.
It does not create virtual funds or virtual-fund allocation rows; those require
an explicit account funding policy and belong in the core account
virtual-funds workflow.

## Extension Notes

Add new portfolio construction configuration in `msm_portfolios.configuration`.
Add reusable DataNodes under `msm_portfolios.data_nodes` or
`msm_portfolios.contrib`. Add rebalance logic under
`msm_portfolios.rebalance_strategy`. Add portfolio identity persistence through
core `msm.models`, `msm.repositories`, `msm.services`, and `msm.api`. Add
portfolio metadata persistence through `msm_portfolios.models` and
`msm_portfolios.api`.

## Related Concepts

- [Assets](../../msm/assets/index.md)
- [Virtual Funds](../../msm/accounts/virtual_funds.md)
- [Execution](../../msm/execution/index.md)
- [Pricing](../../msm_pricing/index.md)
