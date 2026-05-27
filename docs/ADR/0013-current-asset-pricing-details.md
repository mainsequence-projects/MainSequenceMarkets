# 0013. Current Asset Pricing Details

## Status

Proposed

## Context

`msm_pricing` contains the QuantLib-backed pricing runtime for instruments such
as `FixedRateBond`, `FloatingRateBond`, and `InterestRateSwap`. Those classes
can serialize the terms required to rebuild a priceable instrument later, but
the package does not yet own a durable pricing persistence surface.

The Main Sequence instrument documentation describes pricing details as the
bridge between platform assets and runtime pricing. Market data alone does not
make an asset priceable; downstream pricing needs a serialized instrument model
and an as-of timestamp for those terms. The relevant documented fields are:

- `instrument_dump`
- `pricing_details_date`

Local `ms-markets` already has a timestamped `AssetPricingDetail` DataNode keyed
by `(time_index, unique_identifier)`, but it currently lives under
`src/msm/data_nodes/assets/snapshots.py`. That placement is wrong for the new ownership
boundary. Pricing details are not generic asset snapshots; they are pricing
runtime inputs and should move into `msm_pricing`.

The asset extension rule still applies: `AssetTable` is the canonical asset
registry and must stay small. Pricing terms must not become columns on
`AssetTable`. The pricing package may define its own persistence tables that
reference `AssetTable.uid`.

There is a second boundary problem in `msm_pricing`: the package name
`msm_pricing.models` is misleading today. In core `msm`, `models` means
SQLAlchemy MetaTable declarations. In `msm_pricing`, `models` currently contains
pricing engines, curve/index registry functions, and helper builders. If pricing
is going to own pricing-specific MetaTables, the runtime helpers need clearer
names so `msm_pricing.models` can mean actual persistent model declarations.

## Decision

Move pricing-detail ownership into `msm_pricing`.

Core `msm` owns canonical asset identity. Pricing-specific persistence,
pricing-specific DataNodes, and instrument serialization helpers belong to
`msm_pricing` and may reference core asset tables.

### Current Pricing Details MetaTable

Add a pricing-owned one-to-one asset detail table for the current serialized
pricing definition of an asset, and use it first for bond assets.

The table declaration should live under:

```text
src/msm_pricing/models/pricing_details.py
```

The table declaration name should be:

```text
AssetCurrentPricingDetailsTable
```

The MetaTable identifier should be:

```text
AssetCurrentPricingDetails
```

The table should reference `msm.models.assets.AssetTable`, but it should not be
part of `msm.models.assets` and should not be returned by core
`markets_sqlalchemy_models()`.

Pricing should provide its own registration helper, for example:

```text
msm_pricing.meta_tables.pricing_sqlalchemy_models()
msm_pricing.meta_tables.register_pricing_meta_tables(...)
```

Those helpers should register core dependencies such as `AssetTable` first, or
require a caller-provided target MetaTable UID mapping when the core asset table
is already registered.

The first table should be generic enough to support additional priceable
instrument classes later:

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

Initial columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `asset_uid` | UUID PK/FK | Canonical asset row whose current pricing terms are being stored. |
| `instrument_type` | string | Serialized instrument type, for example `FixedRateBond` or `FloatingRateBond`. |
| `instrument_dump` | JSON | Serialized `msm_pricing.instruments.Instrument` payload. |
| `pricing_details_date` | timezone-aware datetime | As-of timestamp for the stored terms. |
| `serialization_format` | string | Stable format key, initially `msm_pricing.instrument.v1`. |
| `pricing_package_version` | string nullable | `ms-markets` package version that produced the payload, when available. |
| `source` | string nullable | Provider, workflow, or integration that produced the terms. |
| `metadata` | JSON nullable | Non-contractual metadata for diagnostics and provenance. |

`asset_uid` must be both the primary key and the foreign key to
`AssetTable.uid`. Do not add a separate detail-row `uid`.

Serialized `InstrumentModel` payloads must be identity-free. The legacy
`main_sequence_asset_id` field belongs to an old architecture and must not be
accepted or emitted. Asset linkage is owned by
`AssetCurrentPricingDetailsTable.asset_uid`, not by the priceable instrument
terms.

