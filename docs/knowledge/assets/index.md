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
- `msm.api.assets`: user-facing Pydantic rows and typed class operations for
  `Asset`, `AssetMasterList`, `AssetCategory`, `AssetCategoryMembership`, and
  `OpenFigiDetails`.
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

Use Pydantic row models in `msm.api.assets` for normal application workflows.
They expose class methods over the active markets runtime and return typed
objects.

```python
from msm.api.assets import Asset

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
# Asset.delete(asset.uid)
```

Production code normally assumes the `Asset` MetaTable is already registered.
The first row operation attaches to the existing table and caches that runtime
for the process. If the table is missing, the row API raises with instructions
to run explicit startup preflight or to enable development auto-registration.

Example and test workflows that need isolated MetaTables can opt into
self-registration by setting `MSM_AUTO_REGISTER_NAMESPACE` before importing
`msm.api` row classes:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)

from msm.api.assets import Asset

asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)
```

The namespace is part of runtime/table registration, not an asset payload field.
Explicit bootstrap remains available for controlled startup preflight:
`Asset.create_schemas(...)` registers only the `Asset` dependency set, while
`msm.create_schemas(models=[...])` can register a selected multi-table set.

Use `runtime.context` or `runtime.table(...)` for lower-level multi-table
repository operations that need to compile statements across registered models.

Prefer `Asset.upsert(...)` in setup scripts and repeatable examples because it
is safe to rerun for the same `unique_identifier`. Use lower-level
`create_asset(...)` only when a duplicate asset should fail the workflow.

Use `AssetCategory` and `AssetCategoryMembership` when the universe itself is a
named reusable object:

```python
from msm.api.assets import Asset, AssetCategory

btc = Asset.upsert(unique_identifier="BTC", asset_type="crypto")
eth = Asset.upsert(unique_identifier="ETH", asset_type="crypto")
category = AssetCategory.upsert(
    unique_identifier="crypto-majors",
    display_name="Crypto Majors",
)
memberships = AssetCategory.replace_memberships(
    category_uid=category.uid,
    asset_uids=[btc.uid, eth.uid],
)
```

Use `OpenFigiDetails.upsert(...)` for typed provider metadata rows when the
asset row already exists. Provider services may still build `AssetTable` or
`OpenFigiDetailsTable` instances internally when authoring SQLAlchemy schema
rows.

Do not delete assets as part of the normal setup path. Only use cleanup for
temporary test assets or custom organization-owned records. Public or shared
mastered assets should be treated as reference data; remove category memberships
or downstream references instead of deleting the canonical identity row.

See `examples/assets/asset_crud_workflow.py` for a focused example that creates
temporary custom assets, resolves `BBG00FNFPQH4` through OpenFIGI, registers the
returned provider details, writes an example AssetSnapshot frame, searches by
type, and lists the created assets. FIGI resolution requires the Main Sequence
secret `OPEN_FIGI_API_KEY`; create it in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before running the
example. The example only registers the `Asset` and `OpenFigiDetails` MetaTables
and cleanup is opt-in through `--delete-temporary-assets`.

## Asset Snapshots

`AssetSnapshot` stores timestamped asset display facts as a DataNode. It should
not be modeled as fields on the `Asset` MetaTable. Use DataNode methods to build
validated frames or configure the node. Node construction and row loading are
separate so the DataNode owns table identity while each snapshot row owns its
own timestamp:

```python
from datetime import datetime, UTC

from msm.data_nodes.assets import AssetSnapshot

snapshot_node = AssetSnapshot().set_snapshots(
    {
        "time_index": datetime.now(UTC),
        "unique_identifier": "example-asset-btc",
        "ticker": "BTC",
    },
)
snapshot_frame = snapshot_node.run(debug_mode=True, force_update=True)
```

Markets resources derive their identifiers from the same runtime namespace rule.
With no environment override, or when the namespace is the default markets
namespace, logical identifiers stay bare, such as `Asset` and
`asset_snapshots`. When
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` is set before import,
`Asset` resolves to `mainsequence.examples.Asset` and
`AssetSnapshot.__data_node_identifier__ = "asset_snapshots"` resolves to
`mainsequence.examples.asset_snapshots`. The DataNode `hash_namespace` also
defaults to the active runtime namespace. Pass an explicit `hash_namespace` only
for isolated experiments or tests.

`AssetSnapshot` and `AssetPricingDetail` configurations declare a canonical
source-table foreign key from their `unique_identifier` record to
`AssetTable.unique_identifier`. The `Asset` MetaTable must be registered before
source-table initialization resolves that FK.
Their schemas are declared as `RecordDefinition` lists on
`AssetSnapshotConfiguration` and `AssetPricingDetailConfiguration`, not as
parallel dtype, label, and description maps.

Before an `AssetSnapshot` run persists rows, it queries the backend and rejects
any incoming `(time_index, unique_identifier)` tuple that already exists. Use a
new `time_index` when publishing a revised snapshot for the same asset.

See `examples/assets/asset_snapshot_workflow.py` for a focused AssetSnapshot
DataNode example that uses the default markets DataNode namespace.

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
