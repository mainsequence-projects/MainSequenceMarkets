# ADR 0038: Index User API And FastAPI Exploration

## Status

Accepted and implemented. Identity, methodology, relationship, bounded
value-read, filtered listing, and direct identity-deletion surfaces are
available through the typed API and FastAPI adapter.

## Context

ADR 0037 defines an Index as one stable observable identity whose values may be
published to separate cadence-specific `IndexValuesTS.<cadence>` tables. The
library needs a typed user API and a thin FastAPI surface for managing that
identity and inspecting its methodology and observations.

The API must preserve these boundaries:

- `IndexTable` owns identity and mutable display metadata;
- `DerivedIndex` owns calculation-definition authoring and lifecycle;
- registered cadence tables are global storage contracts;
- rows in those tables establish whether a particular Index is populated;
- database foreign keys govern ordinary identity deletion.

## Decision

### Typed User API

The public `Index` row exposes typed catalog operations:

```python
Index.list_page(...)
Index.get_detail(uid)
Index.get_summary(uid)
Index.list_methodologies(uid)
Index.get_methodology(uid, definition_uid)
Index.list_datasets(uid)
Index.get_dataset_summary(uid, meta_table_uid)
Index.get_values(uid, meta_table_uid, start=..., end=...)
Index.list_related_meta_tables(uid)
Index.delete(uid)
```

`DerivedIndex` remains the methodology-authoring API. FastAPI routes do not
duplicate definition upsert, activation, retirement, or calculation behavior.

### Methodology Fidelity

`IndexMethodologyDetail` returns the exact ordered leg configuration. A leg
preserves canonical model names and all reproducibility fields, including:

```text
leg_role
selector_parameters_json
observable_code
transform_code
transform_parameters_json
coefficient_parameters_json
```

The service must not collapse or discard selector, transform, rolling hedge,
delta, beta, or DV01 parameters.

### Dataset Contracts And Relevance

Global dataset discovery proves that a registered table is a canonical Index
value contract. It verifies identifier, cadence, physical table, grain,
required columns, and the actual foreign key to
`IndexTable.unique_identifier`.

`Index.list_datasets(uid)` returns the compatible global contracts available
for querying that Index. `Index.get_dataset_summary(...)` and
`Index.get_values(...)` then scope reads to the selected Index identifier.

### Interactive Availability Filters

`listIndexes` supports `has_canonical_values` and `cadence`. These filters
resolve identifiers present in the registered canonical cadence contracts and
apply that set to the authoritative Index query. `response_format=frontend_list`
remains the supported compatibility format on the FastAPI list route.

### Standard Deletion

Index deletion follows the same direct row-deletion contract as other core
reference resources:

```python
Index.delete(uid)
```

```text
DELETE /api/v1/index/{uid}/
```

The HTTP route returns `null` on success and `404` when the UID does not exist.
Database foreign keys define the result for related rows:

- `CASCADE` relationships are deleted by the database;
- `SET NULL` relationships are cleared by the database;
- `RESTRICT` or `NO ACTION` relationships block deletion.

Deleting canonical time-series values is a separate explicit storage operation
and is not implied by deleting an Index identity.

### FastAPI Routes

The Index surface includes:

| Method | Path | Operation ID |
| --- | --- | --- |
| `GET` | `/api/v1/index-type/` | `listIndexTypes` |
| `GET` | `/api/v1/index-type/{index_type}/` | `getIndexType` |
| `GET` | `/api/v1/index/` | `listIndexes` |
| `POST` | `/api/v1/index/` | `createIndex` |
| `GET` | `/api/v1/index/{uid}/` | `getIndex` |
| `PATCH` | `/api/v1/index/{uid}/` | `updateIndex` |
| `DELETE` | `/api/v1/index/{uid}/` | `deleteIndex` |
| `GET` | `/api/v1/index/{uid}/summary/` | `getIndexSummary` |
| `GET` | `/api/v1/index/{uid}/methodologies/` | `listIndexMethodologies` |
| `GET` | `/api/v1/index/{uid}/methodologies/{definition_uid}/` | `getIndexMethodology` |
| `GET` | `/api/v1/index/{uid}/datasets/` | `listIndexDatasets` |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/` | `getIndexDatasetSummary` |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/values/` | `getIndexDatasetValuesFrame` |
| `GET` | `/api/v1/index/{uid}/related-meta-tables/` | `listIndexRelatedMetaTables` |
| `GET` | `/api/v1/index/{uid}/delete-impact/` | `getIndexDeleteImpact` |

Value reads always resolve the selected UID to `Index.unique_identifier`,
apply that dimension filter, require bounded timezone-aware dates and a
server-side limit, and return `core.tabular_frame@v1`.

## Consequences

- Index identity deletion remains small and consistent with other resources.
- Foreign-key definitions remain the source of truth for deletion effects.
- Value cleanup is never hidden inside identity deletion.
- Methodology inspection remains reproducible.
- Dataset descriptors identify compatible canonical contracts; population is
  evaluated by Index-scoped summary and values queries.

## Validation

The implementation is complete only when tests prove:

- create, update, lookup, and direct delete behavior;
- direct delete returns `null` or `404` through FastAPI;
- restrictive foreign keys prevent invalid deletion;
- methodology legs retain every semantic parameter field;
- list filtering preserves `response_format=frontend_list`,
  `has_canonical_values`, and `cadence`;
- dataset summary and value reads remain scoped to the selected Index;
- value reads remain dimension-scoped and bounded;
- OpenAPI and Adapter operation lists match the implemented routes.
