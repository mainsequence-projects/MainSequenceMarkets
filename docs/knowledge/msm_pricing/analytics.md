# Pricing Analytics

`msm_pricing.analytics` contains pure-data analytics helpers that sit outside
the pricing runtime. These helpers operate on caller-supplied pandas or numpy
data and do not resolve assets, portfolios, curves, vendors, DataNodes, or
pricing contexts.

Generic spread primitives are owned by core Index analytics. Pricing retains a
compatibility namespace and pricing-specific specialization:

```text
src/msm_pricing/analytics/__init__.py
src/msm_pricing/analytics/spreads/__init__.py
src/msm/analytics/indices/spreads.py
src/msm_pricing/analytics/spreads/base.py  # compatibility delegates
src/msm_pricing/analytics/spreads/fixed_income.py
```

Use this namespace when the workflow already has marks, spreads, hedge ratios,
or leg-level metrics in memory. Use `msm_pricing.pricing_engine` for QuantLib
pricing mechanics and `msm_pricing.scenarios.curves` for runtime curve shocks.

## Spread Namespace

The public spread namespace is:

```python
from msm_pricing.analytics.spreads import (
    build_spread_series,
    fixed_income_spread_metrics,
    ornstein_uhlenbeck_forecast_cone,
    spread_zscore_matrix,
)
```

`msm.analytics.indices.spreads` owns the cross-asset primitives; the pricing
`base.py` path re-exports the same objects for compatibility:

- aligned spread construction from arrays or pandas Series;
- stable pair history frames with `leg_a`, `leg_b`, and `spread` columns;
- latest and rolling z-scores;
- multi-spread z-score matrices;
- pair metrics such as latest spread, mean, standard deviation, z-score, and
  estimated half-life;
- generic OLS hedge-ratio estimation from price levels or return series;
- deterministic Ornstein-Uhlenbeck-style forecast cones for mean-reverting
  spread histories.

These helpers do not know whether a spread is a bond spread, equity pair,
index spread, commodity calendar spread, option volatility spread, or another
relative-value mark.

## Fixed-Income Specialization

`fixed_income.py` is the first asset-class specialization. It adds fixed-income
interpretation on top of the cross-asset primitives:

- DV01-neutral hedge-ratio calculation;
- leg-level DV01, carry, roll-down, downside, yield, and z-spread fields;
- combined spread metrics where the hedge leg is subtracted from the base leg;
- net DV01, carry, roll-down, and downside after applying the hedge ratio.

The fixed-income module still does not read curves, accounts, portfolios, or
pricing details. Callers should price instruments, resolve curves, and compute
leg-level analytics elsewhere, then pass the resulting marks and metrics into
the analytics helper.

```python
from msm_pricing.analytics.spreads import fixed_income_spread_metrics

metrics = fixed_income_spread_metrics(
    base_values=asset_bond_marks,
    hedge_values=benchmark_bond_marks,
    base_dv01=100_000.0,
    hedge_dv01=80_000.0,
    base_carry=12_500.0,
    hedge_carry=8_000.0,
)
```

The default hedge ratio is `base_dv01 / hedge_dv01`, matching the base spread
formula `base - hedge_ratio * hedge`.

## Extension Ownership

Generic index calculation, units, selectors, coefficient resolution, and
published histories belong under `msm.analytics.indices`. Add a pricing sibling
only when its meaning depends on pricing-domain inputs or interpretation:

```text
src/msm_pricing/analytics/spreads/equity.py
src/msm_pricing/analytics/spreads/options.py
```

Option spread analytics should stay option-centric when possible. A commodity
option spread belongs in an option module if the required inputs are option
prices, implied volatilities, deltas, expiries, and strikes. A commodity module
should own only commodity-specific calendar, roll, or contract semantics.

## Optional Dependency Boundary

The implemented base and fixed-income helpers use the existing runtime
`numpy` and `pandas` dependencies. The `analytics` and `pricing-analytics`
extras are reserved for dependency-heavy analytics that may be added later.

Do not add `scipy`, `arch`, or similar packages to the core `pricing` extra
for these helpers. A dependency-heavy function should call
`require_optional_dependency(...)` before importing its package and should fail
with a clear message when the optional dependency is missing.

## Example

Run the offline example without platform setup:

```bash
python examples/msm_pricing/fixed_income_spread_analytics.py
```

It builds synthetic base and hedge marks, computes a DV01-neutral fixed-income
spread, produces a spread z-score matrix, and builds a small forecast cone from
the resulting spread history.
