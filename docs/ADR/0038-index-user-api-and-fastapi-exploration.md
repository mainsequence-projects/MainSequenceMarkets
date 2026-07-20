# ADR 0038: Index User API And FastAPI Exploration

## Status

Accepted and implemented. This ADR describes the catalog and HTTP surfaces
after the formula/custom replacement in ADR 0037.

## Context

Index identity, formula history, canonical datasets, bounded observations,
related MetaTables, and deletion impact must be inspectable without mixing
those concerns into formula authoring or DataNode execution.

## Decision

### Typed API

`Index` exposes:

```python
Index.list_page(...)
Index.get_detail(uid)
Index.get_summary(uid)
Index.list_formulas(uid)
Index.get_formula(uid, definition_uid)
Index.list_datasets(uid)
Index.get_dataset_summary(uid, meta_table_uid)
Index.get_values(uid, meta_table_uid, start=..., end=...)
Index.list_related_meta_tables(uid, numeric=True, timestamped=True)
Index.reconcile_dataset_availability(...)
Index.delete(uid)
```

`FormulaIndex` owns formula creation, lifecycle, preview, and publication
configuration. Catalog routes do not duplicate formula mutation.

### Formula Fidelity

Formula detail returns the expression, validity, alignment and missing-data
policies, semantic hash, and exact public inputs:

```text
source_reference
meta_table_uid
observable
```

It does not synthesize aliases or expose removed operator, selector,
transform, coefficient, composition, or unit fields.

### Dataset Relevance

Registered cadence tables are global contracts. Per-Index dataset listing
uses `IndexDatasetAvailabilityTable` and returns:

- `populated`;
- `compatible_empty`;
- `unavailable`.

The default excludes compatible-empty rows and retains unavailable rows.
`include_empty=true` includes compatible-empty contracts. An unavailable
query is not reported as zero rows.

`has_canonical_values` and `cadence` use indexed availability metadata. They
do not enumerate distinct Index identifiers from every canonical dataset.
Producers reconcile only identifiers from successful persistence; bounded
backfill is explicit.

### Related MetaTables

Index and Asset related-table routes accept independent filters:

```text
numeric=true
timestamped=true
```

Both default to true. Passing false disables only that filter. Discovery uses
registered schema and authoritative FK metadata, walks the complete visible
catalog in pages, and never scans table values.

### Bounded Values

Value reads require timezone-aware `start` and `end`, an `asc` or `desc`
order, and a server-side limit from 1 through 5,000. The selected Index's
`unique_identifier` is always applied as a dimension filter. Responses use
`core.tabular_frame@v1` and do not repeat display formatting on every row.

### Standard Deletion

Index deletion uses the ordinary direct row API:

```text
DELETE /api/v1/index/{uid}/
```

It returns `null` on success and `404` when missing. Database FK actions govern
related rows. There is no deletion secret, signing token, execution journal,
or custom executor.

Delete impact is a read-only preflight for the same direct operation. Service
permission, validation, and missing-resource errors retain their documented
HTTP meaning rather than being collapsed into a generic availability error.

## FastAPI Contract

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
| `GET` | `/api/v1/index/{uid}/formulas/` | `listIndexFormulas` |
| `GET` | `/api/v1/index/{uid}/formulas/{definition_uid}/` | `getIndexFormula` |
| `GET` | `/api/v1/index/{uid}/datasets/` | `listIndexDatasets` |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/` | `getIndexDatasetSummary` |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/values/` | `getIndexDatasetValuesFrame` |
| `GET` | `/api/v1/index/{uid}/related-meta-tables/` | `listIndexRelatedMetaTables` |
| `GET` | `/api/v1/index/{uid}/delete-impact/` | `getIndexDeleteImpact` |
| `GET` | `/api/v1/asset/{uid}/related-meta-tables/` | `listAssetRelatedMetaTables` |

Every operation is included in the Adapter from API contract. Index create,
update, and delete are mutations; exploration operations are queries.

## Consequences

- Clients can distinguish global dataset compatibility from per-Index
  population.
- Interactive catalog filters avoid full canonical-table scans.
- Formula detail is sufficient to reproduce the source binding.
- Asset and Index source-table selection use one schema contract.
- Destructive behavior remains consistent with other core resources.
