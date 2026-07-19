# Indexes

Indexes are canonical market observables, not assets. An Index may be an
externally supplied reference or a calculated observable with a versioned
derived-index methodology.

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
- If the type is `derived`, which immutable definition and ordered legs give
  the index its meaning at a timestamp?

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
has been finalized by the SDK migration upgrade flow. Application startup can
attach only this dependency set explicitly:

```python
import msm

msm.start_engine(models=["IndexType", "Index"])
```

Examples and development scripts can set `MSM_AUTO_REGISTER_NAMESPACE` before
importing the API classes when they need an example namespace, but they still
must call `msm.start_engine(...)` during startup before row operations.

## Canonical Index Values

`IndexValuesStorage` is the domain-neutral column-schema anchor for plain and
calculated Index observations. Stable-frequency publication uses
`configured_index_values_storage(cadence=...)`, which creates one concrete
MetaTable per frequency with canonical grain:

```text
(time_index, index_identifier)
```

Every row requires `value` and `unit`. `definition_uid`,
`observation_status`, `source_as_of`, and `metadata_json` are nullable
provenance. `definition_uid` is null for a plain observation and is required by
the derived-index publication path.

Frequency does not change the Index identity, but it does change the dataset
identity. For example, `USD_SWAP_10Y` is one Index identity representing the
observable 10-year swap yield. Its one-minute and daily histories require two
DataNodes and two storage tables:

```text
Swap10YOneMinuteDataNode -> IndexValuesTS.1m -> ms_markets__index_values__t_1m
Swap10YDailyDataNode     -> IndexValuesTS.1d -> ms_markets__index_values__t_1d
                              |
                              +-- both rows use index_identifier = USD_SWAP_10Y
```

The generated class declares `__cadence__`, includes cadence in its storage
hash components and MetaTable identifier, and uses the frequency in its
physical table suffix. Do not mix stable frequencies in one table or express
frequency only through a schedule, runtime option, or `hash_namespace`.

Use `IndexValuesDataNode.validate_frame(..., storage_table=...)` to normalize
caller-supplied rows. A concrete producer should override
`_required_storage_table()` with exactly one configured storage. The cadence-
less schema anchor is rejected as a publication target. Omitted nullable
provenance columns are supplied automatically.

Calculation-method changes are identity decisions, not frequency settings. A
software-only implementation change preserves the identity. A prospective
economic-method change uses a new effective definition version when core owns
the calculation. If two complete method histories must coexist, use distinct
Index identifiers such as `USD_SWAP_10Y_METHOD_A` and
`USD_SWAP_10Y_METHOD_B`.

## Timestamped Index Storage And DataNodes

`msm.data_nodes.indices.IndexTimestampedDataNode` is a reusable convenience
base for a table containing time-varying facts keyed to
`IndexTable.unique_identifier`. It is not a mandatory inheritance contract for
extension libraries.

An index-stamped table should use this shape:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| IndexTimestampedDataNode   |--------------------------->| IndexTable                  |
|-----------------------------| index_identifier           |-----------------------------|
| time_index           index  |                            | unique_identifier unique    |
| index_identifier     index  |                            | display_name                |
| value columns               |                            | provider                    |
+-----------------------------+                            +-----------------------------+
```

Core or extension DataNode classes may inherit `IndexTimestampedDataNode` and
bind a registered `PlatformTimeIndexMetaTable` through
`_required_storage_table()`. The shared base validates the table-owned schema,
normalizes timestamps to `datetime64[ns, UTC]`, sets the declared MultiIndex,
and rejects duplicate keys.

An extension may instead define its own Index-indexed storage and producer
implementation. The interoperability rules are structural:

- use canonical `IndexTable` identity;
- retain an `index_identifier -> IndexTable.unique_identifier` foreign key;
- declare the table's own UTC time and identity grain;
- own any source-specific fields and lifecycle;
- declare one stable cadence per physical source table and encode that cadence
  in its MetaTable and table identity;
- optionally publish a selected value into the matching cadence-configured
  canonical Index-value table when generic consumers need that contract.

The extension must not subclass concrete `IndexValuesStorage` merely to obtain
a different physical table. See
`examples/msm/indices/extension_owned_index_storage.py` for a separate
bid/ask/mid schema normalized without using the core Index DataNode base.

## Derived Indexes

Use `index_type="derived"` when an Index owns a calculated methodology such as
a yield spread, commodity calendar spread, curve butterfly, ratio, rebased
basket, or self-financing hedged series. The small `IndexTable` remains the
stable identity; effective-dated definition and leg tables carry calculation
meaning, and generic Index storage carries published history.

See [Derived Index Workflow](derived_indexes.md) for the complete typed API,
operators, unit and timing policies, dynamic resolution, publication workflow,
examples, and the Index/Portfolio/Signal boundaries.

## Boundaries

Do not widen `AssetTable` with index fields. Do not put index reference rows in
asset categories. Use `IndexTable` for the reference identity and use futures or
other derivative detail tables to link tradable contracts back to indexes.

## Related Concepts

- [Assets](../assets/index.md)
- [Futures](../derivatives/futures.md)
- [Models](../models/index.md)
- [Derived Index Workflow](derived_indexes.md)
