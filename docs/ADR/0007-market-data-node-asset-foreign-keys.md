# 0007. AssetIndexedDataNode Asset Foreign Keys

## Status

Accepted

## Context

The previous broad market DataNode base declared the asset identity dimension
locally:

```python
ASSET_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"
```

That string is not only a DataNode dimension. It is also the canonical business
key on the markets `Asset` MetaTable. Keeping it local to
the asset-scoped DataNode module made it too easy for DataNodes, service
helpers, and MetaTable code to drift.

The class name is also too broad. The current base does not define all market
DataNode semantics; it defines DataNode behavior indexed or scoped by asset
identity. A broad market DataNode name makes non-asset-indexed market datasets
look like they should inherit asset-specific range-map and `asset_list`
behavior.

The Main Sequence SDK now supports source-table foreign keys for DataNodes
through `SourceTableForeignKey` declarations on `DataNodeConfiguration`.
Important SDK behavior:

- `DataNodeConfiguration` has an optional `foreign_keys` field.
- `SourceTableForeignKey` is the authoring model. It accepts a target MetaTable
  object/model, source columns, target columns, and `on_delete`.
- The SDK resolves the authoring model to backend
  `SourceTableForeignKeyContract` payloads during DataNode source-table
  initialization.
- `SourceTableForeignKey.source_columns` must exist in
  `DataNodeConfiguration.records`.
- Foreign keys participate in the DataNode storage hash.

That means foreign keys should be visible in configuration before a DataNode is
registered or initialized. Adding them late inside a base DataNode would hide a
storage-hash input and make failures appear only at source-table
initialization.

## Decision

Create a general markets settings module and move the asset identity dimension
there:

```python
ASSET_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"
```

Use that constant everywhere a markets DataNode, asset-scope helper, or Asset
MetaTable-facing service needs the canonical asset identity field.

Use asset-scoped base concepts that describe what they actually do:

```text
AssetIndexedDataNodeConfiguration
AssetIndexedDataNode
```

Do not keep broad compatibility aliases. New and existing library code should
use the asset-indexed names directly.

Do not inject DataNode foreign keys by catching arbitrary configurations at
runtime. Instead, make the foreign-key declaration part of the explicit DataNode
configuration for asset-indexed market tables.

The canonical DataNode-to-Asset relationship is:

```text
DataNode source column: unique_identifier
Asset target column:   AssetTable.unique_identifier
on_delete:             restrict
```

The target is `AssetTable.unique_identifier`, not `AssetTable.uid`, because markets
DataNode rows already persist the stable asset identity dimension. Adding
`asset_uid` to time-series rows would duplicate identity and create another
resolution step for normal DataNode reads.

The implementation should introduce a reusable configuration/helper layer for
asset-indexed market DataNodes. The intended shape is:

```python
from mainsequence.tdag import SourceTableForeignKey

from msm.models import AssetTable
from msm.settings import ASSET_UNIQUE_IDENTIFIER_DIMENSION

SourceTableForeignKey(
    target=AssetTable,
    source_columns=[ASSET_UNIQUE_IDENTIFIER_DIMENSION],
    target_columns=[AssetTable.unique_identifier],
    on_delete="restrict",
)
```

The helper must only apply to DataNodes whose persisted records include the
canonical `unique_identifier` column. `AssetIndexedDataNodeConfiguration` owns
asset-indexed runtime scope such as `asset_list`, while concrete configurations
that persist canonical asset rows add the Asset FK during configuration
validation. This avoids silently adding an Asset FK through the temporary
shared base to holdings, execution, or other schemas that need separate review.

## Implementation Tasks

1. [x] Add `src/msm/settings.py` with
   `ASSET_UNIQUE_IDENTIFIER_DIMENSION`.
2. [x] Introduce `src/msm/data_nodes/assets/asset_indexed.py` with
   `AssetIndexedDataNodeConfiguration` and `AssetIndexedDataNode`.
3. [x] Remove the old compatibility shim and broad aliases.
4. [x] Replace local hard-coded asset identity constants in
   `msm.data_nodes.assets` and `msm.portfolios.asset_scope` with the settings constant.
5. [x] Add `asset_unique_identifier_foreign_key()` returning the canonical
   `SourceTableForeignKey` to `AssetTable.unique_identifier`.
6. [x] Add configuration validation for concrete asset DataNodes that requires
   `records`, verifies the canonical asset identity record exists, supplies the
   canonical Asset FK, and preserves additional explicit FKs.
7. [x] Migrate `AssetSnapshot` and `AssetPricingDetail` to the asset-indexed
   configuration path.
8. [ ] Migrate market price/curve nodes that use canonical
   `(time_index, unique_identifier)` identity.
9. [ ] Evaluate holdings and execution DataNodes separately before adding Asset
   FKs. Holdings use additional owner dimensions such as `account_uid` or
   `fund_uid`; execution uses fields such as `asset_unique_identifier`.
10. [x] Update asset-indexed DataNode code to import `AssetIndexedDataNode` and
   `AssetIndexedDataNodeConfiguration` directly.
11. [ ] Update examples so `msm.start_engine(models=["Asset", ...])` runs
   before any DataNode source-table initialization that resolves the Asset FK.
12. [x] Add tests proving the shared settings constant, canonical FK shape,
   record validation, frame validation, explicit-FK preservation, no hidden FK
   on the asset-indexed base, and removal of legacy compatibility imports.
13. [ ] Perform live platform source-table initialization verification after the
   project is authenticated.

## Consequences

This makes the DataNode-to-Asset relationship part of the published table
contract. For already-published DataNodes, adding the FK may rotate the storage
hash because SDK foreign keys participate in storage hashing. Migrations must
therefore be handled as a deliberate table-contract change, not as a silent
runtime patch.

The Asset MetaTable must be registered before asset-indexed DataNode source
tables are initialized. Example workflows that use `mainsequence.examples` must
configure that namespace before importing `msm.models`, then register the
`Asset` MetaTable through `msm.start_engine(...)`.

Using `on_delete="restrict"` prevents deleting canonical assets while historical
DataNode rows still reference them. Cleanup workflows should remove dependent
DataNode/source-table state explicitly before deleting an asset identity.

Runtime injection remains rejected because it would obscure hash material,
produce late source-table initialization failures, and make custom DataNode
configurations harder to reason about.

The rename improves API readability but creates import churn. Keeping
compatibility aliases allows implementation to move without breaking users
immediately, while making the preferred name clear in docs and examples.
