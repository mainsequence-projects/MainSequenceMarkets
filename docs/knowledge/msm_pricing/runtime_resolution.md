# Runtime Resolution

This page traces how `price()` walks the persisted graph at runtime, from an
instrument payload down to QuantLib objects, and gives the end-to-end ordering a
user follows to build a priceable fixed-income asset.

For portfolio and scenario valuation, [ADR 0036](../../ADR/0036-prepared-pricing-valuation-context.md)
defines the implemented prepared-context path. The prepared context resolves
the same persisted graph with set-based SQLAlchemy-backed queries before line
pricing begins, rather than repeating this resolution once per instrument.

## Runtime Resolution

When a user calls:

```python
bond = Instrument.load_from_asset(asset)
bond.set_valuation_date(valuation_date)
price = bond.price()
```

the runtime should follow the persisted graph:

```text
+-----------------------------+
| Instrument payload          |
|-----------------------------|
| benchmark_rate_index_uid    |
| floating_rate_index_uid     |
| float_leg_index_uid         |
+--------------+--------------+
               |
               | reference to canonical index identity
               v
+-----------------------------+
| msm.IndexTable              |
|-----------------------------|
| uid                         |
| unique_identifier           |
+--------------+--------------+
               |
               | one-to-one pricing extension
               v
+-----------------------------+
| IndexConventionDetails      |
|-----------------------------|
| index_family                |
| convention_dump             |
+--------------+--------------+
               |
               | market_data_set + role/selector curve binding
               v
+-----------------------------+
| PricingMarketDataSetCurve   |
| Binding                     |
+--------------+--------------+
               |
               | curve_uid
               v
+-----------------------------+
| CurveTable                  |
|-----------------------------|
| unique_identifier           |
| curve_type                  |
+--------------+--------------+
               |
               | one-to-one build specification
               v
+-----------------------------+
| CurveBuildingDetails        |
|-----------------------------|
| builder_type                |
| quote_convention            |
| day_counter_code            |
| calendar_code               |
| interpolation_method        |
| compounding                 |
+--------------+--------------+
               |
               | load observations for valuation date
               v
+-----------------------------+
| DiscountCurvesNode          |
|-----------------------------|
| curve_identifier            |
| curve                       |
| key_nodes                   |
+--------------+--------------+
               |
               | Pydantic validation + QuantLib adapters
               v
+-----------------------------+
| msm_pricing.pricing_engine  |
|-----------------------------|
| ql.Index                    |
| ql.YieldTermStructure       |
| price() / cashflows()       |
+-----------------------------+
```

The `DiscountCurvesNode` and `FixingRatesNode` locations used in this chain come
from pricing market-data bindings; see [Market Data Sets](market_data_sets.md)
for how the selected set resolves to a `data_node_uid`.

Runtime pricing reads the compressed `curve` payload. `key_nodes` is retained on
the same curve observation row as compressed-at-rest construction provenance.
The data interface and FastAPI responses return it as producer-owned JSON. It
may include per-node `quote_type`, `quote_unit`, `quote_side`, and yield-native
fields when those describe the raw source inputs. Source publishers may add
their own extensions and enforce them through the DataNode validation hook.
Runtime pricing does not infer the final curve interpretation from `key_nodes`;
`CurveBuildingDetails` remains the source for the constructed curve convention.

Curve selection must be strict:

- first resolve `PricingMarketDataSetBinding` for the storage source, such as
  `discount_curves -> DiscountCurvesStorage`;
- then resolve `PricingMarketDataSetCurveBinding` for the valuation role and
  selector, such as `projection:index:<IndexTable.uid>:mid -> CurveTable.uid`;
- then load `CurveBuildingDetails` for the selected curve;
- then build the QuantLib curve with the declared `interpolation_method`,
  compounding, frequency, day counter, and calendar;
- if any row is missing, fail with a specific missing-binding or missing-build
  detail error.

This lets curve-dependent operations work without silently picking ambiguous
market data or using an implicit curve-index relationship as a policy shortcut.
Index-based user workflows should create those rows with
`PricingMarketDataSetCurveBinding.upsert_index_curve_selection(...)`; the raw
`selector_type` and `selector_key` fields are the persisted generic selector
format.
Fixed-rate and zero-coupon `price()` still use `with_yield`, an explicitly reset
curve, or another explicit pricing policy. They do not automatically turn
`benchmark_rate_index_uid` into a discount curve.

