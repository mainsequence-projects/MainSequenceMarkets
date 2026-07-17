# Pricing Scenarios

`msm_pricing.scenarios` contains transient scenario workflows. It does not own
persisted market data, durable positions, connector source parsing, dashboard
tables, or API response formatting.

The documentation mirrors the package layout:

```text
src/msm_pricing/scenarios/
├── curves/      # curve-shock models, key-node bumps, runtime curve handles
└── valuation/   # base/scenario valuation workflow orchestration
```

## Order Of Use

Use the scenario layers in this order:

1. Build or receive a normalized `ValuationPosition`.
2. Prepare a `PricingValuationContext` once when fixed-income curve or fixing
   resolution is needed.
3. Use `msm_pricing.scenarios.curves` when the task is specifically to shock
   resolved curves and delegate to the strict `price_scenario(...)` path.
4. Use `msm_pricing.scenarios.valuation` when the task is a broader dashboard,
   API, or service workflow that needs base valuation, scenario valuation,
   diagnostics, line impacts, cashflows, carry, analytics, and observed
   dirty-price z-spread overlays.
5. Convert typed result records into pandas, Command Center, or project-local
   table shapes outside core `msm_pricing`.

## Package Boundaries

`scenarios.curves` owns:

- `CurveBumpSpec` and `CurveScenario`;
- key-node bumping and tenor handling;
- runtime scenario curve-handle construction;
- caller-resolved line curve handles;
- curve diagnostics and curve-resolution records.

`scenarios.valuation` owns:

- `ValuationScenario`;
- partial-success line pricing;
- base/scenario run orchestration;
- observed dirty-price z-spread overlay records;
- line impacts and carry impacts;
- workflow diagnostics.

`scenarios.valuation` depends on `scenarios.curves` for curve shock mechanics.
The dependency should not run the other way. Curve scenario helpers must stay
usable without importing valuation workflow table or dashboard concerns.

## Related Pages

- [Curve Scenarios](curves.md)
- [Valuation Scenario Workflow](valuation.md)
- [Runtime Resolution](../runtime_resolution.md)
- [Curves](../curves.md)
- [Instruments](../instruments.md)
