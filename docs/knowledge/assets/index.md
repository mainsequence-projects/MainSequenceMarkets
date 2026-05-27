# Assets

The assets concept owns market asset identity. `Asset` is the user-facing API
model for registering and querying canonical market assets. It connects external
identifiers, asset categories, snapshots, pricing details, and provider metadata
into a consistent Main Sequence representation.

Most application code should work with `msm.api.assets.Asset`. That Pydantic row
model is backed by `msm.models.assets.AssetTable`, the SQLAlchemy MetaTable
schema declaration used for platform registration and compiled SQL operations.
Use `AssetTable` when authoring schema, repository, or registration code; use
`Asset` when application code needs to create, upsert, filter, update, or delete
asset rows.

## Asset Model

`AssetTable` is intentionally small. It is the asset registry, not the place to
store every instrument-specific field. The stable identity fields are:

- `uid`: internal row identity used by relational detail tables.
- `unique_identifier`: the canonical public handle for the asset.
- `asset_type`: a short classification string, such as `crypto`, `equity`, or
  `binance_future_usdm`.

`AssetType` is the type registry. Register an `asset_type` before using it in
new asset workflows so the meaning of the string is discoverable. In the current
schema, `Asset.asset_type` is a string classification field whose values should
match rows in `AssetType`; it is not a database foreign key in this release.

```text
+-----------------------------+        logical value        +-----------------------------+
| AssetType                   |<----------------------------| Asset                       |
|-----------------------------|                             |-----------------------------|
| uid                         |                             | uid                         |
| asset_type        unique    |                             | unique_identifier unique    |
| display_name                |                             | asset_type                  |
| description                 |                             +-----------------------------+
| metadata_json               |
+-----------------------------+
```

The intended extension model is relational composition. Do not extend
`AssetTable` by adding columns such as maturity, strike, expiry, issuer, or
venue-specific payloads. Instead, add a detail table with a foreign key to the
asset row and keep the core `AssetTable` stable.

Example extension shape for futures:

```text
+-----------------------------+        one asset may have       +-----------------------------+
| AssetTable                  |-------------------------------->| FutureAssetDetailsTable     |
|-----------------------------|        asset_uid FK             |-----------------------------|
| uid                  PK     |                                 | uid                  PK     |
| unique_identifier    unique |                                 | asset_uid            FK     |
| asset_type                 |                                 | exchange_code               |
+-----------------------------+                                 | contract_code               |
                                                                | maturity_date               |
                                                                | last_trade_date             |
                                                                | contract_size               |
                                                                | metadata_json               |
                                                                +-----------------------------+
```

A future-specific table like that would belong in an extension package or a
future `msm.models` module. Its public API should mirror the current pattern: a
SQLAlchemy `FutureAssetDetailsTable` for schema work and a Pydantic
`FutureAssetDetails` row model for application code.

## Scope

Assets answer these questions:

- What is the canonical `unique_identifier` for an asset?
- Which registered asset type classifies the asset?
- Which categories or category memberships describe the asset?
- Which snapshots and pricing details are attached to the asset?
- Which provider details, such as OpenFIGI metadata, were used to resolve it?

## Primary Modules

- `msm.models.assets`: SQLAlchemy/MetaTable declaration. The `AssetTable`
  schema model lives here.
- `msm.models.asset_types`: asset type registry model.
- `msm.api.assets`: user-facing Pydantic rows and typed class operations for
  `Asset`, `AssetType`, `AssetCategory`, `AssetCategoryMembership`, and
  `OpenFigiDetails`.
- `msm.data_nodes.assets`: DataNodes for asset snapshots and asset pricing
  details.
- `msm.services.assets`: application-facing asset service helpers over
  repositories.
- `msm.services.assets.openfigi`: OpenFIGI query, normalization, and row-building
  helpers.
- `msm.models.asset_categories`: category and membership models.
- `msm.models.provider_details`: provider metadata such as OpenFIGI details.
- `msm.repositories.assets`, `msm.repositories.asset_categories`, and
  `msm.repositories.provider_details`: MetaTable operation builders for asset
  control-plane records.

## Key Contracts

The asset `unique_identifier` is the stable handle used by portfolios, holdings,
pricing details, and market data. Category membership should describe asset
classification without changing identity.

`AssetType` records a unique `asset_type`, optional `display_name`, optional
`description`, and optional `metadata_json`. Use it as a lightweight registry of
what each type string means in a namespace.

Pricing details are not the same thing as market prices. Pricing details store
terms needed to rebuild priceable instruments, while price histories live in
market-data workflows.

## Creating, Querying, And Deleting Assets

Use Pydantic row models in `msm.api.assets` for normal application workflows.
They expose class methods over the active markets runtime and return typed
objects.

```python
from msm.api.assets import Asset, AssetType

AssetType.upsert(
    asset_type="crypto",
    display_name="Crypto",
    description="Crypto spot and token assets.",
)

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

When a workflow owns startup preflight, register the required MetaTables before
row operations run:

```python
import msm

runtime = msm.create_schemas(models=["AssetType", "Asset"])
asset_table_handle = runtime.table("Asset")
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
temporary custom assets, registers asset types, resolves `BBG00FNFPQH4` through
OpenFIGI, registers the returned provider details, writes an example
AssetSnapshot frame, searches by type, and lists the created assets. FIGI
resolution requires the Main Sequence secret `OPEN_FIGI_API_KEY`; create it in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before running the
example. Cleanup is opt-in through `--delete-temporary-assets`.

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

## Related Concepts

- [Accounts](../accounts/index.md)
- [Portfolios](../portfolios/index.md)
- [Pricing](../pricing/index.md)
- [Platform](../platform/index.md)
