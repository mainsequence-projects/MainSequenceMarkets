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
from msm_pricing.pricing_engine import (
    apply_z_spread_to_curve,
    resolve_quantlib_index,
    resolve_pricing_curve,
)
from msm_pricing.analytics.spreads import fixed_income_spread_metrics
from msm_pricing.scenarios.curves import CurveBumpSpec, CurveScenario, price_curve_scenario
from msm_pricing.scenarios.valuation import (
    ValuationScenario,
    run_valuation_scenario_workflow,
)
from msm_pricing.valuation import ValuationLine, ValuationPosition, build_valuation_position
```

## Package Layout

```text
src/msm_pricing/
├── analytics/           # Pure-data spread and relative-value analytics
├── api/                 # User-facing pricing persistence workflows
├── data_interface/      # Main Sequence market-data reads for curves/index fixings
├── data_nodes/          # Pricing DataNodes and curve/index-fixing codecs
├── instruments/         # Pydantic wrappers for priceable instruments
├── meta_tables.py       # Pricing MetaTable discovery and registration
├── models/              # SQLAlchemy MetaTable declarations
├── pricing_engine/      # QuantLib curve, index, bond, and swap helpers
├── scenarios/           # Transient scenario helpers layered on valuation contexts
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
- `ValuationLine`
- `ValuationPosition`
- `build_valuation_position`
- `CurveBumpSpec`
- `CurveScenario`
- `CurveScenarioResult`
- `price_curve_scenario`
- `ValuationScenario`
- `ValuationScenarioWorkflowResult`
- `price_valuation_lines`
- `run_valuation_scenario_workflow`

`ValuationPosition` is an in-memory valuation basket. It links priceable
instrument instances to unit multipliers for one explicit valuation context. It
is not a persisted pricing MetaTable and does not own account or portfolio
position state.

Curve scenarios live under `msm_pricing.scenarios.curves`. Use
`price_curve_scenario(...)` when a position should be repriced by applying
parallel or key-rate basis-point bumps to resolved curve key nodes. The helper
builds transient scenario handles from copied observation provenance, applies
runtime z-spread overlays when present, and delegates line valuation to
`price_scenario(...)`. Use `price_scenario(...)` directly only when the caller
already owns the exact line-scoped base and scenario handles.

Generic valuation workflows live under `msm_pricing.scenarios.valuation`. Use
`run_valuation_scenario_workflow(...)` when a dashboard, API, or service needs
base valuation, one or more scenario runs, partial-success diagnostics, line
impacts, optional analytics/cashflows, carry impacts, and explicit observed
dirty-price z-spread overlays. The workflow returns typed in-memory records,
not pandas or Command Center table payloads; application wrappers own table
formatting. The canonical documentation is under
`docs/knowledge/msm_pricing/scenarios/`, mirroring the package folder.

Spread analytics live under `msm_pricing.analytics.spreads`. The cross-asset
`base` module owns aligned spread construction, z-score matrices, pair metrics,
hedge-ratio estimation, and forecast cones from caller-supplied data. The
`fixed_income` module adds DV01, carry, roll-down, and downside interpretation
without reading curves, portfolios, assets, or backend rows. Future equity,
index, commodity, and option spread analytics should be sibling modules under
the same namespace.

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
identity, `CurveBuildingDetailsTable` owns curve construction rules, and
`PricingMarketDataSetCurveBindingTable` owns valuation-context curve selection.
`DiscountCurvesNode` lives under `msm_pricing.data_nodes` as a stamped DataNode
keyed by `(time_index, curve_identifier)`. Curve DataNode configurations use
the actual `CurveTable.unique_identifier`; they do not resolve Main Sequence
Constants into curve identity. EOD curve observations declare daily cadence on
`DiscountCurvesStorage.__cadence__`. Publishers emit a curve mapping plus
`key_nodes` construction provenance; storage keeps both the pricing `curve` and
`key_nodes` compressed at rest, while read/API helpers return decompressed JSON.
Key nodes are source-owned JSON object/list provenance with JSON-serializable
nested values. Producers may use the optional `CurveKeyNode` helper and
recommended fields such as `source_reference`, `maturity_date`,
`instrument_type`, `quote`, `quote_type`, `quote_unit`, `quote_side`, and
`yield`, and may add source-specific extensions. `source_reference.type` is
`asset` or `index`, and its identifier is the corresponding canonical unique
identifier. Top-level `asset_identifier` and `index_identifier` key-node fields
are rejected. `CurveBuildingDetails` still describes how the final stored
curve is built and interpreted by pricing.
Source-specific builders can enforce stricter provenance semantics by overriding
`DiscountCurvesNode.normalize_key_nodes(...)` or by attaching a runtime callable
with `set_key_nodes_validator(...)`.

Helper-based curves use `builder_type="rate_helper_curve"` and generic helper
key nodes. `rate_helpers@v1` is the canonical helper schema for deposit, OIS,
futures, bond, FX swap, and constant-notional cross-currency basis helpers. It
also accepts context/provenance nodes such as FX spot when a helper needs
runtime construction context. All fixed-income helper key-node models inherit
the typed `FixedIncomeCurveKeyNode` quote/source contract; bond inputs may use
asset sources while swap, futures, deposit, FX, or basis quote series may use
index sources. Runtime dependencies such as collateral curves and base/quote
indexes remain helper-specific and are resolved explicitly through helper
runtime resolvers; connector-owned schema names are not part of core
`msm_pricing`.

