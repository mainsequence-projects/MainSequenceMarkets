# 0007. AssetIndexedDataNode Asset Foreign Keys

## Status

Proposed

## Context

`MarketDataNode` currently declares the asset identity dimension locally:

```python
ASSET_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"
```

That string is not only a DataNode dimension. It is also the canonical business
key on the markets `Asset` MetaTable. Keeping it local to
`markets_data_node.py` makes it too easy for DataNodes, service helpers, and
MetaTable code to drift.

The class name is also too broad. The current base does not define all market
DataNode semantics; it defines DataNode behavior indexed or scoped by asset
identity. A name such as `MarketDataNode` makes non-asset-indexed market
datasets look like they should inherit asset-specific range-map and
`asset_list` behavior.

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
registered or initialized. Adding them late inside `MarketDataNode` would hide a
storage-hash input and make failures appear only at source-table initialization.

## Decision

Create a general markets settings module and move the asset identity dimension
there:

```python
ASSET_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"
```

Use that constant everywhere a markets DataNode, asset-scope helper, or Asset
MetaTable-facing service needs the canonical asset identity field.

Rename the asset-scoped base concepts to describe what they actually do:

```text
MarketDataNodeConfiguration -> AssetIndexedDataNodeConfiguration
MarketDataNode              -> AssetIndexedDataNode
```

Keep `MarketDataNodeConfiguration` and `MarketDataNode` as compatibility aliases
for one release cycle if needed, but new code should use the asset-indexed names.

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
canonical `unique_identifier` column. `AssetIndexedDataNodeConfiguration` should
own asset-indexed runtime scope such as `asset_list` and the canonical Asset FK.
Non-asset-indexed market DataNodes should use a separate, smaller base or the SDK
`DataNodeConfiguration` directly.

## Plan

1. Add `src/msm/settings.py` with `ASSET_UNIQUE_IDENTIFIER_DIMENSION`.
2. Introduce `src/msm/asset_indexed_data_node.py` with
   `AssetIndexedDataNodeConfiguration` and `AssetIndexedDataNode`.
3. Keep `src/msm/markets_data_node.py` as a compatibility shim that imports and
   re-exports the new names under the old names, then remove that shim in a
   later breaking release.
4. Replace local hard-coded asset identity constants in asset-indexed DataNode
   code, `asset_scope.py`, and asset DataNode contracts with the settings
   constant.
5. Add a helper, for example
   `asset_unique_identifier_foreign_key()`, that returns the canonical
   `SourceTableForeignKey` to `AssetTable.unique_identifier`.
6. Add an asset-indexed DataNode configuration base or mixin that:
   - requires `records`;
   - verifies the canonical asset identity record exists;
   - supplies the canonical Asset foreign key by default;
   - preserves any additional explicit foreign keys declared by a concrete
     DataNode.
7. Migrate DataNodes whose persisted table identity is truly
   `(time_index, unique_identifier)` to that configuration path first:
   - `AssetSnapshot`;
   - `AssetPricingDetail`;
   - market price/curve nodes that use canonical asset identity.
8. Evaluate holdings and execution DataNodes separately:
   - holdings currently use additional owner dimensions such as `account_uid`
     or `fund_uid` and may still include `unique_identifier`;
   - execution DataNodes currently use fields such as `asset_unique_identifier`,
     which should not be silently treated as the canonical dimension until the
     schema is intentionally migrated.
9. Update imports in new code to use `AssetIndexedDataNode` and
   `AssetIndexedDataNodeConfiguration`. Existing imports from
   `msm.markets_data_node` remain temporarily valid through the compatibility
   shim.
10. Update examples so `msm.create_schemas(models=["Asset", ...])` runs before
   any DataNode source-table initialization that resolves the Asset FK.
11. Add tests that prove:
   - the settings constant is the only source for the asset identity dimension;
   - asset-indexed DataNode configs include one FK to `AssetTable.unique_identifier`;
   - FK source columns are present in `records`;
   - DataNode frame validation still enforces the expected index shape;
   - non-asset-indexed DataNodes do not receive a hidden Asset FK.

## Consequences

This makes the DataNode-to-Asset relationship part of the published table
contract. For already-published DataNodes, adding the FK may rotate the storage
hash because SDK foreign keys participate in storage hashing. Migrations must
therefore be handled as a deliberate table-contract change, not as a silent
runtime patch.

The Asset MetaTable must be registered before asset-indexed DataNode source
tables are initialized. Example workflows that use `mainsequence.examples` must
configure that namespace before importing `msm.models`, then register the
`Asset` MetaTable through `msm.create_schemas(...)`.

Using `on_delete="restrict"` prevents deleting canonical assets while historical
DataNode rows still reference them. Cleanup workflows should remove dependent
DataNode/source-table state explicitly before deleting an asset identity.

Runtime injection remains rejected because it would obscure hash material,
produce late source-table initialization failures, and make custom DataNode
configurations harder to reason about.

The rename improves API readability but creates import churn. Keeping
compatibility aliases allows implementation to move without breaking users
immediately, while making the preferred name clear in docs and examples.
