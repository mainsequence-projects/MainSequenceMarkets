# Indexes

The Index API exposes identity management, methodology exploration,
cadence-specific canonical history, declared related MetaTables, and standard
identity deletion. Business behavior lives under `msm.services.indices`;
`apps/v1` is a typed HTTP adapter.

An Index is a reusable observable. It is not automatically an Asset, pricing
instrument, or Portfolio. One Index identity may publish observations to
multiple cadence-specific canonical datasets.

## Routes

| Method | Path | Operation ID | Result |
| --- | --- | --- | --- |
| `GET` | `/api/v1/index-type/` | `listIndexTypes` | Paginated type registry |
| `GET` | `/api/v1/index-type/{index_type}/` | `getIndexType` | One type |
| `GET` | `/api/v1/index/` | `listIndexes` | Counted Index page |
| `POST` | `/api/v1/index/` | `createIndex` | New Index identity |
| `GET` | `/api/v1/index/{uid}/` | `getIndex` | One Index |
| `PATCH` | `/api/v1/index/{uid}/` | `updateIndex` | Updated mutable identity fields |
| `DELETE` | `/api/v1/index/{uid}/` | `deleteIndex` | Delete one identity row |
| `GET` | `/api/v1/index/{uid}/summary/` | `getIndexSummary` | `FrontEndDetailSummary` |
| `GET` | `/api/v1/index/{uid}/methodologies/` | `listIndexMethodologies` | Definition history |
| `GET` | `/api/v1/index/{uid}/methodologies/{definition_uid}/` | `getIndexMethodology` | Exact definition and ordered legs |
| `GET` | `/api/v1/index/{uid}/datasets/` | `listIndexDatasets` | Canonical cadence descriptors |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/` | `getIndexDatasetSummary` | Bounded aggregate summary |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/values/` | `getIndexDatasetValuesFrame` | `core.tabular_frame@v1` |
| `GET` | `/api/v1/index/{uid}/related-meta-tables/` | `listIndexRelatedMetaTables` | Core and extension declarations |
| `GET` | `/api/v1/index/{uid}/delete-impact/` | `getIndexDeleteImpact` | Foreign-key impact summary |

Every operation is included in the Adapter from API connection contract.
Create, update, and delete are mutations.

## Methodology Fidelity

The methodology-detail response preserves the canonical leg contract. It
returns `leg_role`, `selector_parameters_json`, `observable_code`,
`transform_code`, `transform_parameters_json`, and
`coefficient_parameters_json` without collapsing or renaming their semantics.

## Listing

`GET /api/v1/index/` supports `search`, `index_type`, `provider`,
`has_definition`, `has_canonical_values`, `cadence`, `limit`, and `offset`.
The response count is authoritative for the complete filter, and ordering is
stable.

Creating an Index does not create methodology or storage. Use
`DerivedIndex.upsert(...)` when core owns a reproducible methodology. Register
cadence storage through the migration workflow before a producer writes
values.

## Dataset Contracts

`GET /api/v1/index/{uid}/datasets/` returns typed canonical table descriptors.
A table qualifies only when its registered cadence contract maps to the
authoritative `configured_index_values_storage(cadence=...)` model and the
model contains the real foreign key:

```text
index_identifier -> IndexTable.unique_identifier
```

The resolver also verifies identifier, cadence, physical table, grain, and the
required `value` and `unit` columns. A matching column name or physical-name
prefix is not sufficient.

The 1m and 1d descriptors for `USD_SWAP_10Y` therefore identify different
MetaTable UIDs and physical tables even though both are filtered with the same
Index business identifier.

## Bounded Values

The values route requires timezone-aware `start` and `end`, an `asc` or `desc`
order, and a limit from 1 through 5,000. It resolves the selected Index UID and
always applies:

```text
index_identifier = selected Index.unique_identifier
```

The implementation uses a governed compiled `SELECT` with time bounds and a
server-side limit. The response is the SDK `TabularFrameResponse` and can feed
generic Command Center tables and charts.

## Extension Relationships

Extensions may register an `IndexRelationshipProvider` with an authoritative
SQLAlchemy model and a real foreign key to `IndexTable.uid` or
`IndexTable.unique_identifier`. The producer does not have to inherit a core
Index DataNode. Inferred relationships remain informational.

## Deletion

Index deletion follows the same direct row-deletion contract as other core
reference resources:

```http
DELETE /api/v1/index/{uid}/
```

The route returns `null` on success and `404` when the UID does not exist.
Database `CASCADE`, `SET NULL`, `RESTRICT`, and `NO ACTION` constraints govern
related rows. Identity deletion does not delete canonical timestamped value
streams or perform extension-owned cleanup.

## Related Concepts

- [Index values and derived Indexes tutorial](../../tutorial/06-derived-indexes.md)
- [Derived Index workflow](../../knowledge/msm/indices/derived_indexes.md)
- [ADR 0038](../../ADR/0038-index-user-api-and-fastapi-exploration.md)
