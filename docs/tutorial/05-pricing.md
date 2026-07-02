# Pricing Instruments

Connect priceable instruments to the canonical assets you registered in
[Assets and Categories](01-assets.md). This chapter covers pricing instrument
identity, market-data set bindings, bond pricing, and a short note on extending
the markets schema.

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Pricing instrument identity

Use this workflow when connecting pricing terms to a canonical asset:

1. Persist or resolve the asset through `msm.api.assets.Asset`.
2. Store the asset-to-pricing relationship in pricing-owned persistence, keyed
   by the asset UID.
3. Keep `InstrumentModel` payloads limited to priceable terms. Do not include
   `main_sequence_asset_id`, `uid`, or `asset_uid` in serialized instrument
   terms.

This keeps instrument reconstruction independent from Main Sequence persistence
identity. `instrument.attach_to_asset(asset, ...)` writes a timestamped
pricing-details observation. Without `pricing_details_date`, it uses `now()`
and updates the current projection for fast `Instrument.load_from_asset(...)`
reads. With an explicit date, it upserts that timestamped snapshot and updates
current when no current row exists or when the date is newer than current. See
`examples/msm_pricing/instrument_identity_boundary.py` for a minimal payload
boundary example.

For large universes, use `msm_pricing.api.add_many_pricing_details(...)` instead
of calling `attach_to_asset(...)` or `add_pricing_details(...)` in a loop. It
serializes many asset/instrument pairs and persists pricing rows through
chunked bulk upserts:

```python
from msm_pricing.api import add_many_pricing_details, load_instruments_from_assets

add_many_pricing_details(
    [
        {"asset": asset, "instrument": instrument}
        for asset, instrument in asset_instrument_pairs
    ],
    batch_size=1000,
)
```

When an account, portfolio, or custom workflow already has asset rows and
signed units, use `load_instruments_from_assets(...)` to batch-load the current
instrument definitions before constructing `ValuationLine` rows:

```python
instruments_by_asset_uid = load_instruments_from_assets(assets, batch_size=1000)
```

Account and portfolio packages still own snapshot selection and unit
normalization. Pricing receives only the normalized valuation lines.

When the pricing persistence tables are needed, attach them through
`msm_pricing.bootstrap.attach_pricing_schemas(...)`. That startup flow includes
the core asset and index tables first, then pricing extension tables, and uses
the same direct backend attachment contract as `msm.start_engine(...)`.

## Pricing market-data sets

Pricing bootstrap also seeds default market-data bindings for the built-in
pricing market-data set:

```text
PricingMarketDataSet(set_key="default")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
       data_node_uid = DiscountCurvesStorage.get_meta_table_uid()
  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
       data_node_uid = IndexFixingsStorage.get_meta_table_uid()
```

The binding row maps `(market_data_set_uid, concept_key)` to a backend DataNode
storage table UID. Use `msm_pricing.api.PricingMarketDataSet` and
`PricingMarketDataSetBinding` when an application needs an `eod`, `live`, or
`risk_manager` source set:

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

Pricing resolution looks up the active market-data set and concept, then reads
the resulting DataNode with `APIDataNode.build_from_table_uid(...)`. Public
workflows should bind storage table UIDs; identifiers are diagnostic only.
Callers select a non-default source set at valuation time:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

## Instrument write and read path

The user-facing write and read path belongs to instrument classes:

```python
from msm_pricing import Instrument, ZeroCouponBond

bond = ZeroCouponBond(...)
bond.attach_to_asset(asset)

loaded = Instrument.load_from_asset(asset)
```

`attach_to_asset(...)` is the normal user-facing write path. It records the
timestamped pricing details first. Calls without `pricing_details_date` create a
current snapshot at `now()` and update the active instrument definition. Calls
with `pricing_details_date` reconcile that dated snapshot against the active
instrument definition and update current when the dated snapshot should win.

Use `Instrument.load_from_asset(asset)` when the asset is known but the concrete
pricing instrument is not. Use a typed loader such as
`ZeroCouponBond.load_from_asset(asset)` when the caller expects a specific
instrument family and wants a type check.

## Index-referencing instruments

