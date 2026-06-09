# Asset-Indexed DataNodes

`AssetIndexedDataNode` is the markets-specific base class for DataNodes whose
rows are keyed by a Main Sequence market asset. It keeps asset identity out of
core MainSequence behavior while giving market datasets a consistent asset dimension,
asset scoping API, namespace behavior, and source-table relationship to
`AssetTable`.

Use this page for timestamped asset facts such as snapshots, pricing details,
prices, signals, weights, holdings, or any table whose natural row identity is
`(time_index, asset_identifier)`.

## How It Differs From A Normal DataNode

A normal Main Sequence `DataNode` is a generic data product. It owns a stable
published dataset contract, update logic, persistence, hashing, dependencies,
and orchestration behavior. It does not know that one of its dimensions is a
market asset.

`AssetIndexedDataNode` adds the market layer:

- the canonical asset storage dimension is `asset_identifier`;
- `asset_list` is an optional updater scope, not table meaning;
- `get_asset_list()` validates string, mapping, or object asset scopes;
- asset scopes can be translated into DataNode `dimension_filters`;
- per-asset update ranges are exposed through helpers such as
  `get_asset_dimension_range_map_great_or_equal(...)`;
- the default `hash_namespace` follows the active markets namespace;
- the registered storage class declares a foreign key from `asset_identifier` to
  `AssetTable.unique_identifier`.

```text
+-----------------------------+           generic DataNode        +-----------------------------+
| mainsequence.meta_tables.   |---------------------------------->| TimeIndexMetaTable storage   |
| DataNode                    |                                   | registered from storage cls |
|-----------------------------|                                   |-----------------------------|
| storage_hash                |                                   | published table             |
| update_hash                 |                                   | schema / columns            |
| dependencies()              |                                   | update history              |
| update()                    |                                   +-----------------------------+
+-----------------------------+
              ^
              |
              | adds markets asset conventions
              |
+-----------------------------+           asset-indexed          +-----------------------------+
| AssetIndexedDataNode        |---------------------------------->| AssetTable                  |
|-----------------------------|       asset_identifier FK         |-----------------------------|
| asset_identity_dimension    |                                   | unique_identifier unique    |
| asset_list update scope     |                                   | asset_type                  |
| dimension filter helpers    |                                   +-----------------------------+
| per-asset range helpers     |
+-----------------------------+
```

The important distinction is identity. A generic DataNode can publish any table
shape. An asset-indexed DataNode publishes a market table where
`asset_identifier` contains an `Asset.unique_identifier` value.

## Core Contract

Asset-indexed tables should follow this shape unless a specific dataset has a
documented reason not to:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| AssetIndexedDataNode table  |--------------------------->| AssetTable                  |
|-----------------------------| asset_identifier           |-----------------------------|
| time_index           index  |                            | uid                         |
| asset_identifier     index  |                            | unique_identifier unique    |
| value columns               |                            | asset_type                  |
+-----------------------------+                            +-----------------------------+
```

The `asset_identifier` column should not be an arbitrary provider ticker. It
should contain the same canonical identifier registered through
`msm.api.assets.Asset.unique_identifier`. Provider-specific tickers, FIGIs,
ISINs, symbols, and raw payloads belong either in provider detail tables, such
as `OpenFigiAssetDetailsTable`, or in DataNode value columns when the table is
explicitly a timestamped provider fact.

The `AssetIndexedDataNodeConfiguration.asset_list` field is updater scope. Asset
universe selection affects update identity, not the storage identity of the
published dataset. Two updater jobs can write different asset subsets into the
same dataset when the schema and dataset meaning are otherwise the same.

Asset-scoped configuration has two categories:

- normal `DataNodeConfiguration` fields, which enter `update_hash`
- `ClassVar[...]` invariants, which are not Pydantic fields and do not enter
  `update_hash`

Use `Field(...)` for every config field, with a useful `description` and
`examples=[...]` when possible:

```python
from typing import ClassVar

from pydantic import Field

from mainsequence.meta_tables import DataNodeConfiguration


class AssetIndexedDataNodeConfiguration(DataNodeConfiguration):
    asset_list: list | None = Field(
        default=None,
        description=(
            "Optional asset unique identifier scope for this updater run. "
            "Changing it changes update identity, not table identity."
        ),
        examples=[["asset_us_equity_aapl", "asset_us_equity_msft"]],
    )
    asset_category_unique_identifier: str | None = Field(
        default=None,
        description=(
            "Optional asset category unique identifier used to resolve the "
            "updater asset universe."
        ),
        examples=["us_equities"],
    )
    reference_dimension: ClassVar[str] = "asset_identifier"
