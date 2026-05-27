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
├── streamlit/           # UI helpers for pricing forms
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

Use `msm_pricing.meta_tables.register_pricing_meta_tables(...)` to register the
pricing MetaTable graph. The graph includes core dependencies such as
`AssetTable` and `IndexTable` before pricing extension tables so foreign-key
mappings are resolved in order.

Curves are pricing-owned reference data, not assets. `CurveTable` owns curve
identity, and `DiscountCurvesNode` lives under `msm_pricing.data_nodes` as a
stamped DataNode keyed by `(time_index, curve_unique_identifier)`. Curve
DataNode configurations use the actual `CurveTable.unique_identifier`; they do
not resolve Main Sequence Constants into curve identity.

Fixings are index facts, not assets and not a separate rate model.
`FixingRatesNode` lives under `msm_pricing.data_nodes` as an
`IndexTimestampedDataNode` helper keyed by `(time_index, unique_identifier)`,
where `unique_identifier` references `IndexTable.unique_identifier`. Its
configuration includes a hashable `frequency` field, so the observation
frequency is part of the DataNode identity.
Fixing configurations likewise use actual `IndexTable.unique_identifier` values
and do not resolve Main Sequence Constants into index identity.
Runtime builder callables are attached after DataNode construction with
`set_curve_builder(...)` / `set_fixing_builders(...)` or by subclassing the hook
methods, so builder wiring is not part of the hashed DataNode configuration.

User-facing persistence starts from instruments:

```python
bond.attach_to_asset(asset)
loaded = pricing.Instrument.load_from_asset(asset)
```

The generic loader rebuilds the concrete stored instrument type. Typed loaders
such as `ZeroCouponBond.load_from_asset(asset)` validate that the attached
instrument matches the requested class.

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

## Extending

Add new priceable instruments under `instruments/` and shared QuantLib helpers
under `pricing_engine/`. Keep SQLAlchemy table declarations under `models/`.
Keep storage access in `data_interface/`, and keep pricing DataNode publishers
under `data_nodes/` so instrument classes remain focused on rebuilding terms
and pricing.
