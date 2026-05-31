# Asset-Indexed DataNodes

`AssetIndexedDataNode` is the markets-specific base class for DataNodes whose
rows are keyed by a Main Sequence market asset. It keeps asset identity out of
core MainSequence behavior while giving market datasets a consistent asset dimension,
asset scoping API, namespace behavior, and source-table relationship to
`AssetTable`.

Use this page for timestamped asset facts such as snapshots, pricing details,
prices, signals, weights, holdings, or any table whose natural row identity is
`(time_index, unique_identifier)`.

## How It Differs From A Normal DataNode

A normal Main Sequence `DataNode` is a generic data product. It owns a stable
published dataset contract, update logic, persistence, hashing, dependencies,
and orchestration behavior. It does not know that one of its dimensions is a
market asset.

`AssetIndexedDataNode` adds the market layer:

- the canonical asset dimension is `unique_identifier`;
- `asset_list` is an optional updater scope, not table meaning;
- `get_asset_list()` validates string, mapping, or object asset scopes;
- asset scopes can be translated into DataNode `dimension_filters`;
- per-asset update ranges are exposed through helpers such as
  `get_asset_dimension_range_map_great_or_equal(...)`;
- the default `hash_namespace` follows the active markets namespace;
- the registered storage class declares a foreign key from `unique_identifier` to
  `AssetTable.unique_identifier`.

```text
+-----------------------------+           generic DataNode        +-----------------------------+
| mainsequence.meta_tables.   |---------------------------------->| TimeIndexMetaData storage   |
| DataNode                    |                                   | registered from storage cls |
|-----------------------------|                                   |-----------------------------|
| storage_hash                |                                   | published table             |
| update_hash                 |                                   | schema / records            |
| dependencies()              |                                   | update history              |
| update()                    |                                   +-----------------------------+
+-----------------------------+
              ^
              |
              | adds markets asset conventions
              |
+-----------------------------+           asset-indexed          +-----------------------------+
| AssetIndexedDataNode        |---------------------------------->| AssetTable                  |
|-----------------------------|       unique_identifier FK        |-----------------------------|
| asset_identity_dimension    |                                   | unique_identifier unique    |
| asset_list update scope     |                                   | asset_type                  |
| dimension filter helpers    |                                   +-----------------------------+
| per-asset range helpers     |
+-----------------------------+
```

The important distinction is identity. A generic DataNode can publish any table
shape. An asset-indexed DataNode publishes a market table where
`unique_identifier` is expected to mean an `Asset.unique_identifier` value.

## Core Contract

Asset-indexed tables should follow this shape unless a specific dataset has a
documented reason not to:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| AssetIndexedDataNode table  |--------------------------->| AssetTable                  |
|-----------------------------| unique_identifier          |-----------------------------|
| time_index           index  |                            | uid                         |
| unique_identifier    index  |                            | unique_identifier unique    |
| value columns               |                            | asset_type                  |
+-----------------------------+                            +-----------------------------+
```

The `unique_identifier` column should not be an arbitrary provider ticker. It
should be the same canonical identifier registered through `msm.api.assets.Asset`.
Provider-specific tickers, FIGIs, ISINs, symbols, and raw payloads belong either
in provider detail tables, such as `OpenFigiAssetDetailsTable`, or in DataNode value
columns when the table is explicitly a timestamped provider fact.

The `AssetIndexedDataNodeConfiguration.asset_list` field is updater scope. Asset
universe selection affects update identity, not the storage identity of the
published dataset. Two updater jobs can write different asset subsets into the
same dataset when the schema and dataset meaning are otherwise the same.

## Canonical Foreign Key

Under ADR 0017 the schema contract lives on a storage class
(`PlatformTimeIndexMetaData` / `MarketsTimeIndexMetaTableMixin`), not on the
DataNode configuration. The canonical asset foreign key is a SQLAlchemy
`ForeignKey` column from `unique_identifier` to `AssetTable.unique_identifier` on
that storage class. The DataNode uses its storage class through
`_required_storage_table()`.

```python
import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.data_nodes.assets.asset_indexed import AssetIndexedDataNode
from msm.models.assets.core import AssetTable


class ExampleAssetMetricStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    __markets_base_identifier__ = "example_asset_metrics"
    __metatable_description__ = (
        "Timestamped asset metric observations keyed by asset unique identifier "
        "for market analytics and portfolio workflows."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time", "description": "UTC observation timestamp."},
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={"label": "Asset", "description": "Asset unique identifier from AssetTable."},
    )
    metric_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Metric Value", "description": "Example asset metric."},
    )


class ExampleAssetMetric(AssetIndexedDataNode):
    @classmethod
    def _required_storage_table(cls) -> type[ExampleAssetMetricStorage]:
        return ExampleAssetMetricStorage

    def dependencies(self) -> dict:
        return {}
```

Register the storage class through the catalog bootstrap (add it to the markets
model registry returned by `markets_sqlalchemy_models()`, or pass it to
`msm.start_engine(models=[...])`) so the `Asset` MetaTable is registered before
this table's foreign key resolves. Construction requires a storage class that
has been registered through `PlatformTimeIndexMetaData.register(...)`; do not
manually bind storage by UID or reconstruct a generic `MetaTable`.

Use `__metatable_description__` for durable table discovery text. The description
should explain the market intention, row grain, and downstream use of the
asset-indexed dataset, not only list its columns.

## AssetSnapshot

`AssetSnapshot` is the live implementation of the asset-indexed pattern in
`msm.data_nodes.assets`. Its implementation lives in
`msm.data_nodes.assets.snapshots`, while the package re-exports the public
classes for normal user imports. It stores timestamped display facts about an asset,
such as name, ticker, exchange code, and share-class grouping. These are not
columns on `AssetTable` because they can change through time and can differ by
provider or observation date.

```text
+-----------------------------+      canonical FK        +-----------------------------+
| AssetSnapshot DataNode      |------------------------->| AssetTable                  |
|-----------------------------| unique_identifier        |-----------------------------|
| time_index           index  |                          | unique_identifier unique    |
| unique_identifier    index  |                          | asset_type                  |
| name                        |                          +-----------------------------+
| ticker                      |
| exchange_code               |
| asset_ticker_group_id       |
+-----------------------------+
```

`AssetSnapshotsStorage` (in `msm.data_nodes.storage`) declares the persisted
schema as SQLAlchemy mapped columns and owns the canonical
`unique_identifier -> AssetTable.unique_identifier` foreign key. `AssetSnapshot`
uses it through `_required_storage_table()`.

## Register Assets Before Publishing Snapshots

Asset snapshots should refer to assets that already exist in `AssetTable`.
Application code normally registers the asset type and asset through the typed
row API before running an asset-indexed DataNode.

```python
import msm

from msm.api.assets import Asset, AssetType

msm.start_engine(models=["AssetType", "Asset"])

AssetType.upsert(asset_type="crypto", display_name="Crypto")
Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
```

For explicit startup preflight, register the required MetaTable before source
table initialization:

```python
import msm

runtime = msm.start_engine(models=["Asset"])
```

Examples that use `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` inherit
the same namespace for both markets MetaTables and default markets DataNode
hash namespaces.

## Building And Running AssetSnapshot

Use `AssetSnapshot.build_frame(...)` when you want local frame validation, and
`AssetSnapshot().set_snapshots(...)` when you want to attach rows to a node before
running it.

```python
from datetime import UTC, datetime

from msm.data_nodes.assets import AssetSnapshot

snapshots = [
    {
        "time_index": datetime.now(UTC),
        "unique_identifier": "example-asset-btc",
        "name": "Bitcoin",
        "ticker": "BTC",
        "exchange_code": "CRYPTO",
        "asset_ticker_group_id": "crypto-majors",
    }
]