The foreign key should cascade on asset deletion because the current pricing
detail row must not outlive its canonical asset row.

The table should not duplicate every bond term as normalized relational columns
in the first implementation. The serialized instrument dump is the authoritative
priceable contract. Add normalized columns later only for proven lookup or
governance needs, and only through a separate decision.

### Pricing Details DataNode

Move the timestamped pricing-detail DataNode out of core assets and into
pricing:

```text
src/msm/data_nodes/assets/snapshots.py
  AssetSnapshot

src/msm_pricing/data_nodes/pricing_details.py
  AssetPricingDetail
  AssetPricingDetailConfiguration
  asset_pricing_detail_records
```

The DataNode keeps its existing dataset meaning: timestamped pricing metadata
keyed by `(time_index, unique_identifier)`. It remains distinct from the current
pricing details MetaTable:

- `AssetCurrentPricingDetailsTable` stores one current priceable definition per
  asset.
- `AssetPricingDetail` stores timestamped pricing metadata or historical
  pricing-detail records.

The canonical import should become:

```python
from msm_pricing.data_nodes.pricing_details import AssetPricingDetail
```

Core `msm.data_nodes.assets` should no longer be the canonical location for
pricing-detail DataNodes.

### Public API Boundary

Expose pricing persistence APIs from `msm_pricing`, not from core `msm`:

```python
from msm_pricing.api.pricing_details import AssetCurrentPricingDetails
```

The row API is an infrastructure layer. It should work with JSON-serializable
payloads, may import core `msm` table declarations such as `AssetTable`, and
must not require callers to pass table handles.

The user-facing API should revolve around `msm_pricing.instruments` because
those classes are already Pydantic models and match user intent. Users should
attach and load priceable instruments through instrument instances or classes,
not by manually assembling pricing-detail rows.

Expected usage:

```python
from msm.api.assets import Asset, AssetType
from msm_pricing import Instrument, ZeroCouponBond

AssetType.upsert(asset_type="bond", display_name="Bond")
asset = Asset.upsert(unique_identifier="example-bond", asset_type="bond")

bond = ZeroCouponBond(
    face_value=100,
    issue_date="2026-01-01",
    maturity_date="2036-01-01",
    # remaining pricing terms omitted
)
bond.attach_to_asset(asset)

instrument = Instrument.load_from_asset(asset)
price = instrument.price()
```

`Instrument.load_from_asset(asset)` must load the current pricing details for
the asset, read the stored `instrument_type`, rebuild the correct concrete
instrument subclass, attach private runtime context such as `_asset_uid`, and
return that concrete instance. This allows callers to start from an `Asset`
without knowing beforehand which pricing class is attached.

Concrete instrument classes should expose the same classmethod for type-specific
loading:

```python
bond = ZeroCouponBond.load_from_asset(asset)
```

Typed loaders should delegate to the generic loader and then validate that the
rebuilt instance is compatible with the requested class. They should also
validate asset type through class-owned configuration, for example bond classes
expecting `asset.asset_type == "bond"`. Do not add one service function per
instrument type such as `attach_bond_to_asset(...)`,
`attach_option_to_asset(...)`, or `load_swap_from_asset(...)`; this would create
a hard-to-maintain API surface. New instrument families should extend the common
instrument contract instead.

`attach_to_asset(...)` belongs on instrument instances. It should validate the
asset type, serialize the identity-free instrument terms, upsert
`AssetCurrentPricingDetailsTable` by `asset_uid`, and set private runtime
attachment state on the returned instance. The private attachment state must not
be part of the serialized instrument payload.

The intended base-class shape is:

```python
class InstrumentModel(BaseModel):
    _asset_uid: uuid.UUID | None = PrivateAttr(default=None)

    expected_asset_type: ClassVar[str | None] = None

    def attach_to_asset(self, asset: Asset, **options) -> Self:
        self.validate_asset(asset)
        row = persist_current_pricing_details(
            asset=asset,
            instrument=self,
            **options,
        )
        self._asset_uid = row.asset_uid
        return self

    @classmethod
    def load_from_asset(cls, asset: Asset) -> Self:
        instrument = load_instrument_from_asset(asset)
        if cls is not InstrumentModel and not isinstance(instrument, cls):
            raise TypeError(...)
        instrument._asset_uid = asset.uid
        return instrument
```

