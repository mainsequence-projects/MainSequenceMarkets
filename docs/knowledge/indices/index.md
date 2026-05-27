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

## Boundaries

Do not widen `AssetTable` with index fields. Do not put index reference rows in
asset categories. Use `IndexTable` for the reference identity and use futures or
other derivative detail tables to link tradable contracts back to indexes.

## Related Concepts

- [Assets](../assets/index.md)
- [Futures](../derivatives/futures.md)
- [Models](../models/index.md)
