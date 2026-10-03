# Command Center Bulk Actions

The `apps/v1` API exposes backend-authoritative bulk deletion for asset
categories, portfolios, and portfolio groups. These routes implement the
Command Center SDK v1 resource discovery, execution, and preflight contracts
pinned to command-center-sdk `0.1.13`, commit
`f11c0ea8c5d3fc267997e476aa1522c798fdaced`.

## Resource boundaries

| Resource | Discovery | Preflight | Execution |
| --- | --- | --- | --- |
| Asset categories | `GET /api/v1/asset-category/discovery/` | `POST /api/v1/asset-category/bulk-delete/preflight/` | `POST /api/v1/asset-category/bulk-delete/` |
| Portfolios | `GET /api/v1/portfolio/discovery/` | `POST /api/v1/portfolio/bulk-delete/preflight/` | `POST /api/v1/portfolio/bulk-delete/` |
| Portfolio groups | `GET /api/v1/portfolio-group/discovery/` | `POST /api/v1/portfolio-group/bulk-delete/preflight/` | `POST /api/v1/portfolio-group/bulk-delete/` |

Each `command-center.resource_discovery@v1` response advertises one destructive action with `explicit`
selection. `all_matching` is deliberately not advertised. Discovery supplies
the execution endpoint, preflight endpoint, confirmation copy, tone, supported
selection modes, and options.

## Canonical request

Preflight and execution receive the same
`command-center.bulk_action_execution@v1` body:

```json
{
  "selection": {
    "mode": "explicit",
    "uids": ["7dc962fe-58e6-4a04-9cc6-20b44d678d42"]
  },
  "options": {}
}
```

The selected resources use UUID identities and currently advertise no options.
Unknown options, numeric identifiers, and unadvertised selection modes are
rejected. The former `{ "uids": [...], "select_all": false }` HTTP payload is
not part of this contract.

## Preflight and execution

Preflight returns `command-center.bulk_action_preflight@v1`. It resolves every
selected UID and reports `allowed`, `matched_count`, `blockers`, and `warnings`
without mutating data. Portfolio preflight also evaluates protected
VirtualFund and target-position references.

Each bulk-delete preflight also reports what deleting rows from the resource's
table reaches through foreign keys. It asks MetaTables
(`MetaTable.get_impact(action="delete_rows")`) and adds:

- `impact`: the MetaTables impact graph. Nodes are the tables the delete
  reaches, with their effects and whether the caller may write each one. Edges
  are classified as `cascade_delete`, `cascade_update`, `set_null`,
  `set_default`, `restrict` or `reads`. MetaTables' blockers are included.
- `warnings`: one sentence for each foreign-key action the delete triggers, for
  example "PortfolioGroupMembership rows that reference deleted PortfolioGroup
  rows are deleted too (ON DELETE CASCADE)." Command Center shows warnings
  without custom rendering.
- `blockers`: MetaTables' reasons the caller may not run the delete, prefixed
  with the table: the caller cannot write the table, the table does not accept
  writes, or its DataSource is read-only. The preflight then answers
  `allowed: false` and execution answers `409` before the database refuses the
  delete. Cascades never block: write on a table depends only on its own grants,
  because a foreign key's action belongs to the referencing table.

Deleting portfolios or portfolio groups cascades to their
`PortfolioGroupMembership` rows; deleting asset categories cascades to their
`AssetCategoryMembership` rows. If MetaTables cannot compute the impact,
`impact` is `null` and a warning says so. The preflight is not blocked, because
the database still applies and enforces every foreign-key action.

On the local SQLite runtime, MetaTables documents one limitation: its authorizer
also checks the reads and writes of foreign-key actions, so a delete that
cascades fails unless the caller can access every referencing table. The
preflight cannot detect this. PostgreSQL runs these actions as the referencing
table's owner.

Execution repeats preflight immediately before invoking domain deletion. A
blocked selection returns HTTP `409` and does not call the delete service. The
underlying delete operation still performs its own conflict checks, protecting
against authorization or reference changes between preflight and execution.

Request validation errors return `422`. Unsupported modes or options return
`400`. A preflight that discovers missing or protected rows returns `200` with
`allowed: false`; execution of that same selection returns `409`.

## Provider discovery

The discovery and preflight operation IDs are also exposed through
`/.well-known/command-center/connection-contract` as resource operations. The
three execution operation IDs remain mutation operations:

- `discoverAssetCategories` / `preflightBulkDeleteAssetCategories` /
  `bulkDeleteAssetCategories`
- `discoverPortfolios` / `preflightBulkDeletePortfolios` /
  `bulkDeletePortfolios`
- `discoverPortfolioGroups` / `preflightBulkDeletePortfolioGroups` /
  `bulkDeletePortfolioGroups`

The language-neutral manifest, schemas, and fixtures in command-center-sdk are
the contract authority. Provider projects, including this repository's FastAPI
app, import the implementing Python models and helpers from `msm.api.http`.
