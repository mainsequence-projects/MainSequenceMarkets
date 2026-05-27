---
name: mainsequence-markets-asset-indexed-data-nodes
description: Use this skill when creating, extending, reviewing, or documenting ms-markets AssetIndexedDataNode implementations, especially timestamped market tables keyed by (time_index, unique_identifier). This skill owns ms-markets asset identity conventions, AssetTable foreign keys, namespace behavior, records metadata, and frame insertion patterns. It does not own the full Main Sequence DataNode lifecycle, orchestration, hashing theory, scheduling, or generic DataNode API behavior.
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
- Declaring `RecordDefinition` records as the canonical output schema.
- Declaring a `SourceTableForeignKey` from the DataNode source table
  `unique_identifier` column to `AssetTable.unique_identifier`.
- Using `markets_data_node_identifier(...)` and the active markets namespace for
  published identifiers.
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
3. `src/msm/data_nodes/utils/stamped.py`
4. `src/msm/data_nodes/indices/timestamped.py`
5. `src/msm/settings.py`
6. `docs/knowledge/assets/asset_indexed_data_nodes.md`
7. `docs/ADR/0007-market-data-node-asset-foreign-keys.md`

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

## Configuration Pattern

Use `AssetIndexedDataNodeConfiguration` for generic asset-indexed nodes. Use
`AssetDataNodeConfiguration` or a subclass for timestamped asset facts.

Configuration must declare records directly:

```python
from pydantic import Field, model_validator

from mainsequence.tdag.data_nodes import DataNodeMetaData, RecordDefinition
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
    asset_indexed_foreign_keys,
)
from msm.settings import ASSET_UNIQUE_IDENTIFIER_DIMENSION, markets_data_node_identifier


class ExampleAssetMetricConfiguration(AssetIndexedDataNodeConfiguration):
    node_metadata: DataNodeMetaData = Field(
        default_factory=lambda: DataNodeMetaData(
            identifier=markets_data_node_identifier("example_asset_metrics"),
            description="Example metric keyed by UTC observation time and asset.",
        )
    )
    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    )
    records: list[RecordDefinition] = Field(
        default_factory=lambda: [
            RecordDefinition(
                column_name="time_index",
                dtype="datetime64[ns, UTC]",
                label="Time Index",
                description="UTC observation timestamp.",
            ),
            RecordDefinition(
                column_name=ASSET_UNIQUE_IDENTIFIER_DIMENSION,
                dtype="string",
                label="Asset",
                description="Asset unique identifier from AssetTable.",
            ),
            RecordDefinition(
                column_name="metric_value",
                dtype="float64",
                label="Metric Value",
                description="Observed metric value.",
            ),
        ]
    )

    @model_validator(mode="after")
    def _ensure_asset_foreign_key(self):
        self.foreign_keys = asset_indexed_foreign_keys(
            records=self.records,
            foreign_keys=self.foreign_keys,
        )
        return self
```

The foreign key helper should fail if the `records` list does not include the
asset identity record. Do not add ad hoc foreign-key objects in each node when
the canonical helper applies.

## DataNode Class Pattern

The node class should be thin and explicit:

```python
class ExampleAssetMetric(AssetIndexedDataNode):
    __data_node_identifier__ = "example_asset_metrics"

    def __init__(self, config: ExampleAssetMetricConfiguration | None = None):
        super().__init__(config=config or ExampleAssetMetricConfiguration())

    def dependencies(self) -> dict:
        return {}
```

For timestamped asset fact nodes, prefer the local timestamped base pattern from
`src/msm/data_nodes/assets/snapshots.py`:

- config subclass declares records
- class owns `__data_node_identifier__`
- `_default_identifier()` returns
  `markets_data_node_identifier(cls.__data_node_identifier__)`
- `_default_description()` explains the dataset as a durable data product
- class methods build validated frames
- instance methods bind frames before `run(...)`

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
- The config subclasses `AssetIndexedDataNodeConfiguration` or
  `AssetDataNodeConfiguration`.
- `records` contains `time_index`, `unique_identifier`, and all value columns.
- `time_index` record dtype is `datetime64[ns, UTC]`.
- `unique_identifier` record uses `ASSET_UNIQUE_IDENTIFIER_DIMENSION`.
- `foreign_keys` includes the canonical `unique_identifier ->
  AssetTable.unique_identifier` relationship.
- `asset_list` is `update_only` scope, not part of table meaning.
- Identifier generation uses `markets_data_node_identifier(...)`.
- The implementation does not hardcode example or production namespaces.
- Frame validation rejects missing index columns and duplicate keys.
- Tests cover frame validation, records, foreign keys, namespace identifier
  resolution, and any duplicate-backend-key guard.
- Docs/examples use the user-facing `msm.api` asset API where assets are
  registered before DataNode writes.