Instrument families should extend the asset-type contract, not the persistence
workflow:

```python
class Bond(InstrumentModel):
    expected_asset_type: ClassVar[str] = "bond"
```

### Bond-First Workflow

The first supported workflow is a bond workflow:

1. upsert `AssetType(asset_type="bond", display_name="Bond")`;
2. upsert the canonical `Asset` with `asset_type="bond"`;
3. build a `msm_pricing.instruments.bond.Bond` subclass such as
   `FixedRateBond`;
4. call `bond.attach_to_asset(asset)` to persist the current pricing details;
5. load the instrument later through `Instrument.load_from_asset(asset)` when
   the caller does not know the concrete instrument type, or through
   `FixedRateBond.load_from_asset(asset)` when the expected type is known;
6. price the returned instrument through its normal pricing methods.

The generic table may also hold swaps or other supported priceable instruments
later, but the initial public helper should focus on bonds so the validation
surface stays narrow.

### Index Convention Details

Priceable instruments must reference market indexes through the canonical core
index identity:

```text
+-----------------------------+
| msm.models.IndexTable      |
|-----------------------------|
| uid                  PK     |
| unique_identifier    unique |
| display_name                |
| provider                    |
| metadata                    |
+-----------------------------+
```

String fields such as `benchmark_rate_index_name`, `floating_rate_index_name`,
and `float_leg_index_name` are not durable pricing relationships. They should be
replaced with UUID fields that point to `IndexTable.uid`, for example
`benchmark_rate_index_uid`, `floating_rate_index_uid`, and
`float_leg_index_uid`.

If pricing needs enough information to reconstruct an index from the backend,
that information belongs in a pricing-owned one-to-one MetaTable extension of
`IndexTable`, not inside the instrument payload and not in core `msm.models`.
The table declaration should live under:

```text
src/msm_pricing/models/index_convention_details.py
```

The table declaration name should be:

```text
IndexConventionDetailsTable
```

The MetaTable identifier should be:

```text
IndexConventionDetails
```

The relationship should be:

```text
+-----------------------------+        one-to-one extension     +-------------------------------+
| IndexTable                  |-------------------------------->| IndexConventionDetails        |
|-----------------------------|        index_uid PK/FK          |-------------------------------|
| uid                  PK     |                                 | index_uid              PK/FK  |
| unique_identifier    unique |                                 | index_family                  |
| display_name                |                                 | convention_dump               |
| provider                    |                                 | serialization_format          |
| metadata                    |                                 | source                        |
+-----------------------------+                                 | metadata                      |
                                                                +-------------------------------+
```

`index_uid` should be the only primary key and should be a foreign key to
`IndexTable.uid`. The row is dependent on the canonical index row, so
`ondelete="CASCADE"` is appropriate for the convention-detail table.

The convention detail stores index mechanics, not market-data selection. It may
include serializable fields such as index family, tenor, calendar code, day
counter code, currency code, settlement days, business-day convention,
end-of-month behavior, and fixing source information.

### Curve Details

Curves are pricing concepts owned by `msm_pricing`. They are not assets, and
the pricing package must not model them as `AssetTable` rows just because the
legacy discount-curve DataNode currently uses asset-indexed infrastructure.

Add a pricing-owned curve MetaTable under:

```text
src/msm_pricing/models/curves.py
```

The table declaration name should be:

```text
CurveTable
```

The MetaTable identifier should be:

```text
Curve
```

The curve row should point to the pricing-owned index convention row, not
directly to core `IndexTable`. This ensures a curve can only be attached to an
index that has pricing reconstruction details:

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

Initial columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `uid` | UUID PK | Canonical curve row identity. |
| `unique_identifier` | string unique | Stable curve key used by curve DataNodes. |
| `display_name` | string | Human-readable curve name. |
| `curve_type` | string | Curve role or family such as `discount`, `zero`, `forward`, `projection`, or `basis`. |
| `index_uid` | UUID FK | Pricing index convention row this curve is attached to; target is `IndexConventionDetailsTable.index_uid`. |
| `interpolation_method` | string nullable | Curve interpolation method used by the pricing engine. |
| `compounding` | string nullable | Curve compounding convention used by the pricing engine. |
| `source` | string nullable | Provider, workflow, or integration that produced the curve identity. |
| `metadata` | JSON nullable | Non-contractual metadata for diagnostics and provenance. |

