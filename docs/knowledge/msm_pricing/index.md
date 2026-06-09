# msm_pricing

`msm_pricing` owns priceable instrument terms, pricing-specific reference data,
curve and fixing observations, and the QuantLib runtime that turns those rows
into valuations. Core `msm` owns canonical assets and canonical indexes;
pricing extends those rows with pricing contracts instead of widening the core
tables.

Install pricing explicitly with `ms-markets[pricing]` and import the runtime
through `msm_pricing`. The core `ms-markets` install does not require QuantLib.

This page is the operational view for pricing persistence: which objects exist,
how they point to each other, and what a user or source publisher must create
before pricing works.

[ADR 0026](../../ADR/0026-explicit-pricing-market-data-sets.md) defines the
implemented pricing market-data set architecture. Pricing no longer stores
runtime source selection as loose `context_key` plus DataNode identifier
strings. It stores first-class market-data set rows and concept bindings keyed
by backend DataNode storage table UID.

## What Pricing Owns

Pricing answers these questions:

- Which instrument payload is attached to this asset right now?
- Which backend index UID does the instrument reference?
- Which index conventions reconstruct a QuantLib index?
- Which curve row should be selected for this valuation role?
- Which curve and fixing observations should be read for the valuation date?
- Which QuantLib objects should be materialized for `price()` and cashflow
  analytics?

Pricing does not own:

- Asset identity. Assets stay in `msm.models.AssetTable`.
- Index identity. Indexes stay in `msm.models.IndexTable`.
- Platform Constant aliases. Constants are not pricing identity.
- Curve-as-asset modeling. Curves are pricing rows, not tradable assets.
- Legacy string relationships such as `floating_rate_index_name`.

## Package Map

```text
msm_pricing/
  api/             row APIs and instrument attach/load bridge helpers
  instruments/     Pydantic priceable instrument contracts
  models/          SQLAlchemy MetaTable declarations owned by pricing
  data_nodes/      pricing DataNodes and storage-facing publishing helpers
  pricing_engine/  QuantLib builders, resolvers, pricers, and analytics
  data_interface/  platform reads for curves and index fixings
  streamlit/       pricing UI form helpers
  utils/           shared date and serialization utilities
```

`msm_pricing.models` must mean pricing-owned SQLAlchemy MetaTables. Runtime
pricing helpers belong in `msm_pricing.pricing_engine`.

## Persisted Graph

The pricing graph has four persistent layers:

1. core assets and indexes from `msm`;
2. pricing MetaTables that extend assets and indexes;
3. pricing DataNodes that publish curve and fixing observations;
4. serialized instrument payloads that reference backend UUIDs.

```text
AssetTable.uid
  -> AssetCurrentPricingDetailsTable.asset_uid
  -> Instrument payload with backend index UID fields

IndexTypeTable.index_type
  -> IndexTable.index_type
  -> IndexConventionDetailsTable.index_uid
  -> CurveTable.index_uid
  -> DiscountCurvesNode(curve_identifier)

IndexTable.unique_identifier
  -> FixingRatesNode(index_identifier, rate)
  -> QuantLib index hydration
```

The complete fixed-income pricing path is:

```text
User query
  -> Asset row
  -> Instrument.load_from_asset(asset)
  -> FloatingRateBond(floating_rate_index_uid=<IndexTable.uid>)
  -> bond.price(market_data_set="default" | "eod" | "live" | ...)

Pricing resolver
  -> IndexTable.uid
  -> IndexConventionDetailsTable.index_uid
  -> CurveTable(index_uid, curve_type="discount")
  -> PricingMarketDataSet(set_key=<selected set>)
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
  -> data_node_uid
  -> APIDataNode.build_from_table_uid(data_node_uid)
  -> DiscountCurvesStorage rows keyed by (time_index, curve_identifier)
```

Index fixings use the same market-data set:

```text
Floating coupon hydration
  -> IndexTable.unique_identifier
  -> PricingMarketDataSet(set_key=<selected set>)
  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
  -> data_node_uid
  -> APIDataNode.build_from_table_uid(data_node_uid)
  -> IndexFixingsStorage rows keyed by (time_index, index_identifier)
```

