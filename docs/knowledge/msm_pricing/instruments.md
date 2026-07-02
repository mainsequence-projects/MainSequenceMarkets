# Instruments

This page covers how priceable instrument payloads attach to assets through the
`AssetCurrentPricingDetailsTable` projection, and how account and portfolio
holdings become transient valuation baskets with `ValuationLine` and
`ValuationPosition`.

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
- The public write path is timestamped: use `Instrument.attach_to_asset(asset)`
  or `msm_pricing.api.add_pricing_details(...)` for one asset. For large
  universes, use `msm_pricing.api.add_many_pricing_details(...)`; it serializes
  many asset/instrument pairs and writes them through chunked bulk upserts
  instead of one MetaTable operation per asset. Both paths write
  `AssetPricingDetailsStorage`.
- `AssetCurrentPricingDetailsTable` is an internal current projection used for
  fast runtime loading. When the caller does not provide
  `pricing_details_date`, the API uses `now()` as the snapshot timestamp and
  updates this current projection. When the caller provides
  `pricing_details_date`, the API upserts that exact timestamped snapshot and
  updates current when no current row exists or when the new date is newer than
  current.
- Batch persistence chunks by caller `batch_size` and sets each compiled
  MetaTable operation's SDK `max_rows` limit to cover the submitted chunk.
  Returned row counts are validated per bulk operation so partial write-returning
  responses fail instead of being treated as complete.
- Application code should not update `AssetCurrentPricingDetailsTable` directly
  as the normal UX. Direct row APIs are low-level infrastructure for the
  no-date current-snapshot path.

The related DataNode stays separate:

```text
AssetCurrentPricingDetailsTable
  grain:   one current row per asset_uid
  purpose: fast load/rebuild of the current priceable instrument

AssetPricingDetail DataNode
  grain:   (time_index, asset_identifier)
  purpose: timestamped pricing metadata and historical pricing-detail records
```

Use the instrument API, not manual row assembly:

```python
from msm.api.assets import Asset
from msm_pricing import Instrument, FloatingRateBond
from msm_pricing.api import add_many_pricing_details, load_instruments_from_assets

asset = Asset.get_by_unique_identifier("example-floating-bond")
bond = FloatingRateBond(
    face_value=100,
    floating_rate_index_uid=index.uid,
    # remaining contract terms omitted
)

bond.attach_to_asset(asset)
loaded = Instrument.load_from_asset(asset)

add_many_pricing_details(
    [
        {"asset": asset, "instrument": instrument}
        for asset, instrument in asset_instrument_pairs
    ],
    batch_size=1000,
)
```

`Instrument.load_from_asset(asset)` reads the current pricing details row,
rebuilds the concrete instrument class stored in `instrument_type`, attaches
private runtime context such as `_asset_uid`, and returns the concrete object.
Typed loaders such as `FloatingRateBond.load_from_asset(asset)` use the same
path but reject mismatched stored instrument types.

For many assets, use the batch loader:

```python
instruments_by_asset_uid = load_instruments_from_assets(assets, batch_size=1000)
```

It reads `AssetCurrentPricingDetailsTable` with chunked `asset_uid IN (...)`
searches, rebuilds concrete instrument classes, validates each instrument
against the corresponding asset, and returns a mapping keyed by `Asset.uid`.

## Account And Portfolio Valuation Inputs

`msm_pricing` does not query account holdings, target positions, or portfolio
weights directly. Those packages own snapshot selection and exposure
normalization. Pricing starts after the source rows have been reduced to asset
rows plus signed units. This boundary is defined in
[ADR 0033](../../ADR/0033-pricing-valuation-position-boundary.md).

Account holdings use `asset_identifier`, `quantity`, and `direction`. The
account workflow should select the holdings snapshot, resolve each
`asset_identifier` to an `Asset` row, then normalize units as
`quantity * direction`:

```python
from msm_pricing.api import load_instruments_from_assets
from msm_pricing.valuation import build_valuation_position

assets = list(assets_by_identifier.values())
instruments_by_asset_uid = load_instruments_from_assets(assets)
valuation_rows = [
    {
        "instrument": instruments_by_asset_uid[asset.uid],
        "units": row["quantity"] * row["direction"],
        "asset_uid": asset.uid,
        "metadata_json": {"source": "account_holding"},
    }
    for row in account_holding_rows
    for asset in [assets_by_identifier[row["asset_identifier"]]]
]
position = build_valuation_position(
    valuation_rows,
    valuation_date=valuation_date,
    market_data_set="eod",
)
```