Curve identity rules:

- `CurveTable.uid` is the canonical row identity used by MetaTable relations.
- `CurveTable.unique_identifier` is the stable storage key used by curve
  DataNodes and external curve producers.
- `CurveTable.index_uid` points to `IndexConventionDetailsTable.index_uid`.
  This is the same UUID value as the core index row, but the FK target is the
  pricing convention table because curves are pricing concepts.
- Do not make curves assets and do not reference `AssetTable` from
  `CurveTable`.
- Do not make `(index_uid, curve_type)` unique in the first implementation.
  Multiple providers, sources, construction methods, or scenario contexts may
  produce different curves for the same index and curve type. The stable unique
  key is `unique_identifier`.
- Add indexes for `unique_identifier`, `index_uid`, `curve_type`, and `source`
  so runtime curve resolution can be intentional and observable.

`CurveTable` should not duplicate index mechanics. Do not add
`day_counter_code`, `currency_code`, calendar, tenor, fixing rules, or business
day convention columns to the curve table. Those belong to
`IndexConventionDetailsTable`.

#### Curve DataNode Contract

The current discount-curve producer stores curves under a string `curve_uid`.
That string is the curve storage key. It should become
`CurveTable.unique_identifier`.

The target curve DataNode contract is:

```text
DiscountCurves DataNode
  index:   (time_index, curve_unique_identifier)
  columns: curve
  FK:      curve_unique_identifier -> CurveTable.unique_identifier
```

The curve DataNode should reference `CurveTable` by curve unique identifier
instead of pretending curves are assets:

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| CurveTable                  |<--------------------------------| DiscountCurves DataNode     |
|-----------------------------|        curve_unique_identifier   |-----------------------------|
| uid                  PK     |                                  | time_index                  |
| unique_identifier    unique |                                  | curve_unique_identifier     |
| curve_type                  |                                  | curve                       |
| index_uid            FK     |                                  +-----------------------------+
+-----------------------------+
```

The DataNode migration should preserve the published curve data meaning:

- `time_index` remains the observation date or effective curve date.
- `curve_unique_identifier` identifies the curve series, not an asset.
- `curve` remains the serialized curve points payload until a separate decision
  normalizes curve nodes into point-level rows.
- The DataNode should declare a source-table foreign key to
  `CurveTable.unique_identifier`.
- New curve DataNode code should not inherit `AssetIndexedDataNode`; use a
  curve-specific DataNode base or a normal `DataNode` with an explicit
  `SourceTableForeignKey`.

#### Curve Resolution

The default pricing path should support the user workflow:

```python
bond = Instrument.load_from_asset(asset)
bond.set_valuation_date(valuation_date)
price = bond.price()
```

When no explicit curve object is passed, pricing should resolve a curve through
the persisted pricing graph:

```text
instrument index UID
  -> IndexConventionDetailsTable.index_uid
  -> CurveTable rows for index_uid
  -> selected curve row by curve_type/source/default policy
  -> DiscountCurves DataNode by CurveTable.unique_identifier
  -> QuantLib curve
```

The first default-selection rule should be strict:

- if exactly one curve row matches `(index_uid, curve_type)` for the requested
  pricing role, use it;
- if more than one row matches, require the caller or pricing configuration to
  provide a source, curve UID, or future valuation-context selector;
- if no row matches, fail with a clear missing-curve error.

This gives `bond.price()` a deterministic default path without hiding ambiguous
market-data choices.

The runtime reconstruction path should be:

```text
+-----------------------------+
| Instrument payload          |
|-----------------------------|
| benchmark_rate_index_uid    |
| floating_rate_index_uid     |
| float_leg_index_uid         |
+--------------+--------------+
               |
               | FK/reference to canonical index identity
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
| DiscountCurves DataNode     |
|-----------------------------|
| curve_unique_identifier     |
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

This replaces the old runtime shortcut where an in-memory `IndexSpec` bundled
index conventions together with a `curve_uid`. `IndexSpec` is not a table and
should not become the persisted contract by that name. The persistent contract
is `IndexConventionDetailsTable` plus `CurveTable`; the runtime builders under
`msm_pricing.pricing_engine` can transform the convention payload and selected
curve row into QuantLib objects.

