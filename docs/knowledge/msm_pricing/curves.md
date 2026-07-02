# Curves

This page covers the pricing concepts that reconstruct discounting and
projection curves: index conventions (`IndexConventionDetailsTable`) for
QuantLib index/fixing mechanics, curve rows (`CurveTable`), curve build details
(`CurveBuildingDetailsTable`), market-data-set curve bindings, and timestamped
curve observations (`DiscountCurvesNode`).

## Index Conventions

Instruments reference canonical indexes by backend UUID fields such as
`floating_rate_index_uid`, `benchmark_rate_index_uid`, or `float_leg_index_uid`.
They do not store string names.

`IndexTable` is core market reference data. For fixed income, first register
the `interest_rate` type through `IndexType`, then create the index row:

```python
from msm.api.indices import Index, IndexType
from msm.constants import (
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)

IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())
index = Index.upsert(
    unique_identifier="USD-SOFR-3M",
    index_type=INDEX_TYPE_INTEREST_RATE,
    display_name="USD SOFR 3M",
    provider="example",
)
```

Pricing-specific index mechanics live in `IndexConventionDetailsTable`:

```text
+-----------------------------+        one-to-one extension     +-------------------------------+
| IndexTable                  |-------------------------------->| IndexConventionDetails        |
|-----------------------------|        index_uid PK/FK          |-------------------------------|
| uid                  PK     |                                 | index_uid              PK/FK  |
| unique_identifier    unique |                                 | index_family                  |
| index_type                  |                                 | convention_dump               |
| display_name                |                                 | serialization_format          |
| provider                    |                                 | source                        |
| metadata                    |                                 | metadata                      |
+-----------------------------+                                 +-------------------------------+
```

`IndexConventionDetailsTable` stores index reconstruction mechanics:

- index family, such as `ibor` or `overnight`;
- currency code;
- tenor or period;
- fixing calendar;
- day counter;
- settlement days;
- business-day convention;
- end-of-month behavior;
- optional fixing identity override.

It does not store curve selection and it does not belong in core `msm.models`.

```python
from msm_pricing.api import IndexConventionDetails

IndexConventionDetails.upsert(
    index_uid=index.uid,
    index_family="ibor",
    convention_dump={
        "currency_code": "USD",
        "day_counter_code": "Actual360",
        "fixing_calendar_code": "US",
        "period": "3M",
        "settlement_days": 2,
        "business_day_convention": "ModifiedFollowing",
        "end_of_month": False,
        "fixings_unique_identifier": index.unique_identifier,
    },
    source="example",
)
```

## Curves

Curves are pricing concepts. They are not assets and do not reference
`AssetTable`.

`CurveTable` is a pricing-owned MetaTable with its own `uid` and
`unique_identifier`. It is the curve registry. It does not need to belong to an
index and it has no index ownership field. Runtime selection uses explicit
market-data-set curve bindings.

```text
+-----------------------------+        build spec keyed by        +-----------------------------+
| CurveTable                  |<--------------------------------| CurveBuildingDetailsTable   |
|-----------------------------|        curve_uid                |-----------------------------|
| uid                  PK     |                                 | curve_uid            PK/FK  |
| unique_identifier    unique |                                 | builder_type                |
| display_name                |                                 | quote_convention            |
| curve_type                  |                                 | day_counter_code            |
| currency_code               |                                 | calendar_code               |
| quote_side                  |                                 | interpolation_method        |
| source                      |                                 | compounding                 |
| status                      |                                 | extrapolation_policy        |
| metadata                    |                                 | metadata                    |
+-----------------------------+                                 +-----------------------------+
```

Curve identity rules:

- `CurveTable.uid` is the canonical row identity for MetaTable operations.
- `CurveTable.unique_identifier` is the stable curve row key. Curve DataNode
  storage publishes that value in the `curve_identifier` column.
- `CurveBuildingDetailsTable.curve_uid` stores how observations are turned into
  a QuantLib term structure.
- `PricingMarketDataSetCurveBindingTable` stores valuation-policy selection:
  `market_data_set_uid + role_key + selector_type + selector_key + quote_side`
  resolves to `curve_uid`.
- `curve_uid` is not unique in `PricingMarketDataSetCurveBindingTable`. A curve
  can be selected by many market-data-set roles, selector types, index UIDs,
  quote sides, or source sets. The curve row is the target of selection, not the
  owner of the selector.
- `IndexConventionDetailsTable` is only for rebuilding QuantLib indexes and
  fixings. It is not the source of truth for curve construction.
- Do not encode curve selection as an index relationship. Market-data sets may
  choose different bid/mid/offer, source, scenario, discount, projection,
  spread, basis, or future volatility curves.

### Native curve construction methods

