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
