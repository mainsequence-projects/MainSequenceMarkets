# Assets

The assets concept owns market asset identity. It connects external identifiers,
asset categories, snapshots, pricing details, and provider metadata into a
consistent Main Sequence representation.

## Scope

Assets answer these questions:

- What is the canonical `unique_identifier` for an asset?
- Which asset master list owns the asset?
- Which categories or category memberships describe the asset?
- Which snapshots and pricing details are attached to the asset?
- Which provider details, such as OpenFIGI metadata, were used to resolve it?

## Primary Modules

- `msm.models.assets`: SQLAlchemy/MetaTable asset model. The `Asset` model lives
  here.
- `msm.data_nodes.assets`: DataNodes for asset snapshots and asset pricing
  details.
- `msm.services.assets`: application-facing asset service helpers over
  repositories.
- `msm.services.assets.openfigi`: OpenFIGI query, normalization, and row-building
  helpers.
- `msm.models.asset_categories`: category and membership models.
- `msm.models.asset_master_lists`: asset master list model.
- `msm.models.provider_details`: provider metadata such as OpenFIGI details.
- `msm.repositories.assets`, `msm.repositories.asset_categories`, and
  `msm.repositories.provider_details`: MetaTable operation builders for asset
  control-plane records.

## Key Contracts

The asset `unique_identifier` is the stable handle used by portfolios, holdings,
pricing details, and market data. Category membership should describe asset
classification without changing identity.

Pricing details are not the same thing as market prices. Pricing details store
terms needed to rebuild priceable instruments, while price histories live in
market-data workflows.

## Creating, Querying, And Deleting Assets

Use the service helpers in `msm.services` for normal application workflows. They
compile operations against registered markets MetaTables and execute them through
the platform-controlled MetaTable API.

```python
from msm.services import (
    delete_asset,
    get_asset_by_uid,
    get_asset_by_unique_identifier,
    search_assets,
    upsert_asset,
)


asset = upsert_asset(
    context,
    unique_identifier="example-asset-btc",
    asset_type="crypto",
    metadata_json={"ticker": "BTC", "source": "example"},
)
asset_by_identifier = get_asset_by_unique_identifier(
    context,
    unique_identifier="example-asset-btc",
)
asset_by_uid = get_asset_by_uid(context, uid=asset["uid"])
crypto_assets = search_assets(
    context,
    unique_identifier_contains="example-asset-",
    asset_type="crypto",
)
delete_asset(context, uid=asset["uid"])
```

Prefer `upsert_asset(...)` in setup scripts and repeatable examples because it is
safe to rerun for the same `unique_identifier`. Use `create_asset(...)` only when
a duplicate asset should fail the workflow.

Only delete assets that the current workflow owns, such as temporary test assets
or custom organization-owned records. Public or shared mastered assets should be
treated as reference data; remove category memberships or downstream references
instead of deleting the canonical identity row.

See `examples/assets/asset_crud_workflow.py` for a focused example that creates
temporary custom assets, queries them by identifier and UID, searches by type,
and deletes one of the temporary rows.

## Extension Notes

Add new DataNode schemas under `msm.data_nodes.assets` when the output is
time-indexed market data. Add provider-specific lookup or normalization under a
service submodule such as `msm.services.assets.openfigi`. Add new persistent
fields in `msm.models` only when the platform schema needs to own the field.

There is intentionally no `msm.assets` package boundary. Asset identity belongs
to MetaTable models and repositories, timestamped asset facts belong to
DataNodes, and external provider integration belongs to services.

See [AssetMasterList](asset_master_lists.md) for the control-plane reference
table contract.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Portfolios](../portfolios/index.md)
- [Pricing](../pricing/index.md)
- [Platform](../platform/index.md)