Runtime curve construction honors `CurveBuildingDetails.interpolation_method`;
it does not silently coerce every curve into log-linear discount space.
Supported methods are intentionally limited to non-deprecated QuantLib
constructors:

```text
log_linear_discount -> ql.DiscountCurve
log_cubic_discount  -> ql.LogCubicDiscountCurve
linear_zero         -> ql.ZeroCurve with ql.Linear()
cubic_zero          -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
natural_cubic_zero  -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
monotone_cubic_zero -> ql.MonotonicCubicZeroCurve with ql.MonotonicCubic()
linear_forward      -> ql.LinearForwardCurve, only for forward_rate quotes
```

Zero-rate discount-space methods convert stored zero rates into discount
factors with `ql.InterestRate(...).discountFactor(...)`. Zero-space methods
pass zero rates to the QuantLib zero-curve constructor with the declared
compounding and frequency. `rate_unit` parsing is the only local scaling step.

Deprecated QuantLib methods are rejected instead of aliased. Do not persist
`log_linear_zero`, `LogLinearZeroCurve`, `monotonic_log_cubic_discount`, or
`MonotonicLogCubicDiscountCurve` as curve build methods.

```python
from msm_pricing.api import Curve, CurveBuildingDetails, PricingMarketDataSetCurveBinding

curve = Curve.upsert(
    unique_identifier="USD-SOFR-3M-PROJECTION",
    display_name="USD SOFR 3M Projection Curve",
    curve_type="projection",
    currency_code="USD",
    quote_side="mid",
    source="example",
)
CurveBuildingDetails.upsert(
    curve_uid=curve.uid,
    builder_type="zero_rate_curve",
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter_code="Actual360",
    calendar_code="TARGET",
    interpolation_method="log_linear_discount",
    compounding="simple",
    extrapolation_policy="enabled",
)
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    index_uid=index.uid,
    quote_side="mid",
    curve_uid=curve.uid,
)
```

For benchmark z-spread analytics, bind the benchmark index UID with the
`z_spread_base` role. The curve row may still have `curve_type="discount"` or
another physical curve type; the role describes why the curve is selected.

```python
benchmark_curve = Curve.upsert(
    unique_identifier="USD-SOFR-ZSPREAD-BASE",
    display_name="USD SOFR Z-Spread Base Curve",
    curve_type="discount",
    currency_code="USD",
    source="example",
)
CurveBuildingDetails.upsert(
    curve_uid=benchmark_curve.uid,
    builder_type="zero_rate_curve",
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter_code="Actual360",
    calendar_code="TARGET",
    interpolation_method="log_linear_discount",
    compounding="simple",
    extrapolation_policy="enabled",
)
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="z_spread_base",
    index_uid=benchmark_index.uid,
    quote_side=None,
    curve_uid=benchmark_curve.uid,
)
```

The instrument then stores only `benchmark_rate_index_uid=benchmark_index.uid`.
At runtime, `z_spread(...)` resolves the curve through the index curve
selection above. The helper writes `selector_type="index"` and
`selector_key=str(benchmark_index.uid)` into the generic binding table
internally; callers should not pass those selector fields in normal
index-based workflows.

When an observed z-spread should be applied back to a curve handle for scenario
or line valuation, keep that as derived runtime state:

```python
from msm_pricing.pricing_engine import apply_z_spread_to_curve

spreaded_curve = apply_z_spread_to_curve(base_curve_handle, z_spread_decimal)
```

The helper expects the decimal spread returned by `Bond.z_spread(...)`, quoted
as a continuous zero-rate spread. It does not change the persisted curve nodes,
`key_nodes`, `CurveTable`, or `CurveBuildingDetails`.

## Curve Observations

`DiscountCurvesNode` publishes timestamped curve observations. Its storage key
is `CurveTable.unique_identifier`, exposed on the DataNode row as
`curve_identifier`.

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| CurveTable                  |<--------------------------------| DiscountCurvesNode          |
|-----------------------------|        curve_identifier          |-----------------------------|
| uid                  PK     |                                  | time_index                  |
| unique_identifier    unique |                                  | curve_identifier            |
| curve_type                  |                                  | curve                       |
| currency_code               |                                  | key_nodes                   |
|                             |                                  | metadata_json               |
|                             |                                  +-----------------------------+
+-----------------------------+
```

The curve DataNode contract is:

```text
DiscountCurvesNode
  index:   (time_index, curve_identifier)
  cadence: 1d
  columns: curve, key_nodes, metadata_json
  FK:      curve_identifier -> CurveTable.unique_identifier
