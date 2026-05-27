# Pricing

The pricing concept owns instrument valuation. It contains priceable instrument
terms, QuantLib helpers, curve and fixing access, and persistence utilities
needed to turn stored market data into runtime valuation objects.

Pricing is not part of the core `msm` import package. Install it explicitly with
`ms-markets[pricing]` and import it through `msm_pricing`. The core
`ms-markets` install does not require QuantLib.

See `examples/pricing/import_pricing_runtime.py` for the minimal optional
pricing import example.

## Scope

Pricing answers these questions:

- Which instrument terms are needed to rebuild a bond, swap, or position?
- Which curve and fixing data should be loaded for a valuation date?
- Which index UID is authoritative at runtime?
- Which QuantLib objects should be materialized for valuation?
- Which pricing details must be attached to assets for later reconstruction?

## Primary Modules

- `msm_pricing.api`: user-facing pricing persistence helpers for attaching and
  loading instruments from assets, index convention details, and curve identity
  rows.
- `msm_pricing.instruments`: Pydantic wrappers for priceable instruments and
  positions.
- `msm_pricing.data_nodes`: pricing-owned DataNodes and pricing helpers such as
  `AssetPricingDetail`, `DiscountCurvesNode`, and `FixingRatesNode`.
- `msm_pricing.meta_tables`: pricing MetaTable model discovery and registration
  helpers.
- `msm_pricing.models`: SQLAlchemy MetaTable declarations owned by pricing.
- `msm_pricing.pricing_engine`: QuantLib curve, index, bond, and swap helper
  functions.
- `msm_pricing.data_interface`: Main Sequence data reads for curves and index
  fixings.
- `msm_pricing.streamlit`: form helpers for pricing UIs.
- `msm_pricing.settings` and `msm_pricing.utils`: runtime settings and shared
  date conversion utilities.

## Key Contracts

Pricing needs two explicit handshakes:

1. Market data must be registered and stored in the shapes expected by pricing.
2. Assets that need valuation must carry pricing details that rebuild instrument
   terms.

Priceable instrument payloads are identity-free. They describe only the terms
needed to rebuild the pricing object. Asset identity is stored by the
pricing-detail relationship, for example
`AssetCurrentPricingDetailsTable.asset_uid`, and must not be duplicated inside
`InstrumentModel` payloads. See
`examples/pricing/instrument_identity_boundary.py` for a minimal example.

Pricing MetaTables should be registered through
`msm_pricing.meta_tables.register_pricing_meta_tables(...)`. The helper uses the
pricing dependency graph, registering core dependencies such as `AssetTable` and
`IndexTable` before pricing extension tables such as
`IndexConventionDetailsTable`, `CurveTable`, and
`AssetCurrentPricingDetailsTable`.

The typed row APIs for the pricing registry live under `msm_pricing.api`:

- `IndexConventionDetails` stores one pricing convention row per
  `IndexTable.uid` and upserts by `index_uid`.
- `Curve` stores pricing-owned curve identity rows and upserts by
  `CurveTable.unique_identifier`.

Use these APIs to create the persistent pricing graph before publishing curve
observations or loading instruments that reference index UIDs. See
`examples/pricing/pricing_registry_rows.py` for the minimal index convention and
curve identity workflow.

Bond and swap instruments store canonical backend index UUIDs in serialized
payloads, for example `benchmark_rate_index_uid`,
`floating_rate_index_uid`, and `float_leg_index_uid`. They do not store mutable
index relationship names. Payloads containing stale fields such as
`benchmark_rate_index_name`, `floating_rate_index_name`, or
`float_leg_index_name` are rejected.

Curves are pricing concepts, not assets. `CurveTable` owns curve identity and
`DiscountCurvesNode` stores timestamped curve observations keyed by
`(time_index, curve_unique_identifier)` with a source-table foreign key to
`CurveTable.unique_identifier`. Curve DataNode configurations use the actual
`CurveTable.unique_identifier`; Main Sequence Constants are not used as a
second identity layer.

Fixings are index facts. `FixingRatesNode` is a pricing helper that extends
`IndexTimestampedDataNode` and stores timestamped fixing observations keyed by
`(time_index, unique_identifier)`, where `unique_identifier` is an
`IndexTable.unique_identifier`. Its configuration carries a hashable
`frequency` field, so daily, intraday, weekly, or other supported fixing
frequencies are distinct DataNode identities. The node does not define a
separate `Rate` model and does not treat reference rates as assets.
Fixing configurations likewise use actual `IndexTable.unique_identifier` values
and do not resolve Main Sequence Constants into index identity.

Curve and fixing builder functions are runtime execution wiring. Do not put
builder identifiers or callables into hashed DataNode configuration. Source
publishers should call `set_curve_builder(...)`, `set_fixing_builders(...)`, or
subclass the DataNode hook methods while keeping persisted identity in
`CurveTable` and `IndexTable`.

The intended user API is class-owned by instruments:

```python
from msm.api.assets import Asset
from msm_pricing import Instrument, ZeroCouponBond

asset = Asset.get_by_unique_identifier("example-bond")
bond = ZeroCouponBond(...)

bond.attach_to_asset(asset)
loaded = Instrument.load_from_asset(asset)
```

`Instrument.load_from_asset(asset)` is a generic dispatcher: it reads the current
pricing details row, rebuilds the stored concrete instrument type, attaches
private runtime asset context, and returns the concrete instance. Typed loaders
such as `ZeroCouponBond.load_from_asset(asset)` use the same path but reject
mismatched stored instrument types.

The runtime path resolves the index UID through
`msm_pricing.pricing_engine.resolve_quantlib_index(...)`. That resolver loads
`IndexConventionDetails`, selects a `Curve` row through the strict
`resolve_pricing_curve(...)` path, reads curve observations by
`CurveTable.unique_identifier`, hydrates index fixings by
`IndexTable.unique_identifier`, materializes QuantLib objects, sets an explicit
valuation date, and prices the instrument or position.

## Extension Notes

Add new instruments under `msm_pricing.instruments`. Add reusable QuantLib
helpers under `msm_pricing.pricing_engine`. Add SQLAlchemy pricing table
declarations under `msm_pricing.models`. Add storage-facing pricing data reads
under `msm_pricing.data_interface`. Add pricing-specific DataNodes under
`msm_pricing.data_nodes`. Source-specific publishers should inject runtime
builder callables or subclass the relevant DataNode hook methods while keeping
curve and index identity in the MetaTables.

## Related Concepts

- [Assets](../assets/index.md)
- [Portfolios](../portfolios/index.md)
- [Client](../client/index.md)
