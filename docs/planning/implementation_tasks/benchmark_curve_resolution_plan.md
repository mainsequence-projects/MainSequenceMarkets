# Benchmark Curve Resolution Implementation Plan

## Status

Implemented. This document records the verified pricing gap, the target
contract, and the implementation tasks that closed it.

## Success Condition

Benchmark-driven curve resolution is correct when a bond with
`benchmark_rate_index_uid` can resolve the intended valuation curve through
`PricingMarketDataSetCurveBindingTable` for the requested market-data set, role,
selector, and quote side; missing rows fail with actionable errors; z-spread and
other curve-dependent APIs do not silently fall back to unrelated curves; and
curve/fixing caches remain effective for repeated calls with the same resolved
curve identity.

## Verified Original State

`benchmark_rate_index_uid` is an instrument payload field. It points to
`IndexTable.uid`. It is not a curve UID and it is not enough to select a curve
by itself.

The complete curve selection key is:

```text
market_data_set
+ role_key
+ selector_type = index
+ selector_key = <benchmark_rate_index_uid>
+ quote_side
-> PricingMarketDataSetCurveBinding.curve_uid
-> Curve.unique_identifier
-> DiscountCurvesStorage.curve_identifier
-> CurveBuildingDetails.curve_uid
-> QuantLib YieldTermStructureHandle
```

The pre-implementation code did not fully enforce that graph:

- `Bond.get_benchmark_index_curve()` builds a QuantLib index through
  `resolve_quantlib_index(...)` and returns its forwarding term structure. It
  does not let the caller provide a benchmark-specific role or quote side.
- `resolve_quantlib_index(...)` defaults an index curve request to the
  `projection` role when `curve_type="discount"` is passed. That behavior is
  acceptable for floating-rate projection by convention, but it is not a
  z-spread base curve rule.
- `Bond.z_spread(...)` tries an explicit curve, then a floater index curve, then
  `get_benchmark_index_curve()`, then a default curve. It catches exceptions
  from index and benchmark resolution and converts them to `None`, so a missing
  benchmark binding can be hidden until a later generic "No discount curve"
  error.
- `PricingMarketDataSetCurveBinding` supports `quote_side`, and
  `curve_binding_key(...)` uses `default` when `quote_side` is omitted. The
  floating bond example previously wrote a `quote_side="mid"` binding, while
  pricing calls did not pass quote side. That meant the stored binding key was
  `projection:index:<uid>:mid`, but the resolver asked for
  `projection:index:<uid>:default`.
- The resolver API partly conflates role and curve type. `z_spread_base` is a
  valuation role, not necessarily the physical `Curve.curve_type`.

Tests that mock the resolver or only assert that a method was called do not
prove the end-to-end binding graph is correct. The example must be smoke-tested
against the same binding key that the runtime requests.

## Target Contract

Persisted instrument payloads may store an index UID, such as
`benchmark_rate_index_uid`, `floating_rate_index_uid`, or `float_leg_index_uid`.
Runtime curve selection must not assume that an index UID implies a unique curve.

Every code path that resolves a curve from persisted market-data bindings must
accept or carry the full selection context:

```text
market_data_set
role_key
selector_type
selector_key
quote_side
optional explicit curve_uid or curve_unique_identifier override
optional expected curve_type validation
```

For benchmark z-spread, the default binding role should be:

```text
role_key = "z_spread_base"
selector_type = "index"
selector_key = str(benchmark_rate_index_uid)
```

`quote_side` has no implicit `mid` fallback. If a caller wants the `mid` curve,
the caller must pass `quote_side="mid"` or the example must create a
`quote_side=None` default binding. The implementation should choose one policy
per example and test it end to end.

`role_key` and curve type validation must be decoupled. A role such as
`z_spread_base` may select a curve whose `Curve.curve_type` is `discount`,
`projection`, `government`, or another supported build type. The binding role
describes why the curve is selected; the curve row describes what the curve is.

## Implementation Tasks

- [x] Introduce a shared curve selection context.

Add a small pricing-owned helper, for example under
`msm_pricing.pricing_engine`, that carries the binding selection fields and can
produce stable cache keys.

Required behavior:

- [x] normalize `market_data_set` through `PricingMarketDataSet.resolve_uid(...)`
  when a persistent selection is needed;
- [x] normalize `quote_side` with the same rules as `curve_binding_key(...)`;
- [x] expose constructors for index-selected roles, especially projection,
  forwarding, discount, and z-spread base;
- [x] include role, selector, quote side, explicit override, and market-data set in
  cache keys;
- [x] avoid storing mutable QuantLib handles inside the selection object.

- [x] Add a direct curve-for-index resolver helper.

Add a helper that resolves a curve handle directly from an index selector:

```python
resolve_curve_for_index_binding(
    index_uid=...,
    valuation_date=...,
    market_data_set=...,
    role_key=...,
    quote_side=...,
    curve_uid=None,
    curve_unique_identifier=None,
    expected_curve_type=None,
)
```

This helper should call the semantic index curve selection path, which resolves
through `PricingMarketDataSetCurveBinding.resolve_index_curve_uid(...)`. It
should not build a QuantLib index just to get a curve handle, and callers should
not need to pass raw selector fields for index-scoped resolution.

Resolver validation must change so `role_key` selects the binding and
`expected_curve_type` validates the selected curve only when the caller asks for
that validation.

- [x] Fix benchmark z-spread resolution.

Update `Bond.z_spread(...)` so benchmark resolution follows the explicit
binding graph:

- [x] use caller-provided `discount_curve` if supplied;
- [x] for floating-rate instruments, resolve the floating projection curve through
   its own explicit projection selection context;
