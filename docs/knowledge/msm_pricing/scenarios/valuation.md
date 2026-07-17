# Valuation Scenario Workflow

`msm_pricing.scenarios.valuation` is the generic orchestration layer for
dashboards, APIs, and services that need base valuation plus scenario valuation
outputs. It returns typed in-memory records, not pandas `DataFrame`s and not
Command Center `TabularFrameResponse` payloads.

## Public Entry Point

Use `run_valuation_scenario_workflow(...)` when a workflow needs base pricing,
one or more scenario runs, partial-success diagnostics, line impacts, optional
analytics and cashflows, carry impacts, and observed dirty-price z-spread
overlays:

```python
from msm_pricing.scenarios.curves import CurveBumpSpec, CurveScenario
from msm_pricing.scenarios.valuation import (
    ValuationScenario,
    run_valuation_scenario_workflow,
)

result = run_valuation_scenario_workflow(
    position,
    ValuationScenario(
        name="parallel-up-25bp",
        curve_scenario=CurveScenario(
            name="parallel-up-25bp",
            shocks_by_curve_identifier={
                "USD-SOFR-3M-PROJECTION": CurveBumpSpec(parallel_bp=25.0),
            },
        ),
    ),
    context=context,
    overnight_index_resolver=resolver,
    carry_days=30,
    strict=False,
)
```

The first implementation supports direct `ValuationScenario.curve_scenario`.
The model is valuation-level so future equity, volatility, credit, commodity,
or FX scenario components can be added as typed sibling inputs without moving
generic workflow orchestration into `scenarios.curves`.

## Workflow Order

The workflow order is:

```text
ValuationPosition
  -> PricingValuationContext
  -> ValuationScenario(curve_scenario=...)
  -> prepare_curve_scenario_runtime_overrides(...)
  -> compute_observed_z_spread_overlays(...)
  -> price_valuation_lines(base)
  -> price_valuation_lines(scenario)
  -> line_impacts(...)
  -> carry_impacts(...)
```

`run_valuation_scenario_workflow(...)` prepares a
`PricingValuationContext` once when the caller does not provide one. When a
context is provided, it validates that the context matches the submitted
`ValuationPosition`.

Curve shock mechanics are delegated to
`msm_pricing.scenarios.curves.prepare_curve_scenario_runtime_overrides(...)`.
The valuation workflow does not duplicate key-node bumping, curve handle
construction, shared-curve caching, OIS overnight-index resolver propagation,
or curve diagnostics.

## Result Models

Core workflow results are typed records:

- `ValuationScenarioWorkflowResult`: base run, scenario runs, diagnostics,
  runtime curve resolutions, and observed z-spread overlays;
- `ValuationRunResult`: one base or scenario pricing run;
- `ValuationLinePrice`: unit price and market value by line;
- `ValuationLineAnalytics`: raw analytics and unit-scaled numeric analytics;
- `ValuationCashflow`: unit-scaled cashflow rows;
- `ValuationLineImpact`: base-versus-scenario market-value deltas;
- `ValuationCarryImpact`: base-versus-scenario carry deltas;
- `ValuationWorkflowDiagnostic`: line, analytics, cashflow, curve, and
  observed-z-spread errors.

Downstream wrappers should convert these records into their required table
shape. Core `msm_pricing` should not know project-local dashboard column names.

## Partial-Success Pricing

`price_valuation_lines(...)` is the line-pricing primitive used by the
workflow. With `strict=False`, failed line price, analytics, or cashflow phases
produce `ValuationWorkflowDiagnostic` records while successful lines continue.
With `strict=True`, the failing phase raises.

Submitted instruments are prepared through `PricingValuationContext`; the
workflow does not mutate caller-owned instrument objects.

## Observed Dirty-Price Z-Spread

Lines can provide dirty-price targets through:

- `metadata_json["observed_dirty_price"]`;
- `metadata_json["observed_dirty_ccy"]`.

The workflow computes `ObservedZSpreadOverlay` records, exposes them on
`ValuationScenarioWorkflowResult.observed_z_spread_overlays`, and applies the
computed decimal spread only to runtime curve handles. It does not write
`observed_z_spread` back into `ValuationLine.metadata_json`, persisted curve
observations, or prepared context caches.

## Downstream Wrapper Boundary

Project wrappers should:

- accept project request parameters;
- construct `ValuationPosition`, `ValuationScenario`, and `CurveScenario`
  inputs;
- pass connector-owned resolver functions such as an overnight-index resolver;
- call `run_valuation_scenario_workflow(...)`;
- format typed outputs into project-specific table or API shapes.

Project wrappers should not:

- build generic scenario curve handles locally;
- duplicate key-node bumping;
- mutate valuation line metadata;
- own generic diagnostics;
- return a pandas-specific shape from core `msm_pricing`.

## Example

Run the offline example:

```bash
python examples/msm_pricing/valuation_scenario_workflow.py
```

It builds a local prepared context, computes an observed dirty-price z-spread
overlay, prices base and shocked curve runs, and prints JSON-ready typed output
without live platform market-data setup.