### Runtime Package Structure

Rename the pricing-runtime packages so names match their roles:

```text
msm_pricing/
  models/          # SQLAlchemy MetaTable declarations for pricing-owned persistence
  data_nodes/      # pricing DataNodes, including pricing_details.py
  instruments/     # serializable priceable instrument contracts
  pricing_engine/  # QuantLib pricing and construction functions
  persistence/     # bridge helpers between InstrumentModel and pricing rows
  data_interface/  # platform reads for curves and index fixings
  streamlit/       # form helpers for pricing UIs
```

Do not keep runtime helpers in `msm_pricing.models`. That package should follow
the same convention as core `msm.models` and contain pricing-owned SQLAlchemy
MetaTable declarations only. Runtime helpers and internal imports should use
`msm_pricing.pricing_engine`.

Index fixings are index facts, not assets and not a separate `Rate` model.
Pricing keeps a `FixingRatesNode` helper because pricing needs a direct hook for
hydrating QuantLib indexes from stored fixings, but that helper extends
`IndexTimestampedDataNode` and stores rows keyed by
`(time_index, unique_identifier)` where `unique_identifier` references
`IndexTable.unique_identifier`. The fixing node configuration owns a hashable
`frequency` field so datasets with different observation frequencies produce
different DataNode identities.

Curve and fixing DataNodes use the real MetaTable identities directly:
`CurveTable.unique_identifier` and `IndexTable.unique_identifier`. The old
Main Sequence Constant-based builder registry is intentionally removed because
it introduced a second identity layer that conflicts with the Curve and Index
MetaTables. Source-specific publishers should pass runtime builder callables or
subclass DataNode hook methods; the builder is execution wiring, not persisted
dataset identity.

The intended move is:

| Current path | Target path |
| --- | --- |
| `msm_pricing.models.bond_pricer` | `msm_pricing.pricing_engine.bond_pricer` |
| `msm_pricing.models.swap_pricer` | `msm_pricing.pricing_engine.swap_pricer` |
| `msm_pricing.models.indices` | `msm_pricing.pricing_engine.indices` |
| `msm_pricing.models.indices_builders` | `msm_pricing.pricing_engine.indices_builders` |

## Consequences

`AssetTable` remains stable and does not gain pricing columns.

Pricing persistence becomes an explicit `msm_pricing` responsibility. Core
`msm` can continue to own asset identity while pricing owns priceable terms,
pricing-specific DataNodes, and instrument serialization.

The pricing package can define MetaTables that reference core asset tables. This
requires a pricing-specific registration path so callers can register pricing
tables after, or together with, the core asset table dependencies.

Current pricing details become queryable and governable as a MetaTable resource,
while timestamped pricing metadata remains available through the moved
`AssetPricingDetail` DataNode.

The package rename gives `msm_pricing.models` a clearer long-term meaning:
pricing-owned persistent model declarations. Runtime imports through
`msm_pricing.models` are an intentional breaking boundary cleanup; use
`msm_pricing.pricing_engine` instead.

The first implementation should be bond-focused even though the table shape is
generic. If later instruments require normalized relational search fields, that
should be handled as a follow-up extension rather than by widening this first
table prematurely.

## Implementation Tasks

- [x] Move `AssetPricingDetail`, `AssetPricingDetailConfiguration`, and
  `asset_pricing_detail_records` from `src/msm/data_nodes/assets/snapshots.py` to
  `src/msm_pricing/data_nodes/pricing_details.py`.
- [x] Add `src/msm_pricing/data_nodes/__init__.py` and export the pricing
  details DataNode from it.
- [x] Update imports, docs, and tests to use
  `msm_pricing.data_nodes.pricing_details.AssetPricingDetail` as the canonical
  path.
- [x] Decide whether `msm.data_nodes.assets.AssetPricingDetail` is removed
  immediately or kept as a temporary compatibility alias that does not import
  QuantLib.
- [x] Add `AssetCurrentPricingDetailsTable` under
  `src/msm_pricing/models/pricing_details.py`.
- [x] Use `asset_uid` as the only primary key and as a foreign key to
  `AssetTable.uid` with `ondelete="CASCADE"`.
