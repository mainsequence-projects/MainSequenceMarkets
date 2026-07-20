# Indexes

The FastAPI Index surface manages identity and explores formulas, canonical
datasets, values, relationships, and delete impact. Formula mutation remains a
typed-library operation through `FormulaIndex`.

## Routes

| Method | Path | Operation ID | Result |
| --- | --- | --- | --- |
| `GET` | `/api/v1/index-type/` | `listIndexTypes` | Paginated type registry |
| `GET` | `/api/v1/index-type/{index_type}/` | `getIndexType` | One type |
| `GET` | `/api/v1/index/` | `listIndexes` | Counted Index page |
| `POST` | `/api/v1/index/` | `createIndex` | New Index identity |
| `GET` | `/api/v1/index/{uid}/` | `getIndex` | One Index |
| `PATCH` | `/api/v1/index/{uid}/` | `updateIndex` | Updated identity metadata |
| `DELETE` | `/api/v1/index/{uid}/` | `deleteIndex` | Direct row deletion |
| `GET` | `/api/v1/index/{uid}/summary/` | `getIndexSummary` | Detail summary |
| `GET` | `/api/v1/index/{uid}/formulas/` | `listIndexFormulas` | Formula history |
| `GET` | `/api/v1/index/{uid}/formulas/{definition_uid}/` | `getIndexFormula` | Formula and exact inputs |
| `GET` | `/api/v1/index/{uid}/datasets/` | `listIndexDatasets` | Per-Index dataset states |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/` | `getIndexDatasetSummary` | Selected dataset summary |
| `GET` | `/api/v1/index/{uid}/datasets/{meta_table_uid}/values/` | `getIndexDatasetValuesFrame` | Bounded tabular frame |
| `GET` | `/api/v1/index/{uid}/related-meta-tables/` | `listIndexRelatedMetaTables` | Filtered related MetaTables |
| `GET` | `/api/v1/index/{uid}/delete-impact/` | `getIndexDeleteImpact` | FK impact summary |
| `GET` | `/api/v1/asset/{uid}/related-meta-tables/` | `listAssetRelatedMetaTables` | Asset source-table discovery |

All operations are present in the Adapter from API contract. Create, update,
and delete are mutations.

## Identity Payload

Create requires:

```json
{
  "unique_identifier": "USD-SWAP-10Y",
  "index_type": "interest_rate",
  "display_name": "USD 10Y Swap Rate",
  "calculation_method": "custom",
  "value_format": "percent",
  "value_suffix": null
}
```

`calculation_method` is `formula` or `custom`. `value_format` is `decimal` or
`percent`; the optional suffix is presentation text. No provider, methodology
owner, result-unit registry, or effective-date field exists on identity.

## Listing

`GET /api/v1/index/` supports:

```text
search, index_type, has_formula, has_canonical_values, cadence
limit, offset, order, response_format
```

`response_format=frontend_list` is the standard list contract.
`has_canonical_values` and `cadence` query indexed availability metadata; they
do not scan each canonical table for distinct identifiers.

## Formula Responses

Formula history returns version, status, validity, formula, policies, hash,
and input count. Detail adds alignment parameters, metadata, and exact inputs:

```json
{
  "source_reference": {
    "type": "index",
    "identifier": "MXN-TIIE-28D"
  },
  "meta_table_uid": "11111111-1111-1111-1111-111111111111",
  "observable": "price"
}
```

The response has no source key, resolver object, configurable identity/value
columns, selectors, transforms, coefficients, or units.

## Related MetaTables

Asset and Index related-table routes accept:

- `numeric=true`: require a numeric non-identity column;
- `timestamped=true`: require a registered time-indexed table.

Both default to true. False disables only that filter. Responses use the same
`RelatedMetaTable` schema. Relationships are proven by registered FK metadata;
column names alone are not accepted. Catalog discovery is paginated and does
not read source values.

## Dataset States

Per-Index dataset listing returns:

- `populated` when reconciliation found rows;
- `compatible_empty` when a compatible query found none;
- `unavailable` when access or query failure prevented a count.

Compatible-empty rows are hidden unless `include_empty=true`. Unavailable rows
remain visible and are not represented as empty.

## Bounded Values

Value requests require timezone-aware `start` and `end`, `order=asc|desc`, and
a limit from 1 to 5,000. The selected Index identifier is always applied as a
server-side dimension filter. The response is `core.tabular_frame@v1`.

Rows contain numeric value and optional provenance. Observation `unit` is not
part of the response; display formatting belongs to the Index identity.

## Deletion

Deletion uses the same direct row API as other core resources:

```http
DELETE /api/v1/index/{uid}/
```

It returns `null` on success and `404` when missing. Database `CASCADE`,
`SET NULL`, `RESTRICT`, and `NO ACTION` constraints govern relationships.
There is no signing secret, confirmation token, or deletion executor.

`GET /delete-impact/` is read-only preflight metadata. It does not change the
delete operation.

## Related Documentation

- [Formula and custom Index tutorial](../../tutorial/06-index-formulas.md)
- [Formula and custom Index workflow](../../knowledge/msm/indices/formula_indexes.md)
- [ADR 0038](../../ADR/0038-index-user-api-and-fastapi-exploration.md)
