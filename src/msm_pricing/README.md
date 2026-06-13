# `msm_pricing`

`msm_pricing` contains the QuantLib-backed pricing runtime for Main Sequence
Markets. It is the package for priceable instrument definitions, pricing model
helpers, market-data access used by pricing, and DataNode helpers for
pricing-owned curves and index fixings.

The package intentionally uses a separate import root so core `msm` users do
not import or install the QuantLib-backed pricing runtime unless they choose the
pricing extra:

```python
import msm_pricing as pricing
from msm_pricing import FixedRateBond, FloatingRateBond, InterestRateSwap
from msm_pricing.pricing_engine import resolve_quantlib_index, resolve_pricing_curve
```

## Package Layout

```text
src/msm_pricing/
├── api/                 # User-facing pricing persistence workflows
├── data_interface/      # Main Sequence market-data reads for curves/index fixings
├── data_nodes/          # Pricing DataNodes and curve/index-fixing codecs
├── instruments/         # Pydantic wrappers for priceable instruments
├── meta_tables.py       # Pricing MetaTable discovery and registration
├── models/              # SQLAlchemy MetaTable declarations
├── pricing_engine/      # QuantLib curve, index, bond, and swap helpers
├── settings.py
└── utils.py
```

## Current Instrument Surface

The current package exports:

- `Instrument`
- `FixedRateBond`
- `CallableFixedRateBond`
- `AmortizingFixedRateBond`
- `ZeroCouponBond`
- `FloatingRateBond`
- `AmortizingFloatingRateBond`
- `InterestRateSwap`
- `Position`
- `PositionLine`

## Runtime Responsibilities

The pricing runtime expects two explicit handshakes:

1. Market data must be registered and stored in the expected shapes for curves
   and index fixings.
2. Assets that need valuation must carry pricing details that can rebuild the
   instrument terms later.

Instrument payloads contain pricing terms only. Asset identity must live on the
pricing-details relationship, not inside `InstrumentModel`; legacy
`main_sequence_asset_id` payloads are rejected.

Use `msm_pricing.bootstrap.attach_pricing_schemas(...)` to attach the pricing
MetaTable graph. The graph includes core dependencies such as `AssetTable`,
`IndexTypeTable`, and `IndexTable` before pricing extension tables. Runtime
startup resolves registered `MetaTable` and `TimeIndexMetaTable` objects
directly by each model's SQLAlchemy table name.

Curves are pricing-owned reference data, not assets. `CurveTable` owns curve
identity, and `DiscountCurvesNode` lives under `msm_pricing.data_nodes` as a
stamped DataNode keyed by `(time_index, curve_identifier)`. Curve
DataNode configurations use the actual `CurveTable.unique_identifier`; they do
not resolve Main Sequence Constants into curve identity. EOD curve observations
declare daily cadence on `DiscountCurvesStorage.__cadence__`.

Fixings are index facts, not assets and not a separate rate model.
`FixingRatesNode` lives under `msm_pricing.data_nodes` as an
`IndexTimestampedDataNode` helper keyed by `(time_index, index_identifier)`,
where `index_identifier` references `IndexTable.unique_identifier`. Its
daily EOD cadence is declared on `IndexFixingsStorage.__cadence__`, so the
observation interval is first-class `PlatformTimeIndexMetaTable` metadata.
Fixing configurations likewise use actual `IndexTable.unique_identifier` values
and do not resolve Main Sequence Constants into index identity.
Runtime builder callables are attached after DataNode construction with
`set_curve_builder(...)` / `set_fixing_builders(...)` or by subclassing the hook
methods, so builder wiring is not part of the hashed DataNode configuration.

Pricing market-data source selection is concept based. Bootstrap seeds default
bindings for:

```text
PricingMarketDataSet(set_key="default")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
       data_node_uid = DiscountCurvesStorage.get_meta_table_uid()
  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
       data_node_uid = IndexFixingsStorage.get_meta_table_uid()
```

Those UIDs come from attached storage classes, not static namespace helpers.
`storage_table_identifier` is stored only as diagnostic metadata.

Applications can add named market-data sets such as `eod`, `live`, or
`risk_manager` through `msm_pricing.api.PricingMarketDataSet` and
`PricingMarketDataSetBinding`. Each binding stores the backend DataNode storage
table UID used by `APIDataNode.build_from_table_uid(...)`:

```python
from msm_pricing.api import PricingMarketDataSet, PricingMarketDataSetBinding
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_MARKET_DATA_SET_EOD,
)

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

The data interface resolves direct in-memory overrides first and persisted
market-data set bindings second. The final lookup uses
`APIDataNode.build_from_table_uid(...)`.

At pricing time, callers select the source set by key:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

When the argument is omitted, the process default market-data set is used.

User-facing persistence starts from instruments:

```python
from msm_pricing.api import add_many_pricing_details

bond.attach_to_asset(asset)
loaded = pricing.Instrument.load_from_asset(asset)

add_many_pricing_details(
    [
        {"asset": asset, "instrument": instrument}
        for asset, instrument in asset_instrument_pairs
    ],
    batch_size=1000,
)
```

`attach_to_asset(...)` writes a timestamped pricing-details observation. When
`pricing_details_date` is not provided, it uses `now()` and updates the internal
current table for fast loading. If a date is provided, it upserts that
timestamped snapshot and updates current when no current row exists, when the
date is newer than current. The generic loader rebuilds the concrete stored
instrument type from the current projection. Typed loaders such as
`ZeroCouponBond.load_from_asset(asset)`
validate that the attached instrument matches the requested class.

For thousands of assets, use `add_many_pricing_details(...)` rather than
calling `attach_to_asset(...)` in a loop. The batch API serializes instruments
once and persists timestamped/current pricing rows with chunked bulk upserts.
Each compiled MetaTable operation sets an SDK `max_rows` limit large enough for
the submitted chunk, so backend defaults do not silently truncate
`RETURNING` rows; `batch_size` controls how many rows are submitted per bulk
upsert operation.

Pricing registry rows are also exposed through `msm_pricing.api`:

```python
from msm_pricing.api import Curve, IndexConventionDetails
```

`IndexConventionDetails` upserts one convention payload per canonical
`IndexTable.uid`; `Curve` upserts curve identity rows by
`CurveTable.unique_identifier`. These rows are the durable bridge from
instrument index references to curve DataNode observations.

At runtime, pricing code resolves backend index UIDs through
`resolve_quantlib_index(...)` and curve rows through `resolve_pricing_curve(...)`.
Serialized bond and swap payloads must store UUID fields such as
`floating_rate_index_uid` and `float_leg_index_uid`; stale relationship fields
such as `floating_rate_index_name` and `float_leg_index_name` are rejected.
The resolver loads the pricing convention row, selects the curve row, loads
curve/index-fixing data, materializes QuantLib objects, and values the
instrument or position for an explicit valuation date.

See `examples/msm_pricing/bond_pricing_example/` for a complete floating-rate bond
workflow using the public asset, pricing registry, DataNode, attach/load, and
pricing APIs.

## Extending

Add new priceable instruments under `instruments/` and shared QuantLib helpers
under `pricing_engine/`. Keep SQLAlchemy table declarations under `models/`.
Keep storage access in `data_interface/`, and keep pricing DataNode publishers
under `data_nodes/` so instrument classes remain focused on rebuilding terms
and pricing.
