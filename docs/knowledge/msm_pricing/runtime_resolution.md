# Runtime Resolution

This page traces how `price()` walks the persisted graph at runtime, from an
instrument payload down to QuantLib objects, and gives the end-to-end ordering a
user follows to build a priceable fixed-income asset.

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

Curve selection must be strict:

- first resolve `PricingMarketDataSetBinding` for the storage source, such as
  `discount_curves -> DiscountCurvesStorage`;
- then resolve `PricingMarketDataSetCurveBinding` for the valuation role and
  selector, such as `projection:index:<index_uid>:mid -> CurveTable.uid`;
- then load `CurveBuildingDetails` for the selected curve;
- if any row is missing, fail with a specific missing-binding or missing-build
  detail error.

This lets `bond.price()` work without silently picking ambiguous market data or
using `Curve.index_uid` as an implicit policy shortcut.

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
  -> PricingMarketDataSetCurveBinding row
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