Curve construction is native QuantLib construction. The resolver supports only
the documented non-deprecated methods: `log_linear_discount`,
`log_cubic_discount`, `linear_zero`, `cubic_zero`, `natural_cubic_zero`,
`monotone_cubic_zero`, and `linear_forward` for `forward_rate` quotes. Deprecated
QuantLib methods such as `log_linear_zero` and
`MonotonicLogCubicDiscountCurve` fail loudly.

Helper-based reconstruction is a separate resolver branch. When
`CurveBuildingDetails.builder_type="rate_helper_curve"`, runtime resolution
does not coerce helper inputs into zero nodes first. It reads
`DiscountCurvesNode.key_nodes`, validates generic helper key-node dictionaries,
builds QuantLib rate helpers through `msm_pricing.pricing_engine.curves`, and
bootstraps the curve with `reconstruct_curve_handle(...)`. OIS helper key nodes
require a caller-supplied QuantLib overnight index or resolver callable; the
library does not infer indexes from curve names or connector-specific labels.

The primitive reconstruction API never accepts `CurveBuildingDetails` directly.
The dependency flow is:

```text
CurveBuildingDetails + DiscountCurvesNode.key_nodes
  -> persistence adapter
  -> helper key-node models
  -> QuantLib helper specs
  -> QuantLib RateHelper objects
  -> reconstruct_curve_handle(...)
  -> optional export_curve_observation_nodes(...)
```

## Benchmark z-spread resolution

`benchmark_rate_index_uid` is a persisted instrument field that points to
`IndexTable.uid`. It is not a curve UID and it is not enough to identify a curve.
For z-spread, the runtime resolves the benchmark curve through the market-data
binding graph:

```text
----------------------------------------------+
| instrument.benchmark_rate_index_uid         |
+----------------------+-----------------------+
                       |
                       | selector_key
                       v
PricingMarketDataSetCurveBinding
  market_data_set = requested set
  role_key        = "z_spread_base"
  selector_type   = "index"
  selector_key    = str(benchmark_rate_index_uid)
  quote_side      = requested side or default
  -> curve_uid
  -> CurveTable.unique_identifier
  -> DiscountCurvesNode.curve_identifier
  -> CurveBuildingDetails
  -> ql.YieldTermStructureHandle
```

Missing `z_spread_base` bindings fail the `z_spread` operation with the
benchmark index UID, market-data set, role, and quote side in the error. The
runtime does not swallow that failure and fall back to an unrelated default
curve.

`Bond.z_spread(...)` returns a decimal continuous zero-rate spread. To reuse
that result as a derived runtime curve, use the pricing-engine overlay helper:

```python
from msm_pricing.pricing_engine import apply_z_spread_to_curve

spread = bond.z_spread(
    target_dirty_ccy=target_dirty_ccy,
    market_data_set="eod",
    benchmark_curve_quote_side="mid",
)
spreaded_curve = apply_z_spread_to_curve(benchmark_curve, spread)
```

The overlay helper uses the same continuous/no-frequency convention as
`Bond.z_spread(...)`. It does not mutate persisted `DiscountCurvesNode` rows,
`key_nodes`, or `CurveBuildingDetails`; it wraps a resolved QuantLib curve
handle for the current valuation calculation only.

## Curve scenario resolution

`msm_pricing.scenarios.curves.price_curve_scenario(...)` uses the prepared
valuation context as its runtime graph. The helper prepares a
`PricingValuationContext` once when the caller does not pass one, or validates
that the supplied context matches the `ValuationPosition`. It then reads the
already cached curve bindings, curve rows, curve-building details, observations,
effective observation dates, and base QuantLib handles from that context.

Scenario shocks are keyed by `Curve.unique_identifier`. Non-empty shocks rebuild
transient scenario handles from copied `key_nodes`, then line pricing is
delegated to `msm_pricing.valuation.price_scenario(...)`. Node-built curves are
converted into runtime observation nodes. Helper-built curves keep their
helper-shaped key nodes and delegate reconstruction to
`msm_pricing.pricing_engine.curves`.
The scenario helper does not run a second pricing loop and does not mutate:

