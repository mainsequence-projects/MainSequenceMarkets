---
name: mainsequence-markets-asset-indexed-data-nodes
description: Use this skill when creating, extending, reviewing, or documenting ms-markets AssetIndexedDataNode implementations, especially timestamped market tables keyed by (time_index, unique_identifier). This skill owns ms-markets asset identity conventions, AssetTable foreign keys, namespace behavior, storage metadata, and frame insertion patterns. It does not own the full Main Sequence DataNode lifecycle, orchestration, hashing theory, scheduling, or generic DataNode API behavior.
---

# Main Sequence Markets Asset-Indexed DataNodes

Use this skill for the ms-markets layer on top of Main Sequence `DataNode`s.

An `AssetIndexedDataNode` is still a Main Sequence `DataNode`. The base SDK owns
generic behavior such as storage and update hashes, execution, update statistics,
dependencies, persistence, and scheduling. This skill only owns the markets
conventions added around asset identity.

## Route First

Use the generic DataNode skill when the task depends on Main Sequence behavior:

- `.agents/skills/mainsequence/data_publishing/data_nodes/SKILL.md`

Then use this skill for the ms-markets-specific parts:

- asset identity dimension rules
- `AssetTable` source-table foreign keys
- asset scope validation
- markets namespace and identifier rules
- timestamped asset frame validation
- insertion/update methods for asset-indexed nodes

Use the asset model extension skill instead when the task is about `AssetTable`,
`AssetType`, or one-to-one asset detail MetaTables:

- `.agents/skills/ms_markets/assets/asset_model_extension/SKILL.md`

## This Skill Owns

- Defining asset-indexed DataNodes where `unique_identifier` means
  `msm.api.assets.Asset.unique_identifier`.
- Requiring `ASSET_UNIQUE_IDENTIFIER_DIMENSION` from `msm.settings`; do not
  hardcode competing asset identity column constants.
- Keeping `asset_list` as updater scope, not published table meaning.
- Declaring `PlatformTimeIndexMetaData` storage classes as the canonical output
  schema.
- Declaring a SQLAlchemy `ForeignKey` from the storage table
  `unique_identifier` column to `AssetTable.unique_identifier`.
- Deriving published identifiers from the registered storage table and active
  markets namespace.
- Returning validated `datetime64[ns, UTC]` frames with a
  `["time_index", "unique_identifier"]` index for timestamped asset facts.
- Designing insertion methods that belong on the DataNode class, such as
  `AssetSnapshot.build_frame(...)` and `AssetSnapshot().set_snapshots(...)`.

## This Skill Does Not Own

- Full Main Sequence `DataNode` semantics.
- Generic `DataNodeConfiguration` hashing rules beyond how `asset_list` should
  be scoped for markets.
- Job scheduling, platform release setup, images, resources, or RBAC.
- FastAPI or public API route contracts.
- MetaTable registration semantics outside the required `AssetTable`
  relationship.
- Pricing package design or instrument pricing runtime.

When a task crosses one of these boundaries, route explicitly instead of
guessing.

## Read First

Before changing code, inspect the current local implementation:

1. `src/msm/data_nodes/assets/asset_indexed.py`
2. `src/msm/data_nodes/assets/snapshots.py`
3. `src/msm/data_nodes/storage.py`
4. `src/msm/data_nodes/utils/stamped.py`
5. `src/msm/data_nodes/indices/timestamped.py`
6. `src/msm/settings.py`
7. `docs/knowledge/assets/asset_indexed_data_nodes.md`
8. `docs/ADR/0017-storage-first-data-node-architecture.md`

For generic SDK behavior, verify against the latest Main Sequence DataNode docs
and the `mainsequence-data-nodes` skill.

## Core Contract

Default asset-indexed time series tables use this shape:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| AssetIndexedDataNode table  |--------------------------->| AssetTable                  |
|-----------------------------| unique_identifier          |-----------------------------|
| time_index           index  |                            | uid                         |
| unique_identifier    index  |                            | unique_identifier unique    |
| value columns               |                            | asset_type                  |
+-----------------------------+                            +-----------------------------+
```

Rules:

- `unique_identifier` is the canonical `Asset.unique_identifier`, not a raw
  provider ticker, FIGI, ISIN, or venue symbol.
- Provider identifiers belong in provider detail MetaTables or explicit
  provider-fact DataNode columns.
- `time_index` is the observation timestamp of the row.
- Timestamped asset rows must carry their own `time_index`; do not pass one
  global timestamp into a bulk snapshot builder.
- Dtypes must be stable. For time indexes, normalize to `datetime64[ns, UTC]`.
- Duplicate `(time_index, unique_identifier)` rows are invalid.

## Storage And Configuration Pattern

Use a storage-first pattern. The SQLAlchemy storage class owns table identity,
columns, dtypes, indexes, labels, descriptions, and the asset foreign key.
`AssetIndexedDataNodeConfiguration` and `AssetDataNodeConfiguration` carry
update-scoped fields such as `asset_list`; they do not declare records or table
metadata.

Every storage class must include `__metatable_description__`. The description
should explain the table's market intention, row grain, and downstream use, not
only the schema. For asset-indexed tables, say what the asset row represents and
why it is published over time.

Storage must be registered before the DataNode is constructed. The path is
`PlatformTimeIndexMetaData.register(...)`, normally reached through the markets
catalog bootstrap or `msm.start_engine(models=[...])`. Do not manually bind a UID,
reconstruct a generic `MetaTable`, or use manual bind helpers as an authoring step.

Minimal storage-first pattern:

```python
import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
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
        info={"label": "Time Index", "description": "UTC observation timestamp."},
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
        info={"label": "Metric Value", "description": "Observed metric value."},
    )


