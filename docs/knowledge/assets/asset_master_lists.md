# AssetMasterList

`AssetMasterList` is the control-plane pointer for the authoritative asset
reference table. It does not duplicate the asset catalog. It records which
MetaTable should be treated as the source of valid asset identities.

The referenced MetaTable must expose a unique `unique_identifier` column. The
validation helpers check that contract before creating the `AssetMasterList`
row.

```python
from msm.services import create_validated_asset_master_list


asset_master_list = create_validated_asset_master_list(
    context,
    reference_meta_table=reference_meta_table,
    unique_identifier="default-assets",
    name="Default Assets",
    description="Primary asset reference table for this workspace.",
    is_default=True,
)
```

Use `resolve_asset_master_list(context)` when workflows need the default list.
Use `validate_asset_master_list_reference_meta_table(...)` when a UI or setup
job needs to validate a candidate table before saving it.

This design keeps asset reference ownership flexible. The reference table can be
the `msm.models.AssetTable` MetaTable, a platform-managed table, or an
externally registered table created by the application, as long as it satisfies
the asset identity contract.