The DataNode locations used by the pricing engine are pricing market-data
bindings, not instrument metadata and not core `msm` MetaTables. Bindings are
vertical rows under first-class market-data sets so new pricing concepts can be
added without adding one column per future market-data source:

```text
PricingMarketDataSet
  set_key      = default | eod | live | risk_manager
  display_name
  status

PricingMarketDataSetBinding
  market_data_set_uid -> PricingMarketDataSet.uid
  concept_key         = discount_curves | interest_rate_index_fixings | equity_vol_curves
  data_node_uid       = backend DataNode storage table UID
  storage_table_identifier = optional diagnostic copy
```

The important boundary is:

```text
data_node_uid
  authoritative pointer used by pricing runtime

storage_table_identifier
  optional diagnostic value for humans and logs
  not used to resolve pricing market data
```

The built-in pricing constants live in `msm_pricing.settings`:

```python
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_EQUITY_VOL_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_MARKET_DATA_SET_DEFAULT,
    PRICING_MARKET_DATA_SET_EOD,
    PRICING_MARKET_DATA_SET_LIVE,
    PRICING_MARKET_DATA_SET_RISK_MANAGER,
)
```

`interest_rate_index_fixings` is intentionally rate-specific. The current
`FixingRatesNode` stores a decimal `rate` column for SOFR, TIIE, IBOR,
overnight, and similar interest-rate indexes. Future equity index levels,
inflation observations, or volatility inputs should use their own concept keys.

Fresh pricing bootstrap seeds the default bindings:

```text
PricingMarketDataSet(set_key="default")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
       data_node_uid = DiscountCurvesStorage.get_meta_table_uid()

  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
       data_node_uid = IndexFixingsStorage.get_meta_table_uid()
```

Those UIDs are read from the attached backend `TimeIndexMetaTable` objects. They
are not rebuilt from authored names such as `DiscountCurvesTS` or from namespace
helpers. The optional `storage_table_identifier` is diagnostic metadata only.

Deployments can add or replace market-data sets for `eod`, `live`,
`risk_manager`, or other application workflows:

```python
from msm_pricing.bootstrap import attach_pricing_schemas
from msm_pricing.api import PricingMarketDataSet, PricingMarketDataSetBinding
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_MARKET_DATA_SET_EOD,
)

attach_pricing_schemas(seed_default_market_data_bindings=True)

market_data_set = PricingMarketDataSet.upsert(
    set_key=PRICING_MARKET_DATA_SET_EOD,
    display_name="EOD pricing market data",
)
PricingMarketDataSetBinding.upsert(
    market_data_set_uid=market_data_set.uid,
    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    data_node_uid=DiscountCurvesStorage.get_meta_table_uid(),
    storage_table_identifier=DiscountCurvesStorage.get_identifier(),
)
```

Runtime resolution checks direct in-memory UID overrides first, then the
persisted binding row for `(market_data_set_uid, concept_key)`. The final read
always uses `APIDataNode.build_from_table_uid(...)`.

Curve consumers that need the latest available curve snapshot for one curve
identity should use `MSDataInterface.get_latest_discount_curve(...)` instead of
setting a process-wide fallback environment variable:

```python
from msm_pricing.data_interface import MSDataInterface

interface = MSDataInterface()
nodes, effective_date = interface.get_latest_discount_curve(
    curve.unique_identifier,
    market_data_set="eod",
)
```

Instrument pricing chooses the set explicitly when the caller needs more than
one source set in the same process:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

When `market_data_set` is omitted, pricing uses the process-wide default
configuration, whose default selector is `default`.

Registration order matters because pricing MetaTables reference core tables:

```text
AssetTypeTable
AssetTable
IndexTypeTable
IndexTable
IndexConventionDetailsTable
CurveTable
AssetCurrentPricingDetailsTable
PricingMarketDataSetTable
PricingMarketDataSetBindingTable
```

