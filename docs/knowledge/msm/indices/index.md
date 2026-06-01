# Indexes

Indexes are reference data, not assets.

Use `Index` when a workflow needs a canonical row for an index that may be used
as a derivative underlying. Do not create fake `Asset` rows for indexes just to
make a foreign key work.

## Scope

Indexes answer these questions:

- What is the stable `unique_identifier` for this index?
- What type of index is it, such as `interest_rate`?
- What human-readable name should users see?
- Which optional provider namespace owns or supplied the reference row?
- Which derivative contracts reference this index as an underlying?

Indexes do not represent tradable instruments. A tradable future on an index is
an `Asset(asset_type="future")` plus a `FutureAssetDetailsTable` row that references
`IndexTable.uid`.

Do not store platform Constant names on `IndexTable`. Constant aliases are not
part of the schema or the typed `Index` payloads; project-specific aliases
belong in `metadata_json` only when they are reference metadata rather than
canonical identity.

## API

Application code should use `msm.api.indices.IndexType` to register index type
keys and `msm.api.indices.Index` to register canonical index rows.

```python
from msm.api.indices import Index, IndexType
from msm.constants import (
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)

IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())

sofr = Index.upsert(
    unique_identifier="USD-SOFR-3M",
    index_type=INDEX_TYPE_INTEREST_RATE,
    display_name="USD SOFR 3M",
    provider="example",
)
```

OpenFIGI-backed workflows can register index reference rows with the provider
helper. The helper rejects rows whose OpenFIGI `marketSector` is not `Index`.

```python
from msm.api.indices import IndexType
from msm.services import register_index_from_figi
from msm.constants import INDEX_TYPE_EQUITY, INDEX_TYPE_EQUITY_DEFINITION

IndexType.upsert(**INDEX_TYPE_EQUITY_DEFINITION.as_payload())
spx = register_index_from_figi("BBG000KKFC45", index_type=INDEX_TYPE_EQUITY)
```

`Index` exposes the same typed row API style as the rest of `msm.api`:

- `IndexType.upsert(...)`
- `Index.upsert(...)`
- `Index.get_by_uid(...)`
- `Index.get_by_unique_identifier(...)`
- `Index.filter(...)`
- `Index.update(...)`
- `Index.delete(...)`

## Schema

`IndexTypeTable` and `IndexTable` are declared under `msm.models.indices` and
exported through `msm.models`. `IndexTypeTable` mirrors the `AssetTypeTable`
pattern: it registers what an `Index.index_type` string means. In the current
schema, `Index.index_type` is a required string classification field whose values should
match rows in `IndexType`; it is not a database foreign key in this release.

`IndexTypeTable` fields:

| Field | Meaning |
| --- | --- |
| `uid` | Internal row identity. |
| `index_type` | Stable type key, unique within the registered table. |
| `display_name` | Human-readable type name. |
| `description` | Optional explanation of the type. |
| `metadata_json` | Optional type metadata. |

`IndexTable` fields:

| Field | Meaning |
| --- | --- |
| `uid` | Internal row identity. |
| `unique_identifier` | Stable index key, unique within the registered table. |
| `index_type` | Required classification key, such as `interest_rate`. |
| `display_name` | Human-readable name. |
| `description` | Optional explanation of the index. |
| `provider` | Optional provider or source namespace. |
| `metadata_json` | Provider-specific reference fields that are not yet part of the canonical schema. |

`IndexType.index_type` and `Index.unique_identifier` are indexed uniquely.
`Index.index_type`, `display_name`, and `provider` are indexed for lookup workflows.
There is no Constant-name column.

## Registration

`Index.__required_tables__` declares the minimum schema set:

```text
IndexTypeTable
IndexTable
```

Production code normally assumes this MetaTable already exists and the catalog
has been finalized by `msm migrations upgrade`. Application startup can attach
only this dependency set explicitly:

```python
import msm

msm.start_engine(models=["IndexType", "Index"])
```

Examples and development scripts can set `MSM_AUTO_REGISTER_NAMESPACE` before
importing the API classes when they need an example namespace, but they still
must call `msm.start_engine(...)` during startup before row operations.

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

DataNode classes should inherit `IndexTimestampedDataNode` and use a registered
`PlatformTimeIndexMetaData` storage class through `_required_storage_table()`.
That storage class declares the output schema and the canonical
`IndexTable.unique_identifier` foreign key. The shared stamped base validates
required columns against the storage contract, normalizes timestamps to
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