When an instrument references a market index, register the pricing registry rows
before publishing curve observations:

1. Register the canonical index type through `msm.api.indices.IndexType`.
   Fixed-income examples use the built-in `interest_rate` type.
2. Persist the canonical index through `msm.api.indices.Index`.
3. Upsert `msm_pricing.api.IndexConventionDetails` with the index UID and the
   serializable convention payload needed to rebuild the pricing index.
4. Upsert `msm_pricing.api.Curve` with a stable curve `unique_identifier`.
5. Upsert `msm_pricing.api.CurveBuildingDetails` for that curve.
6. Upsert `msm_pricing.api.PricingMarketDataSetCurveBinding` through
   `upsert_index_curve_selection(...)` to bind the selected market-data set,
   valuation role, index UID, and quote side to the curve UID.
7. Publish curve observations through `DiscountCurvesNode` with
   `curve_identifier` set to the same curve `unique_identifier`. Each emitted
   row must include a non-empty `curve` mapping for the constructed pricing
   nodes and `key_nodes` for the dated input quotes used to build that row.
   `key_nodes` is source-owned JSON at the publisher/API boundary and is
   compressed by storage. The base contract is JSON object/list provenance with
   JSON-serializable nested values. Prefer the optional `CurveKeyNode` helper or
   the standard fields shown below when they fit the source, including
   yield-native inputs for discount curves. Source-specific producers can add
   source-owned extensions and can override
   `DiscountCurvesNode.normalize_key_nodes(...)` or attach
   `set_key_nodes_validator(...)` when they need stricter validation.

   ```python
   return pd.DataFrame(
       [
           {
               "time_index": valuation_timestamp,
               "curve_identifier": curve.unique_identifier,
               "curve": compressed_curve_nodes,
               "key_nodes": [
                   {
                       "maturity_date": "2026-06-26",
                       "instrument_type": "direct_zero_rate",
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

See `examples/msm_pricing/pricing_registry_rows.py` for the row API workflow.

`CurveBuildingDetails.interpolation_method` is enforced at runtime. Use one of
`log_linear_discount`, `log_cubic_discount`, `linear_zero`,
`cubic_zero`, `natural_cubic_zero`, `monotone_cubic_zero`, or `linear_forward` with
`quote_convention="forward_rate"`. Deprecated QuantLib methods such as
`log_linear_zero` and `MonotonicLogCubicDiscountCurve` are rejected.

Serialized pricing instruments should reference these rows by UUID, not by
mutable names. Use `floating_rate_index_uid` on floating-rate bonds and
`float_leg_index_uid` on swaps. The runtime resolver turns those UUIDs into the
correct convention row, curve row, QuantLib index, curve, and fixing series.

Fixed-rate and zero-coupon bonds can also store `benchmark_rate_index_uid` for
benchmark analytics. That field is only the index selector; the benchmark curve
for z-spread must be bound explicitly:

```python
from msm_pricing import FixedRateBond
from msm_pricing.api import PricingMarketDataSetCurveBinding

PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="z_spread_base",
    index_uid=benchmark_index.uid,
    quote_side="mid",
    curve_uid=benchmark_curve.uid,
)

bond = FixedRateBond(
    face_value=100.0,
    issue_date=issue_date,
    maturity_date=maturity_date,
    day_count=day_count,
    coupon_frequency=coupon_frequency,
    coupon_rate=0.05,
    benchmark_rate_index_uid=benchmark_index.uid,
)
bond.set_valuation_date(valuation_date)
spread = bond.z_spread(
    target_dirty_ccy=101.25,
    market_data_set=market_data_set.set_key,
    benchmark_curve_quote_side="mid",
)
```

If the binding is written with `quote_side="mid"`, the runtime call must also
request `"mid"`. Omitted quote side means the `default` binding key, not an
implicit mid quote.

When the computed spread must be applied to a resolved curve handle, keep that
as a runtime overlay:

```python
from msm_pricing.pricing_engine import apply_z_spread_to_curve