Use the pricing startup helper instead of manually passing table handles. It
uses direct backend lookup keyed by each SQLAlchemy table name, then binds the
returned `MetaTable` or `TimeIndexMetaTable` to the model class.

Run the relevant `msm` migrations before pricing runtime startup:

```python
from msm_pricing.bootstrap import attach_pricing_schemas

attach_pricing_schemas(seed_default_market_data_bindings=True)
```

For an end-to-end example that shows the explicit architecture, inspect
`examples/msm_pricing/bond_pricing_example/main.py`. It attaches the pricing
storage tables, disables automatic default seeding, creates
`PricingMarketDataSet(set_key="default")`, binds discount curves and
interest-rate fixings by storage table UID, and then calls
`loaded_instrument.price(market_data_set=market_data_set.set_key)`.

## Asset To Instrument

`AssetCurrentPricingDetailsTable` is the fast one-row-per-asset table used by
`Instrument.load_from_asset(asset)`. It stores the current serialized
instrument payload for the asset.

```text
+-----------------------------+        one-to-one extension     +-----------------------------+
| AssetTable                  |-------------------------------->| AssetCurrentPricingDetails  |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | instrument_type             |
| asset_type = bond           |                                 | instrument_dump             |
+-----------------------------+                                 | pricing_details_date        |
                                                                | serialization_format        |
                                                                | pricing_package_version     |
                                                                | source                      |
                                                                | metadata                    |
                                                                +-----------------------------+
```

Important rules:

- `asset_uid` is the only primary key and a foreign key to `AssetTable.uid`
  with cascade delete.
- The serialized instrument payload is identity-free. It does not carry
  `asset_uid`, `uid`, or the removed `main_sequence_asset_id`.
- Asset linkage is owned by `AssetCurrentPricingDetailsTable.asset_uid`, not by
  `InstrumentModel`.
- The table stores current terms. Historical pricing-detail observations belong
  to the `AssetPricingDetail` DataNode.
- `AssetCurrentPricingDetailsTable` is not a view of
  `AssetPricingDetailsStorage`, and `AssetPricingDetailsStorage` is not the
  history table automatically maintained by current-detail upserts.
  `Instrument.attach_to_asset(asset)` writes the current table directly through
  `AssetCurrentPricingDetails.upsert(...)`; it does not publish an
  `AssetPricingDetail` DataNode row. Therefore a valid environment can have
  current pricing details for assets while the `AssetPricingDetail` DataNode is
  empty.

The related DataNode stays separate:

```text
AssetCurrentPricingDetailsTable
  grain:   one current row per asset_uid
  purpose: fast load/rebuild of the current priceable instrument

AssetPricingDetail DataNode
  grain:   (time_index, asset_identifier)
  purpose: timestamped pricing metadata or historical pricing-detail records
```

Use the instrument API, not manual row assembly:

```python
from msm.api.assets import Asset
from msm_pricing import Instrument, FloatingRateBond

asset = Asset.get_by_unique_identifier("example-floating-bond")
bond = FloatingRateBond(
    face_value=100,
    floating_rate_index_uid=index.uid,
    # remaining contract terms omitted
)

bond.attach_to_asset(asset)
loaded = Instrument.load_from_asset(asset)
```

`Instrument.load_from_asset(asset)` reads the current pricing details row,
rebuilds the concrete instrument class stored in `instrument_type`, attaches
private runtime context such as `_asset_uid`, and returns the concrete object.
Typed loaders such as `FloatingRateBond.load_from_asset(asset)` use the same
path but reject mismatched stored instrument types.

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
`unique_identifier`. Its `index_uid` points to
`IndexConventionDetailsTable.index_uid`, not directly to an unqualified string.
That makes curve identity dependent on an index that has pricing conventions.