- submitted instruments;
- prepared context caches;
- persisted market-data-set bindings;
- persisted `DiscountCurvesNode` observations;
- submitted source key-node dictionaries.

Strict mode is the default. A non-empty shock fails before pricing when the
curve is not resolved by the position, the prepared context is missing a curve
row/build-details/observation/base handle, the observation has no usable
`key_nodes`, a key node has unsupported units or quote type, or placeholder
build details do not declare runtime output convention/unit. Use `strict=False`
only when the caller wants structured diagnostics in
`CurveScenarioResult.errors`.

When a line resolves multiple curve roles but the current instrument only
supports one `reset_curve(...)` override, selection is deterministic. Floating
and swap-style instruments prefer `projection`, then `floating`, then
`discount`, then `z_spread_base`. Fixed-rate instruments prefer
`z_spread_base`, then `discount`, then `projection`, then `floating`. A
non-empty shock on an unselected related curve is not silently dropped in
strict mode.

There are two curve-scenario entry points:

- `price_curve_scenario(...)` is the context-resolved workflow. Use it when
  `msm_pricing` should resolve curve bindings from the prepared valuation
  context and build scenario handles from copied `key_nodes`.
- `price_resolved_curve_scenario(...)` is the caller-resolved workflow. Use it
  when an application or connector already has explicit base and scenario curve
  handles per valuation line.

The resolved workflow is still typed and still delegates pricing through
`price_scenario(...)`:

```python
from collections.abc import Mapping, Sequence
from typing import TypeAlias

from msm_pricing.scenarios.curves import (
    CurveScenario,
    CurveScenarioResult,
    LineCurveResolution,
    price_resolved_curve_scenario,
)
from msm_pricing.valuation import PricingValuationContext, ValuationPosition

LineCurveResolutionInput: TypeAlias = (
    Sequence[LineCurveResolution]
    | Mapping[int, LineCurveResolution | Sequence[LineCurveResolution]]
)


def run_resolved_scenario(
    position: ValuationPosition,
    scenario: CurveScenario,
    resolutions: LineCurveResolutionInput,
    context: PricingValuationContext,
) -> CurveScenarioResult:
    return price_resolved_curve_scenario(
        position,
        scenario,
        line_curve_resolutions=resolutions,
        context=context,
        curve_quote_side="mid",
        strict=True,
    )
```

`LineCurveResolutionInput` can be a flat sequence or a mapping keyed by
`line_index`. Each `LineCurveResolution` carries the line role, selector,
`Curve.unique_identifier`, base handle, and optional scenario handle. A
non-empty shock on the selected curve requires `scenario_handle`; empty shocks
reuse `base_handle`. If `context` is omitted, the helper creates a minimal
instrument-preparation context only. It does not resolve market-data-set
bindings, curve rows, curve observations, or key-node scenario handles. Pass a
prepared `PricingValuationContext` when the instrument needs cached index
conventions, fixings, or other platform-resolved inputs.

This is the migration target for project-local compatibility helpers that
already build curve handles outside the standard context path. Those wrappers
should adapt their local handle-resolution output into `LineCurveResolution`
records and then call `price_resolved_curve_scenario(...)`; connector-specific
curve construction remains outside core `msm_pricing`.

## User Workflow

The fixed-income workflow is:

```text
Issuer/Currency/AssetType
  -> Bond asset row
  -> IndexType row
  -> Index row
  -> IndexConventionDetails row
  -> Curve row
  -> CurveBuildingDetails row
  -> upsert_index_curve_selection(...) row
  -> DiscountCurvesNode observations
  -> FixingRatesNode observations
  -> FloatingRateBond(floating_rate_index_uid=<IndexTable.uid>)
  -> bond.attach_to_asset(asset)
  -> Instrument.load_from_asset(asset)
  -> set_valuation_date(...)
  -> price / analytics / cashflows / carry output
```

See `examples/msm_pricing/bond_pricing_example/` for the full floating-rate bond
example and `examples/msm_pricing/utils/mock_market_data.py` for reusable mock
curve and one-month fixing publishers.

## Related Concepts

- [msm_pricing overview](index.md)
- [Market Data Sets](market_data_sets.md)
- [Instruments](instruments.md)
- [Curves](curves.md)
- [Fixings](fixings.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