```

`asset_list` and `asset_category_unique_identifier` are fields because they
select the updater scope and must affect `update_hash`. `reference_dimension` is
a `ClassVar` because it is a fixed implementation invariant, not run
configuration.

Do not use legacy platform metadata markers such as `update_only`,
`runtime_only`, `ignore_from_storage_hash`, or `_ARGS_IGNORE_IN_STORAGE_HASH` to
remove DataNode config fields from hashing. There is no third asset-scope case:
if it is a config field, it is hashed; if it is not hashed, it must not be a
config field.

## Canonical Foreign Key

In the current storage-first architecture, the schema contract lives on a
storage class
(`PlatformTimeIndexMetaTable` / `MarketsTimeIndexMetaTableMixin`), not on the
DataNode configuration. The canonical asset foreign key is an SDK
SQLAlchemy `ForeignKey(...)` declaration on the storage class
`asset_identifier` column. The DataNode uses its storage class through
`_required_storage_table()`.

Project-local storage classes may set `__markets_storage_app__` to use a
project-owned SQLAlchemy table-name app segment instead of the library default
`ms_markets`. Set it in the class body before model import/mapping. This only
changes the physical table name, for example
`my_project_markets__example_asset_metrics`; the logical
`__metatable_identifier__` still owns catalog and runtime identity.

```python
import datetime

import pandas as pd
from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.data_nodes.assets import AssetDataNodeConfiguration, AssetTimestampedDataNode
from msm.models.assets.core import AssetTable


class ExampleAssetMetricStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    __markets_storage_app__ = "my_project_markets"
    __metatable_identifier__ = "example_asset_metrics"
    __metatable_description__ = (
        "Timestamped asset metric observations keyed by asset identifier "
        "for market analytics and portfolio workflows."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "asset_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time", "description": "UTC observation timestamp."},
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={"label": "Asset", "description": "AssetTable.unique_identifier value."},
    )
    metric_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Metric Value", "description": "Example asset metric."},
    )


class ExampleAssetMetricConfiguration(AssetDataNodeConfiguration):
    pass


class ExampleAssetMetric(AssetTimestampedDataNode):
    configuration_class = ExampleAssetMetricConfiguration

    @classmethod
    def _required_storage_table(cls) -> type[ExampleAssetMetricStorage]:
        return ExampleAssetMetricStorage

    @classmethod
    def build_frame(cls, rows: list[dict]) -> pd.DataFrame:
        return cls.validate_frame(pd.DataFrame(rows))

    def set_metrics(self, rows: list[dict]):
        return self.set_frame(self.build_frame(rows))
```

Add the storage class to the markets migration model registry so the SDK
migration provider registers it after the `Asset` MetaTable dependency. Runtime
startup can then attach it with `msm.start_engine(models=[...])`. Do not call
`PlatformTimeIndexMetaTable.register(...)`, manually bind storage by UID, or
reconstruct a generic `MetaTable` in application code.

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
|-----------------------------| asset_identifier         |-----------------------------|
| time_index           index  |                          | unique_identifier unique    |
| asset_identifier     index  |                          | asset_type                  |
| name                        |                          +-----------------------------+
| ticker                      |
| exchange_code               |
| asset_ticker_group_id       |
+-----------------------------+
```

`AssetSnapshotsStorage` (in `msm.data_nodes.assets.storage`) declares the persisted
schema as SQLAlchemy mapped columns and owns the canonical
`asset_identifier -> AssetTable.unique_identifier` foreign key. `AssetSnapshot`
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
        "asset_identifier": "example-asset-btc",
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
`["time_index", "asset_identifier"]` MultiIndex, and rejects duplicate keys
inside the frame.

Before a run persists rows, `AssetSnapshot` checks the backend for existing
`(time_index, asset_identifier)` keys and fails if any incoming key already
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
`AssetSnapshotsTS`. With
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`, `Asset` resolves to
`mainsequence.examples.Asset`, while
`AssetSnapshot._default_identifier()` derives from
`AssetSnapshotsStorage.metatable_identifier()` and resolves to
`mainsequence.examples.AssetSnapshotsTS`.

The default DataNode `hash_namespace` also follows the active markets namespace.
Pass an explicit `hash_namespace` only for isolated experiments, tests, or
parallel runs that must not collide on a shared backend.

## Related Code

- `src/msm/data_nodes/assets/asset_indexed.py`: base class, asset scope validation,
  namespace behavior, `asset_identifier` filters, and per-asset update range helpers.
- `src/msm/data_nodes/assets/storage.py`: asset storage classes (including
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
- `src/msm_pricing/data_nodes/pricing_details/__init__.py`:
  `AssetPricingDetail` and its pricing-specific configuration.
- `examples/msm/assets/asset_crud_workflow.py`: asset workflow that includes
  `AssetSnapshot` frame construction and DataNode execution.
- `docs/knowledge/msm/migrations/index.md`: current storage registration and
  migration workflow for MetaTables and time-index storage tables.
