# 0036. Prepared Pricing Valuation Context

## Status

Accepted - implemented

## Context

[ADR 0033](0033-pricing-valuation-position-boundary.md) defines
`ValuationLine` and `ValuationPosition` as transient pricing baskets:
instrument terms plus units for one valuation date and one market-data set.
That boundary is correct, but it is not enough for portfolio or scenario
valuation.

The current runtime is still shaped around lazy single-instrument valuation.
Each instrument call can prepare itself by resolving the active market-data set,
index conventions, curve bindings, curve rows, curve-building details, fixing
observations, and curve observations. That behavior is acceptable for ad hoc
single-instrument pricing, but it is the wrong operational model for a
portfolio or scenario run where the full instrument universe is already known
before pricing starts.

The fixed-income runtime graph is intentionally explicit:

```text
market_data_set selector
  -> PricingMarketDataSet.uid
  -> PricingMarketDataSetBinding rows for required concepts
  -> instrument index UIDs
  -> IndexConventionDetails rows
  -> PricingMarketDataSetCurveBinding rows by role/index/quote side
  -> Curve rows
  -> CurveBuildingDetails rows
  -> curve and fixing observations for the valuation date
  -> QuantLib handles and indexes
```

Walking that graph once per instrument creates repeated backend row lookups and
late, line-local failures. Hiding those repeated lookups behind a new public API
method would only move the loop; it would not fix the architecture.

There is also a public API problem. Users should not have to call a private
method such as a valuation-position internal instrument dispatcher to price one
line with a prepared curve handle or scenario input. Private helpers are not a
stable integration surface.

## Decision

Introduce a prepared valuation context for `msm_pricing`.

The public runtime object is named `PricingValuationContext`. It is an
in-memory runtime object, not a SQLAlchemy model, MetaTable, or persisted
valuation-run row. Its public import surface should live with the valuation
basket API:

```python
from msm_pricing.valuation import PricingValuationContext
```

It may also be re-exported from `msm_pricing` for convenience. Internal
SQLAlchemy query planning, repository operations, and QuantLib resolver adapters
can live under lower-level repository or pricing-engine modules.

The public abstraction is:

```python
context = PricingValuationContext.prepare(
    valuation_date=valuation_date,
    market_data_set="default",
    instruments=[line.instrument for line in position.lines],
    curve_quote_side="mid",
)
```

The prepared context is the boundary between platform-backed resolution and the
local pricing hot loop. It must resolve shared market data with set-based query
planning before line pricing begins.

The implementation satisfies this core rule:

```text
After PricingValuationContext.prepare(...) returns, line pricing must not call
backend row APIs to resolve market-data-set rows, index conventions, curve
bindings, curve rows, curve-building details, curve observations, or fixings.
```

If a later implementation violates that rule, the implementation is incomplete
even if the public method name looks convenient.

## Required Query Shape

Context preparation must use bulk SQLAlchemy-backed resolution, repository
operations, or compiled set-based operations over the relevant SQLAlchemy
models. It must not perform one row API lookup per instrument, index, curve, or
valuation line.

The prepared context does the following work as batched resolution:

1. Resolve the selected `PricingMarketDataSet` once by key or UID.
2. Load all required `PricingMarketDataSetBinding` rows for the selected set and
   required concept keys in one query.
3. Inspect all submitted instruments and collect every required backend index
   UID by role, including floating-rate indexes, swap floating-leg indexes, and
   benchmark indexes used for analytics such as z-spread.
4. Load all referenced `IndexTable` and `IndexConventionDetailsTable` rows with
   set-based `IN` predicates or equivalent joined queries.
5. Construct the required curve-binding keys for the requested roles, selectors,
   quote sides, and market-data set, then load the matching
   `PricingMarketDataSetCurveBindingTable` rows in bulk.
6. Load all selected `CurveTable` and `CurveBuildingDetailsTable` rows in bulk
   by `curve_uid`.
7. Query curve observations for all required `Curve.unique_identifier` values
   with a batched latest-at-or-before valuation-date strategy.
8. Query index fixings for all required `IndexTable.unique_identifier` values
   and fixing dates needed by the submitted instruments.
9. Build QuantLib term-structure handles and QuantLib indexes from the cached
   rows and observations.

The exact repository APIs can evolve, but the query plan is part of the
contract. A method that loops through instruments and internally calls existing
single-row resolvers is not an implementation of this ADR.

## Public API Shape

`PricingValuationContext` should be usable directly and through
`ValuationPosition`.

Target direct usage:

```python
context = PricingValuationContext.prepare(
    valuation_date=valuation_date,
    market_data_set="eod",
    instruments=instruments,
    curve_quote_side="mid",
)

prepared = context.prepare_instrument(instrument)
price = prepared.price()
```

`prepare_instrument(...)` must return a new prepared object. It must not return
the submitted `instrument` after mutating it in place.

Target valuation-position usage:

```python
context = PricingValuationContext.prepare_for_position(
    position,
    curve_quote_side="mid",
)

result = position.price(context=context)
```