- [x] if `benchmark_rate_index_uid` exists, resolve
   `role_key="z_spread_base"` through `PricingMarketDataSetCurveBinding`;
- [x] only use `_get_default_discount_curve()` when no benchmark selector is
   configured.

Do not catch missing benchmark binding errors as a clean fallback. If
`benchmark_rate_index_uid` is configured and the selected market-data set has no
matching `z_spread_base:index:<uid>:<quote_side>` binding, raise an error that
names:

- `benchmark_rate_index_uid`;
- market-data set;
- role key;
- selector type/key;
- quote side;
- operation (`z_spread`).

- [x] Add binding arguments to public curve-dependent APIs.

Any public method that may resolve a curve from the market-data binding layer
must expose or carry the selection inputs it needs.

Minimum bond scope:

- [x] `price(...)`: keep current `with_yield` and explicit/default-curve behavior,
  but accept projection/discount quote-side arguments when the instrument family
  resolves a curve from bindings.
- [x] `analytics(...)`, `duration(...)`, and `get_cashflows(...)`: pass through the
  same curve-selection context used by `price(...)`.
- [x] `z_spread(...)`: accept `benchmark_curve_role_key`,
  `benchmark_curve_quote_side`, optional benchmark curve overrides, and optional
  expected curve-type validation.
- [x] `carry_roll_down(...)`: continue using the already-built curve, but the cache
  and diagnostics must identify the selection context used by the prior
  `price(...)` or `analytics(...)` call.

Minimum swap scope:

- [x] `InterestRateSwap.price(...)` and cashflow methods must accept the floating
  projection quote side or a shared curve-selection context before resolving
  `float_leg_index_uid`.

- [x] FastAPI operation metadata must expose the new parameters where applicable so
frontend calls can request the same binding key that setup created.

- [x] Preserve and verify caching.

`MSDataInterface.get_historical_discount_curve(...)` is cached at the interface
method boundary. Its effective cache key includes the curve identity argument,
target date, and `market_data_set`. That cache should remain in place.

Bond-level caches must include the normalized curve selection context. A change
from `quote_side="mid"` to `quote_side="offer"` must invalidate any cached
QuantLib index, pricer, price, analytics, duration, and z-spread result that
depends on the resolved curve.

Tests must verify:

- [x] repeated calls with the same benchmark selection do not reread the same curve
  observations unnecessarily;
- [x] changing quote side or role changes the binding lookup and invalidates the
  high-level pricing cache;
- [x] `MSDataInterface.cache_info()` or a monkeypatched read counter proves curve
  reads are still cached for identical `(curve_identifier, valuation_date,
  market_data_set)` requests.

## Required Tests

Add focused tests before claiming the implementation is correct:

- [x] `z_spread` with `benchmark_rate_index_uid` resolves through
  `PricingMarketDataSetCurveBinding.resolve_index_curve_uid(...)` with
  `role_key="z_spread_base"`, the benchmark index UID, and the caller's quote
  side.
- [x] Missing benchmark `z_spread_base` binding raises an actionable error and is
  not swallowed.
- [x] A binding created with `quote_side="mid"` is not found by an omitted
  quote-side request; the test should force the implementation or example to be
  explicit.
- [x] `resolve_curve_for_index_binding(...)` does not require a curve-owned index
  relationship.
- [x] `role_key` and `expected_curve_type` are tested independently.
- [x] Fixed-rate and zero-coupon bonds with `benchmark_rate_index_uid` can compute
  z-spread through the benchmark binding without requiring `reset_curve(...)`.
- [x] Floating-rate bonds still resolve their projection curve correctly after the
  shared selection context is introduced.
- [x] `InterestRateSwap` projection resolution accepts the same quote-side policy.
- [x] FastAPI asset pricing operations accept and forward the new curve-selection
  parameters for z-spread and curve-preview.
- [x] The bond pricing example uses the same quote-side policy it writes.

## Documentation And Example Tasks

Update all user-facing material in the same implementation:

- [x] `docs/knowledge/msm_pricing/runtime_resolution.md`: add the benchmark
  z-spread path and make clear that `benchmark_rate_index_uid` is only an index
  selector.
- [x] `docs/knowledge/msm_pricing/market_data_sets.md`: document `z_spread_base`
  bindings with quote-side policy.
- [x] `docs/knowledge/msm_pricing/curves.md`: show benchmark z-spread curve
  binding setup.
- [x] `docs/tutorial/05-pricing.md`: replace any curve-index shortcut language with
  `Curve`, `CurveBuildingDetails`, and `PricingMarketDataSetCurveBinding`.
- [x] `docs/fast_api/v1/fixed_income_pricer.md` and the related ADR: document new
  operation parameters.
- [x] `.agents/skills/ms_markets/pricing/fixed_income_curve_building/SKILL.md`:
  keep agent guidance aligned so future changes do not claim benchmark
  resolution without a binding.
- [x] `examples/msm_pricing/bond_pricing_example/main.py`: either use a default
  quote-side binding or pass the same quote side to runtime calls.
- [x] Add or extend an example for a fixed-rate bond with
  `benchmark_rate_index_uid`, a `z_spread_base` curve binding, and
  `z_spread(...)` using the explicit selection context.

## Non-Goals

This plan does not make `CurveTable` own an index foreign key.

This plan does not make a bare `benchmark_rate_index_uid` enough to resolve a
curve.

This plan does not silently default omitted quote side to `mid`.

This plan does not require fixed-rate `price()` to automatically use the
benchmark curve as its discount curve. That would be a separate pricing policy
decision. The immediate fix is that any function that claims to resolve a
benchmark curve must accept and use the binding selection context required to
resolve the correct curve.