spreaded_curve = apply_z_spread_to_curve(benchmark_curve_handle, spread)
```

The helper expects the decimal continuous spread returned by `z_spread(...)`.
It does not modify the published curve observation, `key_nodes`, or curve build
metadata.

## Bond pricing workflow

For a full floating-rate bond workflow, use
`examples/msm_pricing/bond_pricing_example/`. It follows this order:

1. Register or resolve the bond asset type, issuer, currency asset, and bond
   asset through `msm.api.assets` and `msm.api.issuers`.
2. Register the `interest_rate` index type through `msm.api.indices.IndexType`,
   then register the canonical index through `msm.api.indices.Index`.
3. Upsert `IndexConventionDetails`, `Curve`, `CurveBuildingDetails`, and
   `PricingMarketDataSetCurveBinding.upsert_index_curve_selection(...)` rows
   under `msm_pricing.api`. The helper persists the generic selector fields
   internally, so index-based workflows should pass `index_uid`, not
   `selector_type` and `selector_key`.
4. Publish one month of mock fixings through a `FixingRatesNode` subclass and a
   sampled flat-forward curve through a `DiscountCurvesNode` subclass. The curve
   storage row stores both the compressed pricing `curve` and compressed
   source-owned `key_nodes` provenance. The publisher emits `key_nodes` as JSON,
   and read/API helpers return decompressed JSON. The mock example uses the
   recommended yield-aware `CurveKeyNode` shape, while `CurveBuildingDetails`
   remains the source for final curve construction rules. The pricing storage
   classes declare their EOD cadence as `__cadence__ = "1d"`.
5. Attach pricing storage tables, then upsert the `default` market-data set and
   its concept bindings with `PricingMarketDataSet` and
   `PricingMarketDataSetBinding`.
6. Create a `FloatingRateBond` with `floating_rate_index_uid=index.uid`.
7. Add pricing details with `instrument.attach_to_asset(asset, ...)`; without an
   explicit timestamp this creates the current loadable instrument definition.
8. Reload it generically with `Instrument.load_from_asset(asset)`, set the
   valuation date, then call `price(market_data_set="default")`,
   `analytics()`, `get_cashflows()`, and `carry_roll_down(...)`.
9. Use `build_valuation_position(...)` when the valuation input is already
   normalized to instrument plus unit rows. For account or portfolio sources,
   the owning package still selects the source snapshot and resolves assets;
   pricing receives rows with `instrument`, `units`, optional `asset_uid`, and
   optional `metadata_json`. Rows must not carry their own market-data set
   because `ValuationPosition` has one basket-level source selection. The bond
   pricing example now values the loaded bond both as a single instrument and
   as a one-line valuation basket. For portfolio-style runs, prepare a public
   valuation context once and pass it to the basket methods:

   ```python
   from msm_pricing.valuation import PricingValuationContext, build_valuation_position

   position = build_valuation_position(
       normalized_rows,
       valuation_date=valuation_date,
       market_data_set="eod",
   )

   context = PricingValuationContext.prepare_for_position(
       position,
       curve_quote_side="mid",
   )
   total_market_value = position.price(context=context)
   observed_z_spread = context.prepare_instrument(bond).z_spread(target_dirty_ccy)
   ```

   `PricingValuationContext` returns copied or wrapped prepared instruments; it
   does not mutate the caller-owned instruments in the submitted valuation
   lines. The prepared context is fixed to the instrument universe submitted to
   `prepare(...)` or `prepare_for_position(...)`; build a new context when the
   valuation date, market-data set, quote side, or instrument universe changes.
   Prepared `z_spread(...)` calls expect `target_dirty_ccy` to already be a
   currency dirty price; convert source quotes such as dirty price per 100
   before calling the prepared instrument.
   Scenario runs use the public `msm_pricing.price_scenario(...)` helper with
   explicit line-scoped base and scenario curve handles, so scenario state is
   applied to prepared copies instead of caller-owned instruments.
   For a fast local smoke test of that workflow, run
   `examples/msm_pricing/valuation_inputs.py` for normalized valuation rows or
   `examples/msm_pricing/pricing_valuation_context.py` for prepared
   fixed-income context behavior. Both examples avoid live platform
   market-data setup.

The reusable mock market-data components live in `examples/msm_pricing/utils/` so
the same curve and fixing DataNode extension pattern can be reused by swap
pricing examples.

## Extending the schema

The advanced workflows below cover adding project-owned relational tables to the
markets schema. They follow the same migration-then-attach lifecycle as the
built-in tables.

### Markets MetaTable models

Use this workflow when adding or reviewing a market-domain relational table:

1. Define the SQLAlchemy model under `msm.models` with
   `MarketsMetaTableMixin` and `MarketsBase`.
2. Set `__metatable_identifier__` to the stable table identity.
3. Put schema, table info, indexes, and constraints in `__table_args__`.
4. Do not set `__tablename__`; the markets mixin assigns the physical table
   name from the storage app segment and logical identity. Built-in tables use
   `ms_markets`, producing `ms_markets__<lowercase-identity>`. Project-local
   extension tables may set `__markets_storage_app__`, for example
   `binance_spot`, to produce project-owned names such as
   `binance_spot__binancespotaccountdetails`. The
   `MSM_AUTO_REGISTER_NAMESPACE` suffix still applies when configured before
   model import.
5. Add the model to `markets_sqlalchemy_models()` in foreign-key dependency
   order.
6. Generate or update a normal Alembic revision under the active namespace
   directory in `src/migrations/versions/`.
7. Use the SDK migration upgrade flow for schema mutation, then
   `msm.start_engine(...)` for runtime attachment. Do not call model
   `.register()` methods or local registration helpers from application code.

`msm.start_engine(...)` resolves selected tables by backend identifier using
`model.__table__.name`; it does not import, register, or migrate missing
tables.

Examples that use example-scoped platform-managed MetaTables must set
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` before importing
MetaTable-backed `msm.api` or `msm.models` modules, then run explicit startup
attachment. Row operations never register or attach MetaTables on first use. A
different namespace or registration configuration is rejected for the
already-initialized process.

