# 0040. Portfolio Temporal Ownership And Execution-Valuation Separation

## Status

Accepted - implemented

Implemented in the portfolio execution, valuation, analytics, configuration,
examples, and regression-test surfaces described below.

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
[Issue #2](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/2)
and [issue #3](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/3)
remain separate implementation defects, although this decision changes the
component in which their fixes belong.

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

The current implementation collapses these distinctions into a synthetic
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

The inconsistency is visible in the existing strategies:

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

## Problem

The current design has no single truthful owner for economic timestamps.

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

## Decision

Separate portfolio execution, portfolio valuation, and portfolio analytics
into distinct temporal owners.

The target graph is:

```text
SignalWeights -------------------+
                                  |
CalendarSession / signal events  +--> PortfolioWeights
                                  |    execution/rebalance updater
Execution valuations / bars -----+            |
                                               | executed weights at actual
                                               | execution timestamps
                                               v
                                     PortfolioWeightsStorage
                                               |
                                               |
ValuationSource ------------------------------+--> PortfoliosDataNode
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

### 1. PortfolioWeights Owns Rebalance And Execution

`PortfolioWeights` becomes the canonical execution/rebalance
`TimeIndexTableUpdater`, rather than a post-calculation writer populated by
`PortfoliosDataNode` through an in-memory frame.

It owns:

- the signal-weight dependency;
- the rebalance strategy and its serialized timing policy;
- event eligibility and signal cutoff/as-of selection;
- any execution valuation or bar dependency required by the strategy;
- previous executed-weight state;
- fees or execution assumptions that affect executed weights;
- production of `PortfolioWeightsStorage` rows.

Its output grain remains:

```text
(time_index, portfolio_identifier, asset_identifier)
```

`time_index` means the UTC timestamp at which the stored weight became
executed/current. It is not a reporting bucket and not the time the job ran.

The execution updater may resolve timestamps from:

- original signal observations for a truly immediate strategy;
- persisted `CalendarSession.opens_at` or `closes_at` values for a
  calendar-relative strategy;
- actual execution/valuation bar timestamps for time-weighted or
  volume-participation strategies;
- an explicit reusable event-schedule dependency when a schedule is a
  separately published data product.

It must not use an untyped `pd.date_range(...)` as a substitute for one of
those sources.

### 2. Rebalance Timing Is A Typed Strategy Contract

Every active rebalance strategy must serialize the economic choices that
change its output. Calendar-relative strategies must express, at minimum:

```text
calendar_identifier
session_label
rebalance_event          market_open | market_close
event_offset
rebalance_cadence
signal_selection
execution_valuation
```

Those fields participate in configuration hashing. Two strategies that differ
in event, cutoff, cadence, offset, or valuation convention are different
update processes and produce economically different portfolio identities.

`ImmediateSignal` has two valid modes, but they must not be conflated:

```text
signal_time
  execute at the signal observation when the instrument is executable

next_eligible_event
  map the signal observation to an explicitly configured future calendar event
```

A strategy that applies the latest signal at every market close is a
close-event strategy. It must not describe itself as immediate at the original
signal timestamp.

Calendar-relative strategies require a persisted calendar identifier. Runtime
resolution must read `CalendarSession` rows and must fail when the calendar is
missing, its source identifier is ambiguous, or the governed lookup fails. A
serialized economic strategy must never silently fall back to
`pandas_market_calendars`, a process-local always-open calendar, or another
date generator. Those helpers may remain available only through an explicitly
named legacy utility that cannot be selected by `CalendarEventSignal`.

### 3. PortfoliosDataNode Owns Valuation Only

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

### 4. PortfolioAnalytics Owns Resampling

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

### 5. Job Time Is Operational Only

A Main Sequence Job schedule controls when computation starts. It does not
define signal, rebalance, execution, valuation, or analysis time.

Runs after the latest eligible event return an empty incremental update until
another upstream event or observation exists. Holidays, early closes, and DST
changes resolve through persisted calendar rows, not through the wall-clock
time of the job.

## Configuration Boundary

The current combined configuration will be split conceptually into execution
and valuation concerns.

Target ownership:

```text
Portfolio execution configuration
  signal_weights_instance
  rebalance_strategy_instance
  strategy timing policy
  execution valuation/bar source when required
  execution fee/participation assumptions

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

Exact public class names may be refined during implementation, but these
ownership boundaries are mandatory.

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

1. Every `PortfolioWeightsStorage.time_index` is traceable to an explicit
   signal, calendar, schedule, or execution-data timestamp selected by the
   serialized strategy policy.
2. Every `PortfoliosStorage.time_index` is traceable to an explicit valuation
   observation or valuation event.
3. A signal observed after an event cutoff is never applied retroactively to
   that event.
4. Executed weights are selected as-of a valuation timestamp; valuation rows
   are not forced to occur only when weights change.
5. A portfolio may rebalance weekly and be valued daily without synthesizing
   daily rebalance rows.
6. Forward-fill or as-of selection is per asset, bounded by an explicit
   staleness policy, and observable in diagnostics.
7. Resampling cannot change canonical execution or valuation timestamps.
8. Configuration hashing distinguishes every timing choice that changes
   economic output.
9. Re-running before the next eligible event or observation produces no new
   rows.
10. Operational job timestamps never enter the economic data contract.

## Incomplete Strategy Policy

`TimeWeighted` and `VolumeParticipation` are not valid active strategies while
their execution paths raise `NotImplementedError`.

During migration they must either:

- be completed against the new execution-updater contract and tested using
  actual input-bar timestamps; or
- be removed from the supported public strategy surface until completed.

Dead code after an unconditional `NotImplementedError` is not treated as a
partial implementation and must not be used to justify serialized behavior.

## Incremental Update Semantics

Each updater advances from its own canonical output and dependencies:

```text
PortfolioWeights
  progress = latest executed-weight timestamp for portfolio_identifier
  end      = latest eligible execution event with required source coverage

PortfoliosDataNode
  progress = latest portfolio-valuation timestamp for portfolio_identifier
  end      = latest eligible valuation observation with complete/policy-valid
             held-asset coverage

PortfolioAnalytics
  progress = latest analytical observation for its own output identity
  end      = latest canonical portfolio value eligible for aggregation
```

No component advances another component by manufacturing timestamps up to
`now`.

## Relationship To Existing Storage

The first implementation should preserve the existing physical storage grains
and foreign keys:

```text
PortfolioWeightsStorage
  (time_index, portfolio_identifier, asset_identifier)

PortfoliosStorage
  (time_index, portfolio_identifier)
```

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

Tradeoffs:

- `PortfoliosDataNode` and `PortfolioWeights` require a substantial refactor.
- Existing configuration payloads using `portfolio_prices_frequency` need a
  breaking migration or explicit deprecated adapter.
- The dependency graph gains a first-class executed-weight producer and may
  gain explicit schedule/analytics producers.
- Execution and valuation may need separate source dependencies even when both
  happen to use the same market-data table.
- Tests and examples must distinguish signal, execution, valuation, analysis,
  and job timestamps.

## Rejected Alternatives

### Keep One Synthetic Portfolio Grid

Rejected because one grid cannot truthfully represent signal, execution,
valuation, and analysis time. Adding more flags to
`portfolio_prices_frequency` would preserve the wrong owner.

### Put A Complete Timing Policy On PortfoliosDataNode

Rejected because it would make timing explicit but still leave the portfolio
valuation calculator responsible for rebalance execution.

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

### Stage 1: Contract Tests

- Add failing tests for signal time, market open/close, early close, DST,
  before/after cutoff, weekly rebalance with daily valuation, and rerun no-op.
- Add invariants proving output timestamps originate from declared sources.
- Preserve focused regressions for per-asset valuation seed lookup and daily
  market-close timestamp preservation.

### Stage 2: Execution Updater

- Promote `PortfolioWeights` to the execution/rebalance updater.
- Move strategy application and previous-weight lookup out of
  `PortfoliosDataNode`.
- Give active strategies typed, hash-bearing timing policies.
- Implement `ImmediateSignal` with truthful signal-time and/or
  next-eligible-event semantics.
- Remove unsupported strategies from the active public surface until complete.

### Stage 3: Valuation Updater

- Make `PortfoliosDataNode` depend on canonical executed weights.
- Drive valuation timestamps from explicit valuation observations/events.
- Implement set-based per-asset as-of seed lookup with bounded staleness.
- Remove rebalance-index generation and final in-place resampling.

### Stage 4: Analytics Updater

- Introduce the optional derived portfolio analytics/resampling surface.
- Give analytical outputs separate identity and explicit aggregation policy.
- Preserve canonical source timestamps and lineage.

### Stage 5: Public Migration

- [x] Remove `portfolio_prices_frequency` from the core contract.
- [x] Update portfolio configuration serialization and hashing.
- [x] Update examples, tutorials, portfolio knowledge docs, skills, and changelog.
- [x] Document the breaking migration in the Unreleased changelog.
- [x] Require calendar-event strategies to resolve persisted calendars without
      a local fallback.
- [x] Provide a dry-run-first migration path for legacy midnight-indexed
      portfolio values.

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

This ADR is implemented only when:

- `PortfolioWeights` is the explicit execution/rebalance producer and
  `PortfoliosDataNode` consumes its canonical output.
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