- [x] Add columns for `instrument_type`, `instrument_dump`,
  `pricing_details_date`, `serialization_format`, `pricing_package_version`,
  `source`, and physical `metadata` via a Python-safe SQLAlchemy attribute such
  as `metadata_json = mapped_column("metadata", JSON, nullable=True)`.
- [x] Add intentional indexes for `instrument_type` and
  `pricing_details_date`.
- [x] Export the table from `msm_pricing.models`.
- [x] Add `msm_pricing.meta_tables.pricing_sqlalchemy_models()` in dependency
  order, including `AssetTable` before `AssetCurrentPricingDetailsTable`.
- [x] Add `msm_pricing.meta_tables.register_pricing_meta_tables(...)` or an
  equivalent helper that registers pricing MetaTables while resolving core
  asset-table dependencies.
- [x] Add tests proving the table uses `asset_uid` as the one-to-one primary
  key, has no separate `uid`, and points at `AssetTable.uid` with cascade
  delete.
- [ ] Add registration-request tests proving pricing models build in dependency
  order for platform-managed and external-registered modes.
- [x] Add `msm_pricing.api.pricing_details.AssetCurrentPricingDetails` plus
  create, upsert, and update payload models.
- [x] Remove legacy `main_sequence_asset_id` from `InstrumentModel` without
  replacing it with `uid` or `asset_uid` on the instrument payload.
- [x] Make the row API require `[AssetTable, AssetCurrentPricingDetailsTable]`
  and upsert by `asset_uid`.
- [x] Add API tests for payload validation, runtime resolution, and upsert
  operation values.
- [x] Add `InstrumentModel.attach_to_asset(asset, ...)` as the primary
  user-facing write path for pricing details.
- [x] Add `Instrument.load_from_asset(asset)` as a generic dispatcher that
  rebuilds and returns the concrete instrument type stored on the asset.
- [x] Add typed `load_from_asset(asset)` classmethods on concrete instrument
  families that delegate to the generic loader and validate the returned
  instrument type.
- [x] Add class-owned asset-type validation so bond instruments require assets
  with `asset_type="bond"` and future instrument families can define their own
  expected asset type.

### Index Convention And Curve Migration

- [x] Audit persisted pricing instrument fields that reference indices by
  mutable string names, starting with `Bond.benchmark_rate_index_name`,
  floating-rate bond index fields, and `InterestRateSwap.float_leg_index_name`.
- [x] Replace persisted index-name fields with canonical `IndexTable.uid`
  references, for example `benchmark_rate_index_uid`,
  `floating_rate_index_uid`, and `float_leg_index_uid`.
- [x] Do not add long-term aliases for the legacy `*_index_name` fields. Treat
  them as a breaking cleanup unless a dedicated data migration needs temporary
  compatibility.
- [x] Add `IndexConventionDetailsTable` under
  `src/msm_pricing/models/index_convention_details.py` as a one-to-one pricing
  extension of `IndexTable`.
- [x] Use `index_uid` as the only primary key on
  `IndexConventionDetailsTable` and as a foreign key to `IndexTable.uid` with
  `ondelete="CASCADE"`.
- [x] Add `IndexConventionDetailsTable` columns for `index_family`,
  `convention_dump`, `serialization_format`, `source`, and physical
  `metadata`.
- [x] Add `CurveTable` under `src/msm_pricing/models/curves.py` as the
  pricing-owned curve identity table.
- [x] Add `CurveTable` columns for `uid`, `unique_identifier`, `display_name`,
  `curve_type`, `index_uid`, `interpolation_method`, `compounding`, `source`,
  and physical `metadata`.
- [x] Make `CurveTable.index_uid` a foreign key to
  `IndexConventionDetailsTable.index_uid`, not directly to `IndexTable.uid`.
- [x] Do not add `day_counter_code`, `currency_code`, calendar, tenor, fixing
  rules, or business-day convention columns to `CurveTable`; these belong to
  `IndexConventionDetailsTable`.
- [x] Add intentional indexes for `CurveTable.unique_identifier`,
  `CurveTable.index_uid`, `CurveTable.curve_type`, and `CurveTable.source`.