Target scenario usage:

```python
result = msm_pricing.price_scenario(
    position=position,
    context=context,
    line_curve_handles=base_handles_by_line,
    scenario_curve_handles=scenario_handles_by_line,
)
```

`PricingValuationContext` is the final public name. Supporting method names may
change during implementation, but the public surface must satisfy these
constraints:

- users do not call private methods to price a line;
- the context can be prepared before entering a portfolio loop;
- scenario curve-handle overrides are explicit inputs;
- the hot loop prices from cached rows, prepared handles, and local QuantLib
  objects only;
- missing data is detected during context preparation where possible.

## Prepared Instrument Boundary

Preparing an instrument must not mutate caller-owned instrument objects in the
public portfolio/scenario workflow. Scenario pricing often needs the same
submitted instrument terms priced under several curve-handle sets. Mutating the
original instrument risks leaking handles, valuation dates, QuantLib index
state, cached fixings, or scenario curve handles across lines or scenarios.

The required implementation shape is a prepared wrapper or cloned instrument:

```text
InstrumentModel terms
  + PricingValuationContext caches
  + optional scenario handle overrides
  -> PreparedInstrument
```

The public API should make the copy boundary obvious:

```python
prepared = context.prepare_instrument(instrument)

assert prepared is not instrument
```

`PreparedInstrument` may wrap the original immutable terms plus prepared
runtime state, or it may own a deep copy of the submitted instrument terms. In
either case, all mutable QuantLib state belongs to the prepared object, not to
the caller-owned input instrument.

Acceptable implementation strategies include:

- rebuilding a concrete instrument from its serialized terms;
- using a validated deep copy of the Pydantic instrument model;
- wrapping the original terms in a separate prepared object that holds all
  valuation date, curve-handle, QuantLib index, and fixing state.

The context API may expose an explicitly named in-place escape hatch only if a
future implementation has a measured need for it. That escape hatch must not be
the default, must not be used by `ValuationPosition` or `price_scenario(...)`,
and must be named so mutation is visible at the call site. A generic
`prepare_instrument(...)` method that mutates its argument is not acceptable.

The prepared object must not perform backend row resolution during pricing.

## Validation And Errors

Context preparation should fail before pricing when the valuation graph is
incomplete or ambiguous.

Required failures include:

- unknown market-data set key or UID;
- missing required concept binding, such as discount curves or interest-rate
  index fixings;
- missing index convention details for an instrument index UID;
- missing or duplicate curve selection for a required role/index/quote-side
  binding;
- missing curve-building details for a selected curve;
- missing curve observations for the selected valuation date policy;
- missing required fixings for the submitted instruments.

Errors should report the market-data set, role, selector, quote side, index UID,
curve UID, and valuation date where applicable. Portfolio users need one
preflight failure report, not one surprising exception after the pricing loop
has already started.

## Non-Goals

This ADR does not:

- persist valuation runs;
- create a durable pricing position table;
- move account holdings or portfolio weights into `msm_pricing`;
- define every scenario-shock model;
- remove single-instrument convenience pricing;
- require every ad hoc `bond.price(...)` call to build a portfolio context;
- cache market-data rows globally across unrelated valuation contexts.

Single-instrument pricing may keep its convenience path. Portfolio and scenario
pricing need the prepared-context path.

## Rejected Patterns

Do not satisfy this ADR by adding only a public method that internally loops
over lines and calls current single-instrument preparation.

Do not satisfy this ADR with a global `lru_cache` around row APIs. The cache key
would be difficult to align with valuation date, market-data set, quote side,
scenario, storage table, and request identity. It would also hide stale-data
and invalidation problems.

Do not ask callers to manually resolve and pass every UID as the normal
portfolio workflow. Passing resolved UIDs can be a temporary application
workaround, but the library should own the prepared valuation context.

Do not expose private valuation-position methods as the recommended user
workflow. If users need the behavior, it belongs behind a public API with a
documented contract.

Do not implement `context.prepare_instrument(instrument)` by mutating
`instrument` and returning it. That leaks prepared runtime state into caller
objects and makes scenario valuation unsafe.

## Implementation Tasks

Completed decision work:

- [x] Record the prepared valuation context decision in this ADR.
- [x] Select `PricingValuationContext` as the final public runtime-context name.
- [x] Select `msm_pricing.valuation` as the public import surface for
  `PricingValuationContext`, with optional package-level re-export from
  `msm_pricing`.
- [x] Record the core invariant that context preparation must use bulk
  SQLAlchemy-backed or compiled set-based resolution instead of hiding
  per-line backend lookup loops.
- [x] Record the copy/wrapper requirement for prepared instruments and reject
  mutating caller-owned instruments in the public portfolio/scenario workflow.
- [x] Wire the ADR into the architecture index and MkDocs navigation.
- [x] Link the decision from the pricing overview, runtime-resolution page, and
  instrument valuation-basket documentation.
- [x] Add the ADR to the changelog.

Completed implementation work:

- [x] Add the public `PricingValuationContext` preparation API under
  `msm_pricing.valuation`, including `prepare(...)` for explicit instrument
  lists and `prepare_for_position(...)` for `ValuationPosition`.
- [x] Re-export `PricingValuationContext` and `PreparedInstrument` from the
  package-level `msm_pricing` import surface.
- [x] Freeze the context input contract in `PricingValuationContextSpec`,
  including `valuation_date`, market-data-set selector or UID, requested quote
  side, requested valuation roles, and the prepared instrument universe.
- [x] Add a pricing-requirement extraction layer for
  `floating_rate_index_uid`, `float_leg_index_uid`, and
  `benchmark_rate_index_uid`, including valuation role and quote-side curve
  binding keys.
- [x] Resolve the selected market-data set once during context preparation.
- [x] Add set-based row API operations for `PricingMarketDataSetBinding` concept
  bindings through `search_model(..., in_filters=...)`.
- [x] Add set-based `IndexTable` row loading so context preparation caches both
  index identity rows and convention rows.
- [x] Add set-based row API operations for `IndexConventionDetailsTable`
  convention rows by `index_uid`.
- [x] Add set-based row API operations for
  `PricingMarketDataSetCurveBindingTable` by curve-binding key.
- [x] Add set-based row API operations for `CurveTable` by `uid` and
  `CurveBuildingDetailsTable` by `curve_uid`.
- [x] Build the context cache from resolved concept bindings, index
  convention rows, curve binding rows, curve rows, and curve-building details.
- [x] Add batched curve-observation reads for all required
  `Curve.unique_identifier` values using a latest-at-or-before valuation-date
  policy.
- [x] Add batched index-fixing reads for all required fixing identifiers using
  the resolver-compatible historical fixing window.
- [x] Extend the context cache to include index rows, curve observations,
  fixing observations, QuantLib term-structure handles, and base QuantLib
  indexes built from cached rows.
- [x] Add a `PreparedInstrument` wrapper over a cloned instrument so the public
  prepared path does not mutate caller-owned instrument objects.
- [x] Ensure `context.prepare_instrument(instrument)` returns a distinct
  prepared object for that submitted instrument.
- [x] Reject instruments outside the frozen prepared universe instead of
  silently expanding an existing context.
- [x] Add public `ValuationPosition` methods that accept a prepared context for
  `price`, `price_breakdown`, `analytics`, `get_cashflows`, and
  `get_net_cashflows`.
- [x] Preserve single-instrument convenience pricing while adding the
  prepared-context path.
- [x] Add preflight validation for missing concept bindings, missing
  index conventions, missing or duplicate curve bindings, missing curve rows,
  and missing curve-building details.
- [x] Add preflight validation for missing curve observations and missing
  fixing observations.
- [x] Add cached resolver adapters so prepared floating-rate bond pricing uses
  context state instead of re-entering backend row APIs.
- [x] Add a public `price_scenario(...)` helper with explicit line-scoped base
  and scenario curve-handle overrides.
- [x] Add query-shape tests for the set-based row API operations used by context
  preparation.
- [x] Add context preparation tests proving fixed-income row resolution is
  batched before instrument pricing.
- [x] Add copy/isolation tests proving prepared instruments do not mutate
  caller-owned instruments.
- [x] Add hot-loop tests proving prepared line pricing performs no backend row
  API resolution for market-data-set UID, index rows/conventions, curve
  bindings, curve rows, curve-building details, curve observations, or fixings.
- [x] Add scenario isolation tests proving curve handles cannot leak across
  lines or scenarios.
- [x] Add parity tests proving prepared-context single-line results match the
  existing supported single-instrument pricing path for the same market data.
- [x] Update package knowledge docs, tutorial docs, examples, and changelog with
  the public prepared-context workflow.

## Success Criteria

The ADR implementation is complete when:

- a user can price a valuation basket without calling a private method;
- a user can prepare one context for a known instrument universe;
- context preparation uses set-based SQLAlchemy-backed resolution instead of
  per-line row API lookup loops;
- the post-prepare pricing loop performs no backend row resolution for
  market-data-set UID, index conventions, curve bindings, curve rows,
  curve-building details, curve observations, or fixings;
- missing market-data graph pieces fail during preparation with actionable
  errors;
- `context.prepare_instrument(instrument)` returns a distinct prepared wrapper
  or clone and leaves the submitted instrument free of prepared runtime state;
- scenario pricing can inject explicit curve-handle overrides without leaking
  mutable state across instruments or scenarios;
- docs, examples, tutorial, and changelog describe the public workflow.

## Consequences

Positive consequences:

- portfolio and scenario valuation get a real performance boundary instead of a
  hidden loop;
- market-data failures become preflight errors instead of late line failures;
- users get a public API for prepared valuation instead of relying on private
  methods;
- the query plan becomes testable and reviewable.

Negative consequences:

- implementation complexity moves into a dedicated context/query-planning
  layer;
- resolver tests must cover query shape, not only returned prices;
- single-instrument convenience paths and prepared-context paths must share
  semantics without duplicating business rules.