class ExampleAssetMetricConfiguration(AssetIndexedDataNodeConfiguration):
    pass
```

The `unique_identifier` foreign key belongs on the storage class. Do not recreate
the old DataNode-side foreign-key or records pattern.

## DataNode Class Pattern

The node class should be thin and explicit:

```python
class ExampleAssetMetric(AssetIndexedDataNode):
    configuration_class = ExampleAssetMetricConfiguration

    def __init__(
        self,
        config: ExampleAssetMetricConfiguration | None = None,
        *,
        hash_namespace: str | None = None,
    ):
        super().__init__(
            config=config or ExampleAssetMetricConfiguration(),
            storage_table=self._required_storage_table(),
            hash_namespace=hash_namespace,
        )

    @classmethod
    def _required_storage_table(cls) -> type[ExampleAssetMetricStorage]:
        return ExampleAssetMetricStorage

    def dependencies(self) -> dict:
        return {}
```

For timestamped asset fact nodes, prefer the local timestamped base pattern from
`src/msm/data_nodes/assets/snapshots.py`:

- config subclass carries update-scoped fields only
- class owns `_required_storage_table()`
- `_default_identifier()` returns
  the identifier derived from `_required_storage_table()`
- `_default_description()` returns the description derived from the storage table
- class methods build validated frames
- instance methods attach validated frames before `run(...)`

Do not create free-floating service functions when the behavior naturally
belongs to the DataNode class.

The timestamped frame/config mechanics are shared in
`src/msm/data_nodes/utils/stamped.py`. Keep new asset and index timestamped nodes
on that base instead of copying validation, schema bootstrap, namespace, or
`datetime64[ns, UTC]` normalization logic. Asset-specific DataNodes belong under
`src/msm/data_nodes/assets/`, and index-specific DataNodes belong under
`src/msm/data_nodes/indices/`. Non-model-specific helpers belong under
`src/msm/data_nodes/utils/`. For timestamped facts keyed to `IndexTable`, use
`IndexTimestampedDataNode` and `IndexDataNodeConfiguration` from
`src/msm/data_nodes/indices/timestamped.py`; the only intended difference is the
canonical source-table foreign key target.

## Namespaces And Identifiers

Use one rule for markets MetaTables and markets DataNodes:

- default namespace: keep bare identifiers such as `Asset` and
  `asset_snapshots`
- when `MSM_AUTO_REGISTER_NAMESPACE` is set to a non-default namespace, prefix
  logical identifiers with that namespace
- use `markets_data_node_identifier(...)` for DataNode identifiers
- let `AssetIndexedDataNode` apply the default markets `hash_namespace`
- pass explicit `hash_namespace` only for tests, isolated experiments, or
  parallel runs that must not collide

Do not hardcode `mainsequence.markets.*` or `mainsequence.examples.*` in a new
DataNode class.

## Asset Scope

`asset_list` is updater scope. It must not define the storage identity of the
published dataset.

Acceptable scope item shapes:

- string asset unique identifiers
- mappings with `unique_identifier`
- objects with `.unique_identifier`

Use the inherited helpers:

- `validate_asset_list(...)`
- `asset_unique_identifiers(...)`
- `asset_dimension_filters(...)`
- `get_asset_dimension_filters()`
- `get_asset_dimension_range_map_great_or_equal(...)`
- `get_last_observation(asset_list=...)`

Do not emit rows for unknown assets. Register or resolve assets through the
typed asset API before publishing asset-indexed rows.

## Frame And Insert Pattern

For timestamped asset facts, separate frame construction from persistence:

```python
frame = AssetSnapshot.build_frame(rows)
node = AssetSnapshot().set_snapshots(rows)
result = node.run(debug_mode=True, force_update=True)
```

Rules:

- `build_frame(...)` validates and normalizes a local `DataFrame`.
- `set_*` methods attach validated rows to a node instance.
- `run(...)` is the write/update operation.
- Each row supplies its own `time_index`.
- Existing backend keys should be checked before writes when the dataset is an
  append-only historical chain.
- Log useful duplicate-key or coverage facts through the DataNode logger.

Use `AssetSnapshot` as the canonical example for append-only historical
representations of an asset.

## Validation Checklist

Before marking work complete:

- The class subclasses `AssetIndexedDataNode` or a markets timestamped
  asset-indexed base.
- The storage table subclasses `PlatformTimeIndexMetaData` through
  `MarketsTimeIndexMetaTableMixin`.
- The storage table has an intention-rich `__metatable_description__`.
- The config subclasses `AssetIndexedDataNodeConfiguration` or
  `AssetDataNodeConfiguration`.
- The storage table declares `time_index`, `unique_identifier`, and all value
  columns.
- The storage time index is timezone-aware and frames normalize to
  `datetime64[ns, UTC]`.
- The storage `unique_identifier` column is the
  `ASSET_UNIQUE_IDENTIFIER_DIMENSION`.
- The storage table declares the canonical `unique_identifier ->
  AssetTable.unique_identifier` SQLAlchemy `ForeignKey`.
- The storage table is registered through `PlatformTimeIndexMetaData.register(...)`
  before DataNode construction.
- `asset_list` is updater scope, not part of table meaning.
- Identifier generation derives from the registered storage table.
- The implementation does not hardcode example or production namespaces.
- Frame validation rejects missing index columns and duplicate keys.
- Tests cover frame validation, storage columns, foreign keys, namespace identifier
  resolution, and any duplicate-backend-key guard.
- Docs/examples use the user-facing `msm.api` asset API where assets are
  registered before DataNode writes.