snapshot_frame = AssetSnapshot.build_frame(snapshots)
snapshot_node = AssetSnapshot().set_snapshots(snapshots)
result_frame = snapshot_node.run(debug_mode=True, force_update=True)
```

Each snapshot row must carry its own `time_index`. `AssetSnapshot` validates the
frame, normalizes timestamps to `datetime64[ns, UTC]`, sets the
`["time_index", "unique_identifier"]` MultiIndex, and rejects duplicate keys
inside the frame.

Before a run persists rows, `AssetSnapshot` checks the backend for existing
`(time_index, unique_identifier)` keys and fails if any incoming key already
exists. Publish corrections as a new timestamped snapshot instead of overwriting
the previous observation.

## Shared Stamped Base

Timestamped reference-data facts share the same frame mechanics whether the
reference row is an asset or an index. Non-model-specific DataNode helpers live
under `msm.data_nodes.utils`; the generic stamped base lives in
`msm.data_nodes.utils.stamped`:

- `StampedFrameMixin` owns real frame binding, validation, and
  `datetime64[ns, UTC]` normalization — all sourced from the registered
  `storage_table` (`__table__.columns`, `__index_names__`,
  `__time_index_name__`). It does not create placeholder rows for schema
  registration.
- `StampedDataNode` owns the empty dependency default and the markets
  `hash_namespace` defaulting rule, and resolves its storage class through
  `_required_storage_table()`.

Asset-specific classes live under `msm.data_nodes.assets` and use storage
classes that add the `AssetTable.unique_identifier` foreign key. Index-specific
classes live under `msm.data_nodes.indices` and reuse the same stamped base with
storage classes carrying the `IndexTable.unique_identifier` foreign key. Shared
utility modules such as `msm.data_nodes.utils.stamped` and
`msm.data_nodes.utils.namespaces` stay concept-neutral and do not sit beside
model-specific packages at the `msm.data_nodes` root.

## Namespaces And Identifiers

Markets DataNodes use the same namespace rule as markets MetaTables because
their default identifiers derive from their storage classes. With the default
markets namespace, logical identifiers stay bare, such as `Asset` and
`asset_snapshots`. With
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`, `Asset` resolves to
`mainsequence.examples.Asset`, while
`AssetSnapshot._default_identifier()` derives from
`AssetSnapshotsStorage.metatable_identifier()` and resolves to
`mainsequence.examples.asset_snapshots`.

The default DataNode `hash_namespace` also follows the active markets namespace.
Pass an explicit `hash_namespace` only for isolated experiments, tests, or
parallel runs that must not collide on a shared backend.

## Related Code

- `src/msm/data_nodes/assets/asset_indexed.py`: base class, asset scope validation,
  namespace behavior, asset dimension filters, and per-asset update range helpers.
- `src/msm/data_nodes/storage.py`: storage classes (including
  `AssetSnapshotsStorage`) that own the schema, dtypes, and canonical `AssetTable`
  foreign keys.
- `src/msm/data_nodes/utils/stamped.py`: shared timestamped frame behavior
  validated against the registered `storage_table`.
- `src/msm/data_nodes/utils/storage_schema.py`: derives column dtype maps from a
  storage class via the SDK `dtype_codec`.
- `src/msm/data_nodes/utils/namespaces.py`: shared markets hash-namespace
  defaulting for DataNodes.
- `src/msm/data_nodes/assets/snapshots.py`: `AssetSnapshot`,
  `AssetDataNodeConfiguration`, and timestamped asset frame validation.
- `src/msm/data_nodes/indices/timestamped.py`: `IndexTimestampedDataNode` and
  `IndexDataNodeConfiguration` for timestamped facts keyed to `IndexTable`.
- `src/msm_pricing/data_nodes/pricing_details.py`: `AssetPricingDetail` and
  its pricing-specific configuration.
- `examples/assets/asset_crud_workflow.py`: asset workflow that includes
  `AssetSnapshot` frame construction and DataNode execution.
- `docs/ADR/0017-storage-first-data-node-architecture.md`: storage-first DataNode
  architecture (supersedes ADR 0007's DataNode-side asset foreign keys).