Curve construction is strict. `CurveBuildingDetails.interpolation_method` must
be one of `log_linear_discount`, `log_cubic_discount`, `linear_zero`,
`cubic_zero`, `natural_cubic_zero`, `monotone_cubic_zero`, or `linear_forward`
with `quote_convention="forward_rate"`. Deprecated QuantLib names such as
`log_linear_zero`, `LogLinearZeroCurve`, `monotonic_log_cubic_discount`, and
`MonotonicLogCubicDiscountCurve` are rejected instead of aliased.

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

Storage-source binding is separate from curve-identity binding. A single
discount-curve storage table can contain many curve identifiers, so market-data
sets also select the curve for each valuation role:

```python
from msm_pricing.api import PricingMarketDataSetCurveBinding

PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    index_uid=index.uid,
    quote_side="mid",
    curve_uid=curve.uid,
)
```

`upsert_index_curve_selection(...)` persists the generic
`selector_type="index"` and `selector_key=str(index.uid)` fields internally.
Use the raw `upsert(...)` binding API only when you really need a non-index
selector policy.

The data interface resolves direct in-memory overrides first and persisted
market-data set bindings second. The final lookup uses
`APIDataNode.build_from_table_uid(...)`.

At pricing time, callers select the source set by key:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

When the argument is omitted, the process default market-data set is used.

For instrument-plus-units valuation, use `ValuationPosition`:

```python
from msm_pricing.valuation import build_valuation_position

position = build_valuation_position(
    [
        {
            "instrument": bond,
            "units": 25.0,
            "asset_uid": asset.uid,
            "metadata_json": {"source": "example"},
        }
    ],
    valuation_date=valuation_date,
    market_data_set="eod",
)
portfolio_value = position.price()
```

`build_valuation_position(...)` accepts normalized row mappings or a pandas
DataFrame with required `instrument` and `units` fields, plus optional
`asset_uid` and `metadata_json`. It does not resolve assets or load instruments;
callers should use the package-owned source workflows first and pass already
loaded priceable instruments into the helper.

For portfolio or scenario pricing, prepare a `PricingValuationContext` before
the line-pricing loop. The context resolves the fixed-income market-data graph
in bulk and prices prepared copies rather than mutating caller-owned
instruments:

```python
from msm_pricing import price_scenario
from msm_pricing.valuation import PricingValuationContext

context = PricingValuationContext.prepare_for_position(
    position,
    curve_quote_side="mid",
)
portfolio_value = position.price(context=context)
prepared_bond = context.prepare_instrument(bond)
observed_z_spread = prepared_bond.z_spread(target_dirty_ccy)

scenario = price_scenario(
    position=position,
    context=context,
    line_curve_handles=base_handles_by_line,
    scenario_curve_handles=scenario_handles_by_line,
)
```

`PreparedInstrument.z_spread(...)` expects the target dirty price as a currency
amount. Source-specific quote normalization, such as converting dirty price per
100 notional into currency, should happen before calling the prepared method.

User-facing persistence starts from instruments:

```python
from msm_pricing.api import add_many_pricing_details, load_instruments_from_assets

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

Use `load_instruments_from_assets(...)` when an account, portfolio, or custom
workflow has already resolved the asset rows and needs the current priceable
instrument for each asset:

```python
instruments_by_asset_uid = load_instruments_from_assets(assets, batch_size=1000)
```

`attach_to_asset(...)` writes a timestamped pricing-details observation. When
`pricing_details_date` is not provided, it uses `now()` and updates the internal
current table for fast loading. If a date is provided, it upserts that
timestamped snapshot and updates current when no current row exists or when the
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

Account holdings and portfolio weights are not pricing positions. Their owning
package must select the relevant snapshot, resolve asset rows, and normalize
exposure into signed `units`. Pricing then receives only valuation lines:

```python
from msm_pricing.api import load_instruments_from_assets
from msm_pricing.valuation import build_valuation_position

instruments_by_asset_uid = load_instruments_from_assets(assets)
valuation_rows = [
    {
        "instrument": instruments_by_asset_uid[row["asset_uid"]],
        "units": row["units"],
        "asset_uid": row["asset_uid"],
    }
    for row in normalized_source_rows
]
position = build_valuation_position(
    valuation_rows,
    valuation_date=valuation_date,
    market_data_set="eod",
)
```

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
pricing APIs. The example binds separate projection and discount curves for the
floating index. A market-data set may bind both roles to one physical curve
only by writing both role bindings explicitly.

## Extending

Add new priceable instruments under `instruments/` and shared QuantLib helpers
under `pricing_engine/`. Keep SQLAlchemy table declarations under `models/`.
Keep storage access in `data_interface/`, and keep pricing DataNode publishers
under `data_nodes/` so instrument classes remain focused on rebuilding terms
and pricing.