Pass `models=[...]` to explicit preflight when a workflow only needs a subset of
tables, for example `msm.start_engine(models=["Asset"])`. Normal examples and
application code should use typed row classes such as
`msm.api.assets.Asset.upsert(...)`. Use `runtime.table(...)` and
`runtime.context` only for lower-level repository or service internals.

See `examples/msm/platform/inspect_markets_metatable_models.py` for a small offline
inspection example that prints the SDK-derived table names. See
[Markets Models](../knowledge/msm/models/index.md) for the model reference.

### Project-local MetaTable extensions

Use this workflow when an application owns a custom markets table that should be
migrated and registered with the same path as built-in tables:

1. Define an abstract project-local mixin with the project's default
   `__metatable_namespace__` and, when needed, a project-owned
   `__markets_storage_app__`.
2. Define the SQLAlchemy model with that mixin and `MarketsBase`.
3. Give it one stable `__markets_base_identifier__`; ms-markets combines this
   base identifier with the mixin namespace to produce the globally unique
   MetaTable identifier.
4. Declare relationships with normal SQLAlchemy `ForeignKey(...)` targets.
5. Add or sync the package/project migration that creates or refreshes the
   table and finalizes the schema.
6. Attach at runtime with `msm.start_engine(models=[MyModelTable])`.
7. Put row operations in an optional `MarketsMetaTableRow` wrapper.

`MSM_AUTO_REGISTER_NAMESPACE` still overrides the project mixin namespace when
set before model import. Use that for isolated tests and example runs; do not
make env-only namespace setup the main project extension contract.

The `models=[...]` selector is the public runtime attachment boundary. It
expands foreign-key dependencies, verifies and attaches the selected SQLAlchemy
model through direct backend lookup, and binds the resolved backend
`MetaTable` object back to that model. Do not build a project-local UID map or call
row `create_schemas()` helpers as the extension mechanism.

For asset detail tables keyed by `AssetTable.uid`, expose `uid` as an alias of
`asset_uid` in the row wrapper while keeping the SQLAlchemy primary key on
`asset_uid`.

See `examples/msm/platform/custom_asset_details_extension.py` for a minimal
project-local asset detail table, row wrapper, and startup function. See
[Platform Extensions](../knowledge/msm/platform/index.md) for the platform
extension reference.

**Next →** [Pricing knowledge base](../knowledge/msm_pricing/index.md)
