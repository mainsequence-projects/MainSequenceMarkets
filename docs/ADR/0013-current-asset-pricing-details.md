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
`src/msm/data_nodes/assets.py`. That placement is wrong for the new ownership
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
`AssetTable.uid`. Do not add a separate detail-row `uid`. If a Pydantic row
helper needs a `uid` field, expose `uid` as an alias of `asset_uid`.

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
src/msm/data_nodes/assets.py
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

Expose pricing row APIs from `msm_pricing`, not from core `msm`:

```python
from msm_pricing.api.pricing_details import AssetCurrentPricingDetails
```

The row API should work with JSON-serializable payloads. It may import core
`msm` table declarations such as `AssetTable`, but it must not require callers
to pass table handles.

Expected usage:

```python
from msm.api.assets import Asset, AssetType
from msm_pricing.api.pricing_details import AssetCurrentPricingDetails

AssetType.upsert(asset_type="bond", display_name="Bond")
asset = Asset.upsert(unique_identifier="example-bond", asset_type="bond")

details = AssetCurrentPricingDetails.upsert(
    asset_uid=asset.uid,
    instrument_type="FixedRateBond",
    instrument_dump=instrument_dump,
    pricing_details_date="2026-05-27T00:00:00Z",
    serialization_format="msm_pricing.instrument.v1",
)
```

`msm_pricing` should also expose convenience helpers that accept concrete
`InstrumentModel` instances and serialize or rebuild them.

### Bond-First Workflow

The first supported workflow is a bond workflow:

1. upsert `AssetType(asset_type="bond", display_name="Bond")`;
2. upsert the canonical `Asset` with `asset_type="bond"`;
3. build a `msm_pricing.instruments.bond.Bond` subclass such as
   `FixedRateBond`;
4. serialize the instrument to the backend payload format;
5. upsert `AssetCurrentPricingDetailsTable` by `asset_uid`;
6. rebuild the instrument later through `InstrumentModel.rebuild(...)`.

The generic table may also hold swaps or other supported priceable instruments
later, but the initial public helper should focus on bonds so the validation
surface stays narrow.

### Runtime Package Structure

Rename the pricing-runtime packages so names match their roles:

```text
msm_pricing/
  models/          # SQLAlchemy MetaTable declarations for pricing-owned persistence
  data_nodes/      # pricing DataNodes, including pricing_details.py
  instruments/     # serializable priceable instrument contracts
  engines/         # QuantLib pricing and construction functions
  indices/         # IndexSpec registry and QuantLib index construction
  persistence/     # bridge helpers between InstrumentModel and pricing rows
  data_interface/  # platform reads for curves and fixings
  interest_rates/  # curve/fixing ETL and publishing helpers
  streamlit/       # form helpers for pricing UIs
```

Keep `msm_pricing.models` compatibility exports during the migration if needed,
but new runtime helpers and internal imports should use `msm_pricing.engines`
and `msm_pricing.indices`.

The intended move is:

| Current path | Target path |
| --- | --- |
| `msm_pricing.models.bond_pricer` | `msm_pricing.engines.bonds` |
| `msm_pricing.models.swap_pricer` | `msm_pricing.engines.swaps` |
| `msm_pricing.models.indices` | `msm_pricing.indices.registry` |
| `msm_pricing.models.indices_builders` | `msm_pricing.indices.builders` |

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
pricing-owned persistent model declarations. Existing runtime imports through
`msm_pricing.models` need a compatibility period or an intentional breaking
change.

The first implementation should be bond-focused even though the table shape is
generic. If later instruments require normalized relational search fields, that
should be handled as a follow-up extension rather than by widening this first
table prematurely.

## Implementation Tasks

- [x] Move `AssetPricingDetail`, `AssetPricingDetailConfiguration`, and
  `asset_pricing_detail_records` from `src/msm/data_nodes/assets.py` to
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
- [ ] Add `msm_pricing.meta_tables.register_pricing_meta_tables(...)` or an
  equivalent helper that registers pricing MetaTables while resolving core
  asset-table dependencies.
- [x] Add tests proving the table uses `asset_uid` as the one-to-one primary
  key, has no separate `uid`, and points at `AssetTable.uid` with cascade
  delete.
- [ ] Add registration-request tests proving pricing models build in dependency
  order for platform-managed and external-registered modes.
- [ ] Add `msm_pricing.api.pricing_details.AssetCurrentPricingDetails` plus
  create, upsert, and update payload models.
- [ ] Expose `uid` as a Pydantic alias for `asset_uid` in the row model.
- [ ] Make the row API require `[AssetTable, AssetCurrentPricingDetailsTable]`
  and upsert by `asset_uid`.
- [ ] Add API tests for payload validation, `uid` alias behavior, runtime
  resolution, and upsert operation values.
- [ ] Add bond-focused helpers under `msm_pricing.persistence` that serialize an
  `InstrumentModel` into the pricing row API.
- [ ] Validate at least one fixed-rate bond round trip:
  `InstrumentModel -> instrument_dump -> AssetCurrentPricingDetails ->
  InstrumentModel.rebuild(...)`.
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
- [ ] Add `msm_pricing.engines` and `msm_pricing.indices` packages.
- [ ] Move internal imports from runtime-oriented `msm_pricing.models.*` modules
  to the new runtime package paths.
- [ ] Keep old runtime import paths as compatibility shims or document the
  breaking import change.
- [ ] Update `src/msm_pricing/README.md`, `docs/knowledge/pricing/index.md`,
  and ADR 0005 references to prefer `engines` and `indices` over runtime
  helpers under `models`.
- [ ] Run `git diff --check`.
- [ ] Run focused tests for pricing DataNodes, pricing MetaTables, pricing API,
  and pricing import compatibility.
- [ ] Run `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`
  after docs navigation updates.
