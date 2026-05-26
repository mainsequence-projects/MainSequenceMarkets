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

- `msm.models.assets`: SQLAlchemy/MetaTable declaration. The `AssetTable`
  schema model lives here.
- `msm.api.assets`: user-facing Pydantic `Asset` row model and typed class
  operations.
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

Use the Pydantic row model in `msm.api.assets` for normal application workflows.
It exposes class methods over the active markets runtime and returns typed
`Asset` objects.

```python
from msm.api.assets import Asset

Asset.create_schemas()
asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)
asset_by_identifier = Asset.get_by_unique_identifier(
    unique_identifier="example-asset-btc",
)
asset_by_uid = Asset.get_by_uid(asset.uid)
crypto_assets = Asset.filter(
    unique_identifier_contains="example-asset-",
    asset_type="crypto",
)
# Optional cleanup for temporary custom assets only:
# from msm.services import delete_asset
# delete_asset(msm.get_runtime().table("Asset"), uid=asset.uid)
```

Production code normally calls `msm.create_schemas()` once during process
initialization without a runtime namespace override. Example and test workflows
that need isolated MetaTables add the namespace during initialization. For
asset-only workflows, register only the `Asset` MetaTable and pass the returned
single-table handle into lower-level repository or service helpers. For the
typed API, the row model can initialize its own required schemas:

```python
from examples.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE
from msm.api.assets import Asset

Asset.create_schemas(
    namespace=EXAMPLE_METATABLE_NAMESPACE,
)
asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)
```

The namespace is part of runtime/table registration, not an asset payload field,
and row operations never create schemas implicitly. If `Asset.upsert(...)` is
called before `Asset.create_schemas(...)` or `msm.create_schemas(...)`, it raises
with bootstrap guidance.

Use `runtime.context` or `runtime.table(...)` for lower-level multi-table
repository operations that need to compile statements across registered models.

Prefer `Asset.upsert(...)` in setup scripts and repeatable examples because it
is safe to rerun for the same `unique_identifier`. Use lower-level
`create_asset(...)` only when a duplicate asset should fail the workflow.

Do not delete assets as part of the normal setup path. Only use cleanup for
temporary test assets or custom organization-owned records. Public or shared
mastered assets should be treated as reference data; remove category memberships
or downstream references instead of deleting the canonical identity row.

See `examples/assets/asset_crud_workflow.py` for a focused example that creates
temporary custom assets, registers OpenFIGI details for `BBG00FNFPQH4`, writes an
example AssetSnapshot frame, searches by type, and lists the created assets. The
example only registers the `Asset` and `OpenFigiDetails` MetaTables and cleanup
is opt-in through `--delete-temporary-assets`.

## Asset Snapshots

`AssetSnapshot` stores timestamped asset display facts as a DataNode. It should
not be modeled as fields on the `Asset` MetaTable. Use service helpers to build
validated frames or a configured DataNode:

```python
from msm.services import build_asset_snapshot_node

snapshot_node = build_asset_snapshot_node(
    {"unique_identifier": "example-asset-btc", "ticker": "BTC"},
    identifier="examples.mainsequence.markets.asset_snapshots",
    hash_namespace="examples",
)
snapshot_frame = snapshot_node.update()
```

See `examples/assets/asset_snapshot_workflow.py` for a focused AssetSnapshot
DataNode example that uses an example-scoped identifier.

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
