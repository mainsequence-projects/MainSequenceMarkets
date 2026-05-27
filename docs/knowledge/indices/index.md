# Indexes

Indexes are reference data, not assets.

Use `Index` when a workflow needs a canonical row for an index that may be used
as a derivative underlying. Do not create fake `Asset` rows for indexes just to
make a foreign key work.

## Scope

Indexes answer these questions:

- What is the stable `unique_identifier` for this index?
- What human-readable name should users see?
- Which optional provider namespace owns or supplied the reference row?
- Which derivative contracts reference this index as an underlying?

Indexes do not represent tradable instruments. A tradable future on an index is
an `Asset(asset_type="future")` plus a `FutureDetailsTable` row that references
`IndexTable.uid`.

## API

Application code should use `msm.api.indices.Index`.

```python
from msm.api.indices import Index

spx = Index.upsert(
    unique_identifier="SPX",
    display_name="S&P 500 Index",
    provider="example",
)
```

OpenFIGI-backed workflows can register index reference rows with the provider
helper. The helper rejects rows whose OpenFIGI `marketSector` is not `Index`.

```python
from msm.services import register_index_from_figi

spx = register_index_from_figi("BBG000KKFC45")
```

`Index` exposes the same typed row API style as the rest of `msm.api`:

- `Index.create_schemas(...)`
- `Index.upsert(...)`
- `Index.get_by_uid(...)`
- `Index.get_by_unique_identifier(...)`
- `Index.filter(...)`
- `Index.update(...)`
- `Index.delete(...)`

## Schema

`IndexTable` is declared under `msm.models.indices` and exported through
`msm.models`.

| Field | Meaning |
| --- | --- |
| `uid` | Internal row identity. |
| `unique_identifier` | Stable index key, unique within the registered table. |
| `display_name` | Human-readable name. |
| `description` | Optional explanation of the index. |
| `provider` | Optional provider or source namespace. |
| `metadata_json` | Provider-specific reference fields that are not yet part of the canonical schema. |

`unique_identifier` is indexed uniquely. `display_name` and `provider` are
indexed for lookup workflows.

## Registration

`Index.__required_tables__` declares the minimum schema set:

```text
IndexTable
```

Production code normally assumes this MetaTable already exists. Application
startup can register only this dependency set explicitly:

```python
from msm.api.indices import Index

Index.create_schemas()
```

Examples and development scripts can instead set `MSM_AUTO_REGISTER_NAMESPACE`
before importing the API classes.

## Timestamped Index DataNodes

Use `msm.data_nodes.indices.IndexTimestampedDataNode` when a table stores
time-varying facts keyed to `IndexTable.unique_identifier`. The implementation
lives in `msm.data_nodes.indices.timestamped` and is re-exported by the
`msm.data_nodes.indices` package for normal user imports. It is the IndexTable
counterpart to the asset timestamped base and reuses the shared
`msm.data_nodes.utils.stamped` frame/config implementation.

An index-stamped table should use this shape:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| IndexTimestampedDataNode   |--------------------------->| IndexTable                  |
|-----------------------------| unique_identifier          |-----------------------------|
| time_index           index  |                            | unique_identifier unique    |
| unique_identifier    index  |                            | display_name                |
| value columns               |                            | provider                    |
+-----------------------------+                            +-----------------------------+
```

Configuration classes should inherit `IndexDataNodeConfiguration`, declare
their output schema with `RecordDefinition`, and let
`index_indexed_foreign_keys(...)` add the canonical source-table foreign key.
The shared stamped base validates required columns, normalizes timestamps to
`datetime64[ns, UTC]`, sets the
`["time_index", "unique_identifier"]` MultiIndex, rejects duplicate keys, and
uses the active markets namespace for default DataNode identifiers and
`hash_namespace`.

## Boundaries

Do not widen `AssetTable` with index fields. Do not put index reference rows in
asset categories. Use `IndexTable` for the reference identity and use futures or
other derivative detail tables to link tradable contracts back to indexes.

## Related Concepts

- [Assets](../assets/index.md)
- [Futures](../derivatives/futures.md)
- [Models](../models/index.md)