- [x] Add `IndexConventionDetailsTable` and `CurveTable` to
  `msm_pricing.meta_tables.pricing_sqlalchemy_models()` in dependency order
  after `IndexTable` and before curve-dependent consumers.
- [x] Add pricing row APIs for index convention details and curves under
  `msm_pricing.api`.
- [x] Add a pricing index resolver that accepts an `IndexTable.uid`, loads the
  corresponding `IndexConventionDetailsTable` row, and builds the runtime
  QuantLib index from the convention payload.
- [x] Add a curve resolver that accepts an `index_uid`, curve type, and
  valuation date, resolves a `CurveTable` row, loads observations from the
  discount-curves DataNode by `CurveTable.unique_identifier`, and returns the
  QuantLib curve object required by the pricing engine.
- [x] Make the curve resolver strict: use the only matching
  `(index_uid, curve_type)` row when the match is unique, require an explicit
  source, curve UID, or future valuation-context selector when multiple rows
  match, and raise a clear missing-curve error when no rows match.
- [ ] Refactor the legacy runtime `IndexSpec.curve_uid` coupling so index
  conventions no longer select curves directly.
- [x] Migrate the discount-curves DataNode contract so curve observations are
  keyed to `CurveTable.unique_identifier` rather than to `AssetTable` identity.
- [x] Add a curve DataNode table contract with index
  `(time_index, curve_unique_identifier)`, a `curve` payload column, and a
  source-table foreign key from `curve_unique_identifier` to
  `CurveTable.unique_identifier`.
- [x] Stop inheriting new curve DataNode code from `AssetIndexedDataNode`; use a
  curve-specific DataNode base or a normal `DataNode` with an explicit
  `SourceTableForeignKey`.
- [x] Add tests proving curve observations declare the `CurveTable` foreign key
  and do not declare the canonical asset foreign key.
- [x] Update bond and swap pricing methods so they resolve QuantLib indices
  and curves through the new UID-based convention and curve resolvers instead
  of calling `get_index(...)` with a raw name.
- [x] Update serialized instrument validation so persisted payloads require
  UUID index references and reject stale `*_index_name` relationship fields.
- [x] Add API and instrument tests proving serialized bond and swap payloads
  store index UIDs, resolver calls receive the expected backend index UID, and
  attach/load round trips preserve the UID reference.
- [ ] Add migration notes for existing payloads that contain
  `benchmark_rate_index_name`, `floating_rate_index_name`, or
  `float_leg_index_name`, including how each old string should be matched to an
  `IndexTable.uid`.
- [ ] Validate at least one fixed-rate bond round trip:
  `instrument.attach_to_asset(asset) -> AssetCurrentPricingDetails ->
  Instrument.load_from_asset(asset) -> price()`.
- [ ] Add a bond asset example under `examples/pricing/` that creates or
  resolves a bond asset and writes current pricing details.
- [ ] Update `docs/knowledge/assets/index.md` so it points pricing-detail
  readers to `msm_pricing` instead of presenting pricing details as core asset
  DataNodes.
- [ ] Update `docs/knowledge/pricing/index.md` to describe the pricing-owned
  table, pricing-owned DataNode, and `msm_pricing.persistence` helpers.
- [ ] Update `docs/knowledge/models/index.md` to clarify that core `msm.models`
  does not own pricing-specific table declarations.
- [ ] Update `docs/tutorial/index.md` or `docs/tutorial/market_workflows.md`
  with the bond-pricing-details workflow.
- [ ] Update `CHANGELOG.md`.
- [x] Add the `msm_pricing.pricing_engine` package for QuantLib-backed runtime
  helpers.
- [x] Move internal imports from runtime-oriented `msm_pricing.models.*`
  modules to `msm_pricing.pricing_engine.*`.
- [x] Remove runtime exports from `msm_pricing.models` so the package only
  exposes pricing-owned MetaTable declarations.
- [x] Update `src/msm_pricing/README.md`, `docs/knowledge/pricing/index.md`,
  and ADR 0005 references to prefer `pricing_engine` over runtime helpers under
  `models`.
- [ ] Run `git diff --check`.
- [ ] Run focused tests for pricing DataNodes, pricing MetaTables, pricing API,
  and pricing import compatibility.
- [ ] Run `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`
  after docs navigation updates.
