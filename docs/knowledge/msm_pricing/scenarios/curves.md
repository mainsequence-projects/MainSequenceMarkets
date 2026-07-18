# Curve Scenarios

`msm_pricing.scenarios.curves` shocks pricing curves by
`Curve.unique_identifier`. It is the curve-specific runtime layer used directly
by strict curve scenario pricing and indirectly by the broader valuation
workflow.

## Public Entry Points

Use `price_curve_scenario(...)` when `msm_pricing` should resolve curve
bindings from a prepared valuation context and build scenario handles from
copied `key_nodes`:

```python
from msm_pricing.scenarios.curves import (
    CurveBumpSpec,
    CurveScenario,
    price_curve_scenario,
)

result = price_curve_scenario(
    position,
    CurveScenario(
        name="parallel-up-25bp",
        shocks_by_curve_identifier={
            "USD-SOFR-3M-PROJECTION": CurveBumpSpec(parallel_bp=25.0),
        },
    ),
    context=context,
)
```

Use `price_resolved_curve_scenario(...)` when a connector or application
already owns exact base and scenario curve handles per line:

```python
from msm_pricing.scenarios.curves import (
    CurveScenario,
    LineCurveResolution,
    price_resolved_curve_scenario,
)

result = price_resolved_curve_scenario(
    position,
    CurveScenario(name="parallel-up-25bp", shocks_by_curve_identifier={...}),
    line_curve_resolutions=[
        LineCurveResolution(
            line_index=0,
            role_key="projection",
            selector_type="index",
            selector_key=str(index_uid),
            quote_side="mid",
            curve_uid=curve_uid,
            curve_identifier="USD-SOFR-3M-PROJECTION",
            base_handle=base_handle,
            scenario_handle=scenario_handle,
        )
    ],
    context=context,
)
```

Use `prepare_curve_scenario_runtime_overrides(...)` when a higher-level
workflow needs the selected base and scenario curve handles without forcing the
strict `price_scenario(...)` pricing loop. The valuation workflow uses this
entry point.

Use `prepare_resolved_curve_scenario_runtime_overrides(...)` when the caller
has already resolved or constructed `LineCurveResolution` records and only
needs the shared ms-markets preflight, deterministic line-curve selection,
z-spread overlay, and base/scenario handle maps. This is the correct adapter
point for applications that keep local curve-resolution reports but should not
own generic scenario handle selection.

## Shock Identity

Scenario shocks are keyed by `Curve.unique_identifier`, not by backend curve
UID, index UID, role key, quote side, or provider-local curve name. A curve that
is selected by several roles or lines is rebuilt once for the scenario and
reused wherever that same curve identity is resolved.

`CurveBumpSpec` supports:

- `parallel_bp`: a basis-point shift applied to every usable source key-node
  rate or yield;
- `keyrate_bp`: tenor labels such as `"3M"` or positive day counts mapped to
  basis-point shifts;
- `metadata_json`: caller-owned scenario metadata.

The bump helpers operate on copied `key_nodes` dictionaries. They never mutate
the submitted observation, the persisted `DiscountCurvesNode` row, or prepared
valuation context caches.

## Runtime Construction

Non-empty shocks rebuild transient runtime handles from copied key-node
provenance. Node-built curves are converted into runtime observation nodes.
Helper-built curves keep helper-shaped key nodes and delegate reconstruction to
`msm_pricing.pricing_engine.curves`.

OIS helper curves still need a QuantLib overnight index at runtime. Callers can
pass `overnight_index` or `overnight_index_resolver` to
`price_curve_scenario(...)`; the high-level path forwards that resolver into
scenario handle construction.

For bond helper curves, no-op reconstruction is supported, but non-empty yield
shocks on price-quoted bond helpers raise diagnostics until a generic
yield-to-price conversion layer exists with explicit bond conventions.

## Selection And Diagnostics

Floating-rate instruments must expose `reset_curves(...)` so scenario pricing
can pass both projection and discount handles. A floating line that only
supports a single curve override fails instead of selecting projection as a
mono-curve shortcut.

A non-empty shock on an unselected related curve is not silently dropped in
strict mode. Use `strict=False` only when the caller wants structured
diagnostics in `CurveScenarioResult.errors`.

## Z-Spread Overlays

Curve scenarios can apply an already-computed
`observed_z_spread_decimal` from line metadata to runtime handles. That is a
runtime overlay only; it does not mutate persisted curve observations or curve
build details.

When the workflow needs to compute the spread from an observed dirty price,
use [Valuation Scenario Workflow](valuation.md). That layer returns explicit
`ObservedZSpreadOverlay` records and applies the computed spread to runtime
handles without writing back into line metadata.

## Examples

- `examples/msm_pricing/curve_scenario.py`
- `examples/msm_pricing/resolved_curve_scenario.py`
- `examples/msm_pricing/valuation_scenario_workflow.py`
