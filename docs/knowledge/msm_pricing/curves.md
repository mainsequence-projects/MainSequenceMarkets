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
index. The legacy nullable `index_uid` field may still exist on old rows, but
new runtime selection uses explicit market-data-set curve bindings.

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
- `IndexConventionDetailsTable` is only for rebuilding QuantLib indexes and
  fixings. It is not the source of truth for curve construction.
- Do not make `(index_uid, curve_type)` unique. `index_uid` is legacy metadata,
  and market-data sets may choose different bid/mid/offer, source, scenario,
  discount, projection, spread, basis, or future volatility curves.

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
PricingMarketDataSetCurveBinding.upsert(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    selector_type="index",
    selector_key=str(index.uid),
    quote_side="mid",
    curve_uid=curve.uid,
)
```

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
| currency_code               |                                  +-----------------------------+
+-----------------------------+
```

The curve DataNode contract is:

```text
DiscountCurvesNode
  index:   (time_index, curve_identifier)
  cadence: 1d
  columns: curve
  FK:      curve_identifier -> CurveTable.unique_identifier
```

`curve` remains a serialized compressed curve payload. Do not normalize curve
points into a different row grain without a separate decision.

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