Portfolio workflows follow the same boundary after they choose the portfolio
composition source and convert weights, notionals, or quantities into concrete
asset-level units:

```python
assets = list(assets_by_uid.values())
instruments_by_asset_uid = load_instruments_from_assets(assets)
valuation_rows = [
    {
        "instrument": instruments_by_asset_uid[row["asset_uid"]],
        "units": row["units"],
        "asset_uid": row["asset_uid"],
        "metadata_json": {"source": "portfolio_weight"},
    }
    for row in normalized_portfolio_rows
]
position = build_valuation_position(
    valuation_rows,
    valuation_date=valuation_date,
    market_data_set="eod",
)
```

`ValuationPosition` has one `market_data_set` for the whole basket. Build
separate baskets when two groups of lines must be valued against different
market-data sets. See [Market Data Sets](market_data_sets.md) for how the
selected set resolves to DataNode reads.

`build_valuation_position(...)` accepts normalized mappings or a pandas
DataFrame with required `instrument` and `units` fields, plus optional
`asset_uid` and `metadata_json`. The valuation date is required and the
market-data set is passed only at the basket level. Rows must not carry their
own `market_data_set`; source-specific selection and asset/instrument loading
belong before this pricing boundary.

Use `PricingValuationContext` for portfolio-style pricing instead of calling
private valuation-position helpers. The context prepares the known instrument
universe once, resolves supported fixed-income market-data rows with set-based
row API operations, stores the immutable input contract in
`PricingValuationContextSpec`, and returns copied/wrapped prepared instruments
so the caller-owned instrument terms are not mutated:

```python
from msm_pricing.valuation import PricingValuationContext

context = PricingValuationContext.prepare_for_position(
    position,
    curve_quote_side="mid",
)

total_market_value = position.price(context=context)
per_line = position.price_breakdown(context=context)

prepared = context.prepare_instrument(position.lines[0].instrument)
assert prepared.instrument is not position.lines[0].instrument
unit_price = prepared.price()
observed_z_spread = prepared.z_spread(target_dirty_ccy)
```

`PreparedInstrument.z_spread(...)` uses the same prepared context injection path
as `price()`: the context supplies the selected market-data set and curve quote
side when the underlying instrument supports those arguments. Callers must pass
`target_dirty_ccy` as a normalized currency dirty price; source-specific quote
parsing, such as dirty price per 100 notional, remains outside the core
valuation context.

For scenario runs, use `msm_pricing.price_scenario(...)` with explicit
line-scoped base and scenario curve handles. The helper prepares separate
copies for override cases, so mutable scenario curve state does not leak into
the caller-owned instruments or the cached base prepared instrument.

The prepared context is intentionally not expandable. Its spec records the
valuation date, market-data set, quote side, valuation-role requirements, and
submitted instrument universe. Calling `prepare_instrument(...)` with an
instrument that was not included in `prepare(...)` or
`prepare_for_position(...)` is rejected; build a new context for a different
universe.

The prepared context caches market-data concept bindings, index rows, index
convention rows, curve bindings, curve rows, curve-building details, curve
observations, fixing observations, QuantLib curve handles, and base QuantLib
indexes for index-referencing instruments. Prepared floating-rate bond pricing
uses that context state rather than re-entering backend row or observation
resolution in the line-pricing hot loop. See
`examples/msm_pricing/pricing_valuation_context.py` for a runnable offline
example that uses the repository's mock flat-forward curve and mock fixing
builders, prepares a mock index-referencing instrument through
`PricingValuationContext`, and demonstrates the copy boundary without requiring
live platform market data.

## Related Concepts

- [msm_pricing overview](index.md)
- [Market Data Sets](market_data_sets.md)
- [Curves](curves.md)
- [Runtime Resolution](runtime_resolution.md)
- [Assets](../msm/assets/index.md)
- [Derivatives](../msm/derivatives/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
