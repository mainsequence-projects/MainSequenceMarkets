# 0040. Portfolio Temporal Ownership And General Rebalance Execution

## Status

Accepted — implemented

The execution/valuation/analytics separation was implemented in version 1.0.6.
The general rebalance-strategy amendment dated 2026-09-07 is implemented in
the Unreleased line. `ImmediateSignal`, `CalendarEventSignal`, `TimeWeighted`,
`VolumeParticipation`, and `LiquidityConstrained` now share one declared-input,
stateful execution contract.

This ADR amends:

- [ADR 0030](0030-explicit-portfolio-price-source-dependency.md), by
  superseding the decision that `PortfoliosDataNode` owns rebalance-index
  generation, executed-weight production, and local alignment to one portfolio
  grid;
- [ADR 0031](0031-generic-portfolio-valuation-source.md), by preserving the
  generic valuation-source contract while separating execution from portfolio
  valuation.

It provides the architectural direction for
[GitHub issue #4](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/4).
At initial adoption,
[issue #2](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/2)
and [issue #3](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/3)
were separate implementation defects. Version 1.0.6 subsequently fixed those
defects together with the temporal-separation baseline; the general strategy
amendment does not reopen them.

## Context

Portfolio workflows contain several different kinds of time:

```text
signal observation time
  when investment intent becomes observable

rebalance decision time
  when a strategy selects target weights

execution time
  when portfolio weights actually change

valuation time
  when the held portfolio is valued

analysis time
  when a consumer groups or samples canonical values

job execution time
  when computation happens operationally
```

These times may coincide for a simple daily close strategy, but they do not
have the same meaning. A weekly-rebalanced portfolio may publish daily values.
A signal observed after a market close may be eligible only at the next
session. A volume-participation strategy may execute across many intraday bars.
An analytics consumer may request month-end observations without changing any
economic event.

The pre-1.0.6 implementation collapsed these distinctions into a synthetic
portfolio index:

```text
PortfoliosDataNode
  -> derives start and end from portfolio output progress and current time
  -> creates new_index from portfolio_prices_frequency
       daily: persisted calendar market_close timestamps
       intraday: pd.date_range(...)
  -> forward-fills signal observations onto new_index
  -> forward-fills valuation observations onto new_index
  -> passes already aligned frames to the rebalance strategy
  -> calculates executed weights and portfolio values on that index
  -> resamples the result again to portfolio_prices_frequency
```

This makes `portfolio_prices_frequency` simultaneously act as a rebalance
cadence, valuation cadence, and reporting cadence. It also reverses the stated
configuration contract: `BacktestingWeightsConfig` says that the rebalance
strategy controls how and when weights become executed weights, but the
portfolio node selects timestamps before invoking the strategy.

The inconsistency was visible in the pre-1.0.6 strategies:

- `RebalanceStrategyBase.calculate_rebalance_dates(..., "daily")` selects
  `market_open`;
- the active daily portfolio path independently selects `market_close`;
- `ImmediateSignal` receives signal weights already interpolated to those
  closes, so it is not immediate at the original signal timestamp;
- `TimeWeighted` and `VolumeParticipation` raise `NotImplementedError` before
  their remaining execution code.

Finally, daily resampling can replace a real market-close timestamp with a
midnight bucket label. That violates the Main Sequence rule that `time_index`
is the observation point represented by the row, not a generic date label.

Version 1.0.6 corrected that temporal ownership for immediate and persisted
calendar-event execution. It did not, however, establish a general execution
strategy contract. Its `PortfolioWeights` path still:

- declares exactly two dependencies: signal weights and one execution
  valuation source;
- asks the strategy for timestamps before loading strategy-specific market
  inputs;
- branches on `timing_mode` in the updater;
- aligns one configured value column plus an optional column named `volume`;
- passes those fixed frames to `apply_rebalance_logic(...)`; and
- persists only the last executed weights, with no explicit active intent,
  remaining target, or partial-execution status.

That interface can represent immediate and calendar-triggered full rebalances.
It cannot truthfully represent a strategy driven by observed bars, elapsed
execution windows, traded volume, quotes, order-book depth, available
liquidity, or external fills. The unfinished `TimeWeighted` and
`VolumeParticipation` classes correctly remain outside the public strategy
surface, but excluding them does not make the current abstraction general.

## Problem

The pre-1.0.6 design had no single truthful owner for economic timestamps.

It causes the following contract failures:

1. A portfolio calculator manufactures timestamps that did not come from a
   signal, execution event, calendar event, or valuation observation.
2. A rebalance strategy cannot fully express its timing semantics because its
   inputs have already been resampled.
3. Forward-fill silently decides signal cutoff, stale-price, holiday, and
   missing-observation behavior.
4. Executed weights and portfolio values are forced onto one timeline even
   when their natural cadences differ.
5. Reporting transformations can overwrite economic timestamps in canonical
   storage.
6. Incomplete strategies appear to participate in a complete portfolio
   workflow even though their execution contracts are not implemented.
7. A rerun can reconstruct an already processed event with a differently
   labelled timestamp instead of returning a deterministic no-op.

The solution is not to add more date-generation logic to
`PortfoliosDataNode`. Date generation is valid only in a component whose
declared product is an event schedule or analytical series.

The 2026-09-07 amendment addresses a second problem: moving date selection
from `PortfoliosDataNode` into a method named `execution_timestamps(...)` is not
enough. A general rebalance strategy must own its input contract, target
activation, event selection, partial transitions, and unfinished state. The
portfolio updater must not know that a particular strategy uses a calendar,
bar volume, quote size, order-book depth, or time slices.

## Decision

Separate portfolio target intent, rebalance execution state, executed-weight
projection, portfolio valuation, and portfolio analytics into distinct owners.

The amended target graph is:

```text
SignalWeights (target intent) -------------------------+
                                                        |
strategy-declared observed dependencies ----------------+--> PortfolioRebalance
  persisted calendar events                                  generic stateful updater
  execution bars / observed volume                                  |
  quotes / order book / available liquidity                         |
  externally published schedule or fills                            v
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
ValuationSource -----------------------------------------------------+--> PortfoliosDataNode
                                                                          valuation-only updater
                                                                                  |
                                                                                  v
                                                                         PortfoliosStorage
                                                                                  |
                                                                                  v
                                                                         PortfolioAnalytics
                                                                         optional derived updater
```

The portfolio workflow uses composition, not class inheritance.
`PortfoliosDataNode` does not subclass a rebalance strategy. It inherits the
economic state and timestamps of the rebalance process by consuming the
canonical executed-weight dependency.

Concrete strategies are implementations below `RebalanceStrategyBase`, not
architectural nodes above it. Immediate, calendar-triggered, time-weighted,
volume-participation, and liquidity-constrained execution all use the same
state-machine boundary.

### 1. PortfolioRebalance Owns Generic Strategy Orchestration

`PortfolioRebalance` is the canonical stateful rebalance-execution
`TimeIndexTableUpdater`. It is generic orchestration: it does not contain
calendar-, volume-, time-, or liquidity-specific branches.

It owns:

- the signal-weight dependency that publishes target intent;
- a serialized `RebalanceStrategyBase` implementation;
- the deterministic union of dependencies declared by that strategy;
- validation of each declared dependency against the strategy's required
  input columns and grain;
- loading the previous persisted rebalance state;
- feeding ordered, traceable source events to the strategy state machine; and
- production of `PortfolioRebalanceStateStorage` rows.

`dependencies()` must merge the reserved `signal_weights` dependency with the
strategy's declared `TimeIndexTableUpdater` or `TimeIndexTableRef`
dependencies. Dependency construction happens before `update()` and remains
deterministic. A strategy must not perform hidden table reads, construct an
upstream node inside its event loop, or obtain market inputs from global
process state.

The generic updater may supply execution bounds and persisted prior state. It
must not select strategy events, interpolate signals, assume a column named
`volume`, or branch on a `timing_mode` string.

### 2. RebalanceStrategyBase Is A Dependency-Declaring State Machine

Every active strategy must provide one typed contract with these semantics:

```text
declared_dependencies
  named, typed, hash-bearing market/event sources required by the strategy

required_input_contract
  expected grain and required fields for each declared dependency

select_events
  ordered eligible events selected only from declared source observations

prepare_execution_context
  optional run-scoped precomputation for facts reused by many event transitions

activate_target
  target-intent cutoff and succession policy

apply_event
  deterministic transition from prior state plus one observed event

result
  zero or more auditable state transitions plus the next unfinished state
```

The implemented Python methods are `declared_dependencies()`,
`required_input_contract()`, `select_events()`, `target_selection_mode()`, and
`apply_event()`. `prepare_execution_context()` is the optional optimization
hook for bounded rolling statistics or indexed lookups that must be computed
once rather than once per event. Those responsibilities may not move back into
`PortfolioRebalance`, `PortfolioWeights`, or `PortfoliosDataNode`.

All values that change output participate in serialization and hashing,
including dependency identities, required source columns, calendar/session or
window rules, cutoff, target succession, participation limits, liquidity
limits, price convention, fees, completion tolerance, and cancellation or
expiry behavior.

`timing_mode` remains open-ended descriptive metadata, but it is not the
dispatch interface. Adding a new strategy does not require editing a central
conditional in the generic updater.

### 3. Unfinished Execution Is Canonical State

A strategy may take many source events to reach one target. The workflow must
persist enough state to resume without pretending that a partially filled
target is complete or reconstructing progress from job time.

`PortfolioRebalanceStateStorage` has this conceptual grain:

```text
(time_index, portfolio_identifier, rebalance_intent_id, asset_identifier)
```

where `time_index` is the explicit signal, calendar, schedule, bar, quote,
book, liquidity, or fill event at which strategy state changed. The storage
contract must include, at minimum:

```text
rebalance_intent_id       deterministic identity of the activated target
target_signal_time_index source signal observation selected for the target
event_source              stable declared-dependency key
execution_status          pending | partial | complete | superseded |
                          cancelled | rejected
target_weight             activated target allocation
weight_before             executed allocation before this transition
weight_after              executed allocation after this transition
executed_weight_delta     allocation change produced by this event
remaining_weight_delta    unfinished allocation after this event
```

Price, executed quantity/notional, observed volume, and observed available
liquidity are optional execution facts when the strategy uses them. A
schema-versioned deterministic strategy-state payload may carry additional
state that cannot be represented by the common columns; it must not contain
live objects, credentials, process-local identifiers, or untraceable current
time.

The target-succession policy must explicitly decide what a later signal does
to unfinished work: replace, queue, ignore until completion, or another named
policy. A target is complete only when the configured completion rule is met.
Missing future bars or liquidity leave it unfinished and produce no invented
completion timestamp.

When several declared inputs have the same timestamp, the strategy must define
deterministic precedence or consolidation and emit at most one final state row
for each `(time_index, portfolio_identifier, rebalance_intent_id,
asset_identifier)` coordinate. Venue-level fills that require multiple records
at that coordinate remain in their own fill ledger and may be consumed as one
declared source.

This table is a portfolio rebalance-state ledger, not a broker order/fill
ledger. Live order routing and venue-native fill identity remain in the
execution domain; a portfolio strategy may consume an explicit fill source.

### 4. PortfolioWeights Is An Executed-Weight Projection

`PortfolioWeights` consumes canonical rebalance state and writes the current
executed allocation whenever `weight_after` changes. It contains no strategy
selection, date generation, signal interpolation, participation logic, or
unfinished-order policy.

It owns:

- the `PortfolioRebalance` dependency;
- deterministic projection of executed state transitions;
- production of `PortfolioWeightsStorage` rows.

Its output grain remains:

```text
(time_index, portfolio_identifier, asset_identifier)
```

`time_index` means the UTC timestamp at which the stored weight became
executed/current. It is not a reporting bucket and not the time the job ran.

Its timestamps are copied from rebalance-state transitions that changed
executed weights. The upstream strategy may select events from:

- original signal observations for a truly immediate strategy;
- persisted `CalendarSession.opens_at` or `closes_at` values for a
  calendar-relative strategy;
- actual execution/valuation bar timestamps for time-weighted or
  volume-participation strategies;
- an explicit reusable event-schedule dependency when a schedule is a
  separately published data product.

It must not use an untyped `pd.date_range(...)` as a substitute for one of
those sources. A calendar offset is permitted only as a hash-bearing,
traceable transformation of a persisted calendar event. For bar-, volume-,
liquidity-, or fill-driven strategies, the executed transition timestamp is
the actual selected source observation, not the earlier decision event.

### 5. Concrete Strategies Specialize The General Contract

Every active rebalance strategy must serialize the economic choices that
change its output. Calendar-relative strategies must express, at minimum:

```text
calendar_identifier
session_label
rebalance_event          market_open | market_close
event_offset
rebalance_cadence
signal_selection
```

Those fields participate in configuration hashing. Two strategies that differ
in event, cutoff, cadence, or offset are different update processes and produce
economically different portfolio identities. A strategy that needs an
execution price also declares the relevant observed source and price column;
that dependency identity and convention participate in hashing.

An immediate strategy has two valid modes, but they must not be conflated:

```text
signal_time
  execute at the signal observation when the instrument is executable

next_eligible_event
  map the signal observation to an explicitly configured future calendar event
```

A strategy that applies the latest signal at every market close is a
close-event strategy. It must not describe itself as immediate at the original
signal timestamp.

Calendar-relative strategies require a persisted calendar identifier and an
explicit `PortfolioCalendarEvents` or compatible published-event dependency.
That schedule producer reads `CalendarSession` rows, requires the canonical
`Calendar.unique_identifier`, and fails when the calendar is missing, an alias
is supplied, or the governed lookup fails.
`CalendarEventSignal` only filters the published observations; it performs no
hidden calendar read. Neither component silently falls back to
`pandas_market_calendars`, a process-local always-open calendar, or another
date generator.

Additional strategies use the same contract:

```text
time-weighted
  observes bars or a separately published execution schedule inside the
  configured window and advances a partial target at each source event

volume-participation
  declares price-and-volume bars and limits each transition by the observed
  bar volume and configured participation rate

trailing-average-daily-volume-participation
  declares completed daily VWAP-and-volume bars plus observable intraday
  execution bars; historical VWAP times volume estimates a daily notional cap,
  while the intraday price and volume determine actual execution

liquidity-constrained
  declares quotes, order-book depth, or another available-liquidity source and
  limits each transition by that observed capacity

fill-driven
  declares a venue or simulated-fill source and advances only from persisted
  fill observations
```

These strategies may use a calendar event to activate a target or open an
eligibility window. That decision timestamp is not automatically the executed
weight timestamp. Execution occurs only when the strategy's declared event
contract produces a state transition.

`PortfolioTable.calendar_uid` remains the portfolio's required reference
calendar. It is not an implicit rebalance clock. A calendar-aware strategy
must declare the exact persisted calendar source it consumes and must validate
any required relationship to the portfolio reference calendar. A strategy
that is driven only by bars, volume, liquidity, quotes, order books, schedules,
or fills does not gain calendar events merely because the portfolio row has a
calendar.

Historical VWAP is ex-post and therefore cannot be an assumed execution price.
For trailing daily-liquidity participation, only completed daily bars whose
right-edge availability timestamp is strictly before the configured session
execution window may enter the rolling capacity estimate. The actual
`execution_price` must come from the separately declared intraday execution
source at the transition timestamp. The per-asset daily capacity consumed must
survive restarts and target supersession within the same session.

The generic runner groups declared observations by timestamp and materializes
signal targets once per run. Strategies with rolling inputs use
`prepare_execution_context()` to build bounded lookup state once. They must not
scan full trailing history independently for every asset/event transition.
After any required input sorting, the reference trailing strategy performs
linear preparation in daily-history and execution-bar rows, plus the state
transitions that the output contract necessarily emits.

### 6. PortfoliosDataNode Owns Valuation Only

`PortfoliosDataNode` consumes:

- canonical executed weights;
- an explicit asset-indexed valuation source;
- the configured numeric valuation column;
- an explicit valuation alignment and staleness policy.

It owns:

- as-of selection of the latest executed holdings at each eligible valuation
  observation;
- valuation-source coverage checks for required held assets;
- portfolio-period return calculation;
- cumulative portfolio value calculation;
- production of `PortfoliosStorage` rows.

Its output grain remains:

```text
(time_index, portfolio_identifier)
```

`time_index` means the UTC timestamp of the portfolio valuation observation.
It does not have to equal the latest executed-weight timestamp.

The valuation timeline must come from explicit observations or events:

- by default, eligible timestamps from the valuation source itself;
- optionally, an explicit valuation-event source such as persisted calendar
  closes;
- never an internal generic date range derived only from an output-frequency
  string.

For sparse asset-indexed sources, an eligibility policy decides when all
required holdings have sufficiently fresh values. Per-asset as-of alignment
may select observations at or before an eligible valuation timestamp, but it
does not invent a new timestamp and must expose staleness or missing coverage.

### 7. PortfolioAnalytics Owns Resampling

Frequency conversion for display, comparison, charting, or performance
analysis belongs to an optional derived `PortfolioAnalytics`
`TimeIndexTableUpdater` or an equivalent consumer-owned analysis surface.

It may produce daily, weekly, monthly, or other analytical observations, but:

- its output has a separate storage identity from canonical portfolio values;
- its configuration declares frequency, label, closed-side, timezone,
  calendar, and aggregation semantics;
- it does not overwrite `PortfoliosStorage` rows;
- it preserves source-observation lineage;
- a bucket label is not presented as an economic execution timestamp.

If an analysis output uses `time_index`, that timestamp must truthfully be the
observation point of the analytical row. Period names or bucket boundaries
that are not observation points belong in explicit payload columns.

### 8. Job Time Is Operational Only

A Main Sequence Job schedule controls when computation starts. It does not
define signal, rebalance, execution, valuation, or analysis time.

Runs after the latest eligible event return an empty incremental update until
another upstream event or observation exists. Holidays, early closes, and DST
changes resolve through persisted calendar rows, not through the wall-clock
time of the job.

## Configuration Boundary

The public configuration is split conceptually into target, rebalance,
executed-weight, valuation, and analytics concerns.

Target ownership:

```text
Portfolio rebalance configuration
  signal_weights_instance
  rebalance_strategy_instance
  strategy-declared dependency instances or table references
  strategy event, cutoff, succession, completion, and state policy
  execution fee/participation/liquidity assumptions

Portfolio executed-weight configuration
  portfolio_rebalance_instance

Portfolio valuation configuration
  portfolio_weights_instance
  valuation_source_instance
  valuation_column
  valuation alignment/staleness policy

Portfolio analytics configuration
  portfolio_values_instance
  analysis frequency
  aggregation and labelling policy
```

The implementation realizes these boundaries with `PortfolioRebalance`,
`PortfolioRebalanceStateStorage`, `PortfolioWeights`, and
`PortfoliosDataNode`. `PortfolioCalendarEvents` is an optional explicit
schedule producer for calendar-aware strategies.

The portfolio configuration hash includes the canonical serialized rebalance
strategy and every declared dependency identity. This is how the portfolio
inherits the rebalance contract through composition. `PortfolioTable` does not
copy strategy fields, manufacture dates, or subclass the strategy.

The existing `BacktestingWeightsConfig`, `PortfolioExecutionConfiguration`,
and `PortfolioWeights`-as-executor surface is a migration source, not the final
general contract. No compatibility adapter may hide the new
`PortfolioRebalance` state dependency or map arbitrary strategies back to one
valuation-plus-optional-volume frame.

`portfolio_prices_frequency` must no longer drive rebalance event creation or
canonical portfolio resampling. It will be removed from the combined core
contract rather than retained with ambiguous meaning. Users needing a stable
valuation schedule configure a valuation-event source. Users needing sampled
output configure `PortfolioAnalytics`.

No compatibility adapter may silently recreate the old synthetic grid. If a
temporary migration adapter is provided, it must be explicit, deprecated, and
produce a warning that names the legacy timing assumptions.

## Temporal Invariants

The implementation must enforce these invariants:

1. Every `PortfolioRebalanceStateStorage.time_index` is traceable to an
   explicit signal, persisted calendar, published schedule, bar, quote,
   order-book, liquidity, or fill event selected by the serialized strategy.
2. Every `PortfolioWeightsStorage.time_index` equals a rebalance-state event at
   which executed weight changed; the projection creates no timestamp.
3. Every `PortfoliosStorage.time_index` is traceable to an explicit valuation
   observation or valuation event.
4. A signal observed after an event cutoff is never applied retroactively to
   that event.
5. Executed weights are selected as-of a valuation timestamp; valuation rows
   are not forced to occur only when weights change.
6. A portfolio may rebalance weekly and be valued daily without synthesizing
   daily rebalance rows.
7. Forward-fill or as-of selection is per asset, bounded by an explicit
   staleness policy, and observable in diagnostics.
8. Resampling cannot change canonical rebalance, execution, or valuation
   timestamps.
9. Configuration hashing distinguishes every dependency and policy choice
   that changes economic output.
10. The generic updater contains no strategy-type switch and no fixed
    assumptions about calendar, volume, liquidity, quote, or order-book
    columns.
11. Partial execution persists its active intent, executed state, remaining
    state, and status; absence of future input never forces completion.
12. A later signal is handled by an explicit hash-bearing target-succession
    policy.
13. Re-running before the next eligible event or observation produces no new
   rows.
14. Operational job timestamps never enter the economic data contract.

## Strategy Completion Policy

`TimeWeighted`, `VolumeParticipation`, and `LiquidityConstrained` are valid
active strategies because they declare and validate their observed inputs,
select actual source timestamps, persist partial or pending state, and resume
from that state. No supported strategy contains an unconditional
`NotImplementedError` or depends on the retired fixed valuation-plus-volume
frame API.

A future strategy stays outside the supported public surface until its
declared-input, event-provenance, transition, restart, succession, and
no-forced-completion tests pass.

## Incremental Update Semantics

Each updater advances from its own canonical output and dependencies:

```text
PortfolioRebalance
  progress = latest persisted state transition for portfolio_identifier,
             including every unfinished rebalance_intent_id
  end      = latest eligible event available from declared dependencies

PortfolioWeights
  progress = latest projected weight transition for portfolio_identifier
  end      = latest rebalance-state transition that changes executed weight

PortfoliosDataNode
  progress = latest portfolio-valuation timestamp for portfolio_identifier
  end      = latest eligible valuation observation with complete/policy-valid
             held-asset coverage

PortfolioAnalytics
  progress = latest analytical observation for its own output identity
  end      = latest canonical portfolio value eligible for aggregation
```

Each updater may overlap source reads as required for per-asset seeds and
same-timestamp deterministic replay, but it emits only transitions not already
represented by its canonical state. No component advances another component
by manufacturing timestamps up to `now`.

## Relationship To Existing Storage

The general strategy implementation adds one canonical state table and
preserves the existing executed-weight and portfolio-value grains:

```text
PortfolioRebalanceStateStorage
  (time_index, portfolio_identifier, rebalance_intent_id, asset_identifier)

PortfolioWeightsStorage
  (time_index, portfolio_identifier, asset_identifier)

PortfoliosStorage
  (time_index, portfolio_identifier)
```

`PortfolioRebalanceStateStorage.portfolio_identifier` references
`PortfolioTable.unique_identifier`, and `asset_identifier` references
`AssetTable.unique_identifier`. The common state columns described above are
ordinary typed columns. Any additional deterministic strategy-state payload
must be schema-versioned and bounded; it is not a substitute for the common
queryable status and remaining-target fields.

The existing `PortfolioTable.portfolio_weights_data_node_uid` remains the
direct pointer used by valuation and read services. The dependency graph from
that weights projection to `PortfolioRebalance` provides execution-state
lineage, so this amendment does not require another nullable pointer on
`PortfolioTable`.

This ADR does not require an immediate physical rename of
`PortfolioWeightsStorage.price_current`, `price_before`, or
`PortfoliosStorage.close`. Those names remain candidates for a separate schema
ADR and migration.

`PortfoliosStorage.close_time` must not be used to compensate for an incorrect
`time_index`. During implementation it should either equal the canonical
valuation observation timestamp or be removed/repurposed through an explicit
schema decision.

## Consequences

Positive consequences:

- Temporal ownership matches financial meaning.
- Rebalance strategies genuinely control when and how weights execute.
- Weekly execution and daily valuation become natural rather than exceptional.
- Signal cutoff, valuation staleness, early closes, and DST are testable.
- Canonical storage keeps real economic timestamps.
- Analytics can evolve without changing portfolio identity or execution.
- Incomplete strategies cannot borrow apparent completeness from portfolio
  forward-fill and resampling.
- Time-, volume-, liquidity-, quote-, book-, and fill-driven strategies can
  declare different inputs without changing generic orchestration.
- Partial execution and later resumption become explicit and auditable.

Tradeoffs:

- The implemented amendment adds `PortfolioRebalance`, a new storage contract,
  and a migration from `PortfolioWeights`-as-executor to a weights projection.
- Existing configuration payloads using `portfolio_prices_frequency` need a
  breaking migration or explicit deprecated adapter.
- The dependency graph gains a first-class rebalance-state producer and may
  gain explicit schedule, bar, liquidity, fill, or analytics producers.
- Execution and valuation may need separate source dependencies even when both
  happen to use the same market-data table.
- Tests and examples must distinguish signal, execution, valuation, analysis,
  and job timestamps.
- The additional state table is deliberate complexity: it keeps unfinished
  execution out of canonical weights and keeps strategy-specific logic out of
  portfolio valuation.

## Rejected Alternatives

### Keep One Synthetic Portfolio Grid

Rejected because one grid cannot truthfully represent signal, execution,
valuation, and analysis time. Adding more flags to
`portfolio_prices_frequency` would preserve the wrong owner.

### Put A Complete Timing Policy On PortfoliosDataNode

Rejected because it would make timing explicit but still leave the portfolio
valuation calculator responsible for rebalance execution.

### Generalize PortfolioWeights With timing_mode Branches

Rejected because a central switch still requires the portfolio updater to know
which strategies use signal events, calendars, bars, volume, or liquidity.
Optional fixed frames merely move the coupling into a wider method signature.

### Store Unfinished Work Only In PortfolioWeightsStorage

Rejected because an active target can change state without changing executed
weight, and several target intents may transition at one timestamp. A table
whose timestamp means "weight became current" cannot also truthfully represent
pending, superseded, rejected, or cancelled intent state.

### Make Each Strategy A Different Portfolio Updater

Rejected because it duplicates updater identity, storage lifecycle, incremental
orchestration, and normalization in every strategy. Strategies are composed
state machines under one `PortfolioRebalance` updater.

### Make PortfoliosDataNode Subclass RebalanceStrategyBase

Rejected because object-oriented inheritance would mix DataNode identity,
storage lifecycle, strategy configuration, and valuation behavior. The needed
relationship is composition through canonical executed weights.

### Force Portfolio Values Onto Rebalance Events

Rejected because portfolio valuation may be more frequent than rebalancing.
It would also omit economically meaningful mark-to-market movement between
weight changes.

### Use Job Scheduling As Rebalance Timing

Rejected because operational start time is not a reproducible economic event
and cannot correctly represent backfills, holidays, early closes, or delayed
data availability.

### Resample Canonical Portfolio Values In Place

Rejected because it replaces observation timestamps with analytical bucket
labels and makes downstream consumers unable to recover the canonical series.

## Migration Plan

### Baseline Stages 1-5: Temporal Separation (Implemented In 1.0.6)

#### Stage 1: Contract Tests

- Add failing tests for signal time, market open/close, early close, DST,
  before/after cutoff, weekly rebalance with daily valuation, and rerun no-op.
- Add invariants proving output timestamps originate from declared sources.
- Preserve focused regressions for per-asset valuation seed lookup and daily
  market-close timestamp preservation.

#### Stage 2: Execution Updater

- Promote `PortfolioWeights` to the execution/rebalance updater.
- Move strategy application and previous-weight lookup out of
  `PortfoliosDataNode`.
- Give active strategies typed, hash-bearing timing policies.
- Implement `ImmediateSignal` with truthful signal-time and/or
  next-eligible-event semantics.
- Remove unsupported strategies from the active public surface until complete.

#### Stage 3: Valuation Updater

- Make `PortfoliosDataNode` depend on canonical executed weights.
- Drive valuation timestamps from explicit valuation observations/events.
- Implement set-based per-asset as-of seed lookup with bounded staleness.
- Remove rebalance-index generation and final in-place resampling.

#### Stage 4: Analytics Updater

- Introduce the optional derived portfolio analytics/resampling surface.
- Give analytical outputs separate identity and explicit aggregation policy.
- Preserve canonical source timestamps and lineage.

#### Stage 5: Public Migration

- [x] Remove `portfolio_prices_frequency` from the core contract.
- [x] Update portfolio configuration serialization and hashing.
- [x] Update examples, tutorials, portfolio knowledge docs, skills, and changelog.
- [x] Document the breaking migration in the Unreleased changelog.
- [x] Require calendar-event strategies to resolve persisted calendars without
      a local fallback.
- [x] Provide a dry-run-first migration path for legacy midnight-indexed
      portfolio values.

### Amendment Stage 6: General Contract And State Storage (Implemented)

- [x] Add contract tests for declared dependencies, required input schemas,
  strategy-free orchestration, target succession, partial execution, restart,
  and absence of forced completion.
- [x] Add and migrate `PortfolioRebalanceStateStorage` with the state grain and
  common columns defined by this ADR.
- [x] Introduce `PortfolioRebalance` as the generic stateful updater.
- [x] Replace `execution_timestamps(...)` plus `apply_rebalance_logic(...)` with
  the dependency-declaring state-machine contract.

### Amendment Stage 7: Executed-Weight Projection (Implemented)

- [x] Convert `PortfolioWeights` into a pure projection of state transitions that
  changed executed weight.
- [x] Preserve `PortfolioWeightsStorage` grain and its use by
  `PortfoliosDataNode` and read services.
- [x] Prove that the projection copies source event timestamps and creates none.

### Amendment Stage 8: Strategy Migration (Implemented)

- [x] Migrate immediate and calendar-event behavior onto the general contract
  without changing their economic results.
- [x] Implement time-weighted and volume-participation strategies after their
  declared-input, partial-state, and restart tests pass.
- [x] Add a liquidity-constrained reference strategy using observed quote,
  order-book, or available-liquidity timestamps.
- [x] Keep any strategy with an unfinished state transition or undeclared input
  outside the public exports.

### Amendment Stage 9: Public Configuration Migration (Implemented)

- [x] Replace the combined execution path with explicit rebalance-state,
  executed-weight, and valuation composition.
- [x] Include strategy-declared dependency identities and all economic policies in
  canonical hashing.
- [x] Update docs, examples, tutorials, changelog, and migration guidance.
- [x] Treat the public contract change as a versioned breaking change; no adapter
  may silently recreate the fixed valuation-plus-optional-volume interface.

### Amendment Stage 10: Trailing Daily Liquidity (Implemented)

- [x] Add a public trailing daily-volume participation strategy with separate
  completed-daily capacity and observable intraday execution dependencies.
- [x] Exclude current-session and future daily VWAP observations from capacity
  and never use historical VWAP as `execution_price`.
- [x] Persist per-asset session consumption across restart and target
  supersession, then reset it only when a new session begins.
- [x] Precompute rolling history, signal targets, and event observation lookups
  once per run instead of performing repeated full-frame scans.

### Legacy Midnight-Indexed Values

Existing rows cannot be corrected by updating `time_index` in place. They are
owned by `PortfoliosDataNode`, and changing an indexed coordinate would bypass
the updater's storage lifecycle and make later incremental progress ambiguous.

The supported migration is therefore a portfolio-scoped rollback and replay:

1. Inspect the requested legacy window and the latest persisted row.
2. Resolve every candidate row through the portfolio's `calendar_uid` and
   persisted `CalendarSession` close. The old `close_time` must corroborate the
   mapping.
3. Refuse missing, ambiguous, conflicting, or only partially inspected tails.
4. Delete the inclusive tail with
   `TimeIndexMetaTable.delete_after_date(..., dimension_filters={"portfolio_identifier": [...]})`.
5. Rerun the migrated portfolio graph so `PortfoliosDataNode` deterministically
   rebuilds values at canonical valuation-source timestamps.

Apply one portfolio at a time with scheduled writers paused. The result checks
the deleted row count against the plan so a concurrent tail change is visible.
The migration never reconstructs a close from a fixed UTC hour, never uses raw
SQL, and never presents deletion alone as a completed repair. A second dry run
after replay must return no rollback.

## Acceptance Criteria

### Temporal-Separation Baseline (Implemented In 1.0.6)

The original temporal-separation decision is implemented because:

- In the 1.0.6 baseline, `PortfolioWeights` became the explicit
  execution/rebalance producer and `PortfoliosDataNode` consumed its canonical
  output. The amendment subsequently inserted `PortfolioRebalance` and made
  `PortfolioWeights` a projection.
- `PortfoliosDataNode` contains no rebalance-date generation.
- canonical portfolio valuation contains no in-place reporting resample.
- no core portfolio path uses a generic `pd.date_range(...)` to invent
  execution or valuation timestamps.
- immediate, calendar-relative, and bar-participation timing semantics are
  distinguishable in serialized configuration and hashing.
- signals immediately before and after a cutoff behave non-retroactively.
- normal sessions, holidays, early closes, and DST resolve from persisted
  calendar data.
- weekly rebalance with daily valuation produces sparse executed-weight rows
  and daily canonical value rows.
- per-asset valuation as-of alignment uses the last eligible observation for
  each required asset and enforces configured staleness.
- reruns before a new eligible event return no new rows.
- legacy midnight-indexed rows have a persisted-calendar-validated, scoped
  rollback-and-replay path that is idempotent after replay.
- analytical resampling writes a separate derived data product.
- unsupported unfinished strategies are not presented as executable.
- documentation and examples distinguish all temporal concepts and no longer
  describe `portfolio_prices_frequency` as a combined execution/valuation
  clock.

### General Strategy Amendment (Implemented)

The amended ADR is implemented because:

- `PortfolioRebalance` merges signal weights with arbitrary deterministic,
  typed dependencies declared by the serialized strategy.
- the generic updater contains no `timing_mode` or concrete-strategy branch and
  no fixed assumption about valuation, volume, quote, book, or liquidity
  columns.
- every strategy validates the grain and required fields of each declared
  dependency before applying events.
- event selection occurs after declared inputs are available and every emitted
  state timestamp is traceable to an input event or a permitted persisted
  calendar transformation.
- active intent, target signal, before/after executed state, remaining target,
  and nonterminal/terminal status survive an incremental restart.
- a lack of future bars, volume, liquidity, quotes, book updates, or fills
  leaves work unfinished and emits no synthetic completion.
- target succession is explicit, hash-bearing, and tested with a later signal
  arriving during partial execution.
- `PortfolioWeights` is a pure projection from rebalance state and creates no
  dates or strategy decisions.
- immediate and calendar-event strategies preserve their supported results on
  the new contract.
- time-weighted, volume-participation, and liquidity-constrained reference
  strategies pass event-provenance, partial-execution, no-liquidity, and rerun
  idempotency tests before export.
- trailing daily-volume participation uses only completed history for its daily
  cap, executes at the current declared intraday price, carries same-session
  consumption across restart/supersession, and performs bounded linear
  preparation before transition emission.
- the storage migration, public configuration migration, examples, tutorial,
  knowledge docs, and changelog are complete.