```text
+-------------------------------+        one-to-many curves       +-----------------------------+
| IndexConventionDetails        |-------------------------------->| CurveTable                  |
|-------------------------------|        index_uid FK target      |-----------------------------|
| index_uid              PK/FK  |                                 | uid                  PK     |
| index_family                  |                                 | unique_identifier    unique |
| convention_dump               |                                 | display_name                |
| serialization_format          |                                 | curve_type                  |
| source                        |                                 | index_uid            FK     |
| metadata                      |                                 | interpolation_method        |
+-------------------------------+                                 | compounding                 |
                                                                  | source                      |
                                                                  | metadata                    |
                                                                  +-----------------------------+
```

Curve identity rules:

- `CurveTable.uid` is the canonical row identity for MetaTable operations.
- `CurveTable.unique_identifier` is the stable curve row key. Curve DataNode
  storage publishes that value in the `curve_identifier` column.
- `CurveTable.index_uid` targets `IndexConventionDetailsTable.index_uid`.
- Do not add day counter, currency, calendar, tenor, or fixing rules to
  `CurveTable`; those belong to `IndexConventionDetailsTable`.
- Do not make `(index_uid, curve_type)` unique. Different sources, providers,
  or scenarios may publish multiple curves for the same index and role.

```python
from msm_pricing.api import Curve

curve = Curve.upsert(
    unique_identifier="USD-SOFR-3M-DISCOUNT",
    display_name="USD SOFR 3M Discount Curve",
    curve_type="discount",
    index_uid=index.uid,
    interpolation_method="log_linear_discount",
    compounding="compounded_annual",
    source="example",
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
| index_uid            FK     |                                  +-----------------------------+
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

## Index Fixings

Fixings are observed facts about an index. They are not assets and they are not
a separate `Rate` model.

`FixingRatesNode` extends `IndexTimestampedDataNode`, so rows are keyed by
`(time_index, index_identifier)`, where `index_identifier` is
`IndexTable.unique_identifier`.

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| IndexTable                  |<--------------------------------| FixingRatesNode             |
|-----------------------------|        index_identifier          |-----------------------------|
| uid                  PK     |                                  | time_index                  |
| unique_identifier    unique |                                  | index_identifier            |
| index_type                  |                                  | rate                        |
+-----------------------------+                                  +-----------------------------+
```

The fixing DataNode contract is:

```text
FixingRatesNode
  index:   (time_index, index_identifier)
  cadence: 1d
  columns: rate
  FK:      index_identifier -> IndexTable.unique_identifier
```

The EOD pricing storage tables declare `__cadence__ = "1d"` on the
`PlatformTimeIndexMetaTable` storage class. Cadence is first-class
time-indexed table metadata and participates in SDK storage identity, so it
does not belong on `IndexFixingConfiguration`.

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
               | select curve by index_uid + curve_type/source
               v
+-----------------------------+
| CurveTable                  |
|-----------------------------|
| unique_identifier           |
| curve_type                  |
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

Default curve selection must be strict:

- if exactly one curve row matches `(index_uid, curve_type)` for the pricing
  role, use it;
- if multiple rows match, require a source, curve UID, or valuation-context
  selector;
- if no row matches, fail with a missing-curve error.

This lets `bond.price()` work without silently picking ambiguous market data.

## User Workflow

The fixed-income workflow is:

```text
Issuer/Currency/AssetType
  -> Bond asset row
  -> IndexType row
  -> Index row
  -> IndexConventionDetails row
  -> Curve row
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

## Rejected Patterns

Do not reintroduce these patterns:

- `benchmark_rate_index_name`, `floating_rate_index_name`, or
  `float_leg_index_name` in serialized instruments;
- `main_sequence_asset_id` in instrument payloads;
- curve rows stored as assets;
- Main Sequence Constant names as index or curve identity;
- a persisted `IndexSpec` registry with `curve_uid`;
- source-specific builder names inside hashed DataNode configuration.

The old `IndexSpec` shortcut bundled conventions and curve identity in memory.
The persistent contract is now explicit:
`IndexConventionDetailsTable` plus `CurveTable`, with QuantLib construction in
`msm_pricing.pricing_engine`.

## Related Concepts

- [Assets](../msm/assets/index.md)
- [Derivatives](../msm/derivatives/index.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