```

`curve` is required. It remains the serialized compressed pricing payload
consumed by runtime valuation. It stores the constructed curve nodes keyed by
days to maturity; the quote meaning comes from
`CurveBuildingDetails.quote_convention`, `rate_unit`, `compounding`, and the
related build fields. Do not normalize curve points into a different row grain
without a separate decision.

`key_nodes` records the input quotes used to build that specific curve
observation. It is row-level construction provenance, not another convention
source. Publishers pass producer-owned JSON that satisfies the base contract
below; the DataNode compresses that JSON into the storage column, and read/API
helpers return it decompressed. `msm_pricing.data_nodes.CurveKeyNode` is the
recommended helper when the standard fields fit the source:

```json
[
  {
    "maturity_date": "2031-05-27",
    "asset_identifier": "MXN_BONO_2031",
    "instrument_type": "fixed_rate_bond",
    "quote": 99.25,
    "quote_type": "clean_price",
    "quote_unit": "price_per_100",
    "quote_side": "mid"
  },
  {
    "maturity_date": "2027-05-27",
    "instrument_type": "direct_zero_rate",
    "quote": 0.105,
    "quote_type": "zero_rate",
    "quote_unit": "decimal",
    "quote_side": "mid",
    "yield": 0.105
  }
]
```

Rules:

- Publisher `key_nodes` values must be JSON object/list provenance with
  JSON-serializable nested values. They are stored as compressed text and
  returned by helpers as decompressed JSON.
- The shared storage layer does not enforce one fixed per-node financial schema
  because mixed curves may combine bonds, zero-coupon instruments, swaps,
  deposits, direct zero rates, and source-specific payloads.
- Prefer the standard fields `maturity_date`, `asset_identifier`,
  `instrument_type`, `quote`, `quote_type`, `quote_unit`, and `quote_side` when
  they fit the source. Discount-curve producers that think in yields may also
  include the optional `yield` field.
- Source publishers that need more structure should encode that structure in
  their own `CurveKeyNode`-compatible extensions or enforce it through
  `normalize_key_nodes(...)` / `set_key_nodes_validator(...)`.
- `quote_type` and `quote_unit` describe the raw source input for that key node.
  `CurveBuildingDetails` still describes how the final stored `curve` is built
  and interpreted by pricing.

When a producer needs stricter source-specific validation, extend the DataNode
validator instead of tightening the shared storage contract. The base
`DiscountCurvesNode` calls `normalize_key_nodes(...)` for each row after
storage-level JSON normalization. Subclass it for source-owned rules:

```python
from msm_pricing.data_nodes import CurveKeyNode, DiscountCurvesNode


class SourceDiscountCurvesNode(DiscountCurvesNode):
    def normalize_key_nodes(self, value, *, row, curve_identifier):
        nodes = super().normalize_key_nodes(
            value,
            row=row,
            curve_identifier=curve_identifier,
        )
        return [
            CurveKeyNode.model_validate(node).model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            for node in nodes
        ]
```

For runtime composition, attach a callable with
`node.set_key_nodes_validator(...)`. The callable receives the normalized
`value`, the full row, and the `curve_identifier`, and must return JSON
object/list provenance. Do not put validator callables in `CurveConfig`; they
are execution behavior, not hashed dataset identity.

A `DiscountCurvesNode` publisher passes the values as ordinary DataFrame
columns. Keep `key_nodes` beside `curve`; do not nest it inside the compressed
pricing payload and do not precompress it in the publisher:

```python
return pd.DataFrame(
    [
        {
            "time_index": valuation_timestamp,
            "curve_identifier": curve.unique_identifier,
            "curve": {
                30: 0.0500,
                90: 0.0508,
                180: 0.0512,
            },
            "key_nodes": [
                {
                    "maturity_date": "2026-06-26",
                    "quote": 0.0500,
                    "quote_type": "zero_rate",
                    "quote_unit": "decimal",
                    "yield": 0.0500,
                },
                {
                    "maturity_date": "2026-08-25",
                    "asset_identifier": "USD_SOFR_SWAP_3M",
                    "quote": 0.0508,
                    "quote_type": "par_rate",
                    "quote_unit": "decimal",
                },
            ],
            "metadata_json": {"source_snapshot": "example-2026-05-27"},
        }
    ]
)
```

`metadata_json` stores optional row diagnostics such as provider snapshot IDs,
quality flags, workflow labels, or raw-source checksums. It should not be used
to override the pricing interpretation of `curve` or `key_nodes`.

Source publishers should subclass `DiscountCurvesNode` or inject runtime curve
builder callables. The builder is execution wiring; it is not persisted dataset
identity.

## Related Concepts

- [msm_pricing overview](index.md)
- [Market Data Sets](market_data_sets.md)
- [Fixings](fixings.md)
- [Runtime Resolution](runtime_resolution.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
