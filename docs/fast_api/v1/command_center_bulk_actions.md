# Command Center Bulk Actions

The `apps/v1` API exposes backend-authoritative bulk deletion for asset
categories, portfolios, and portfolio groups. These routes implement the
Command Center SDK v1 discovery, execution, and preflight contracts pinned to
command-center-sdk commit
`7f2c942799fb83edaacfc1c0d971452bfc8aff5c`.

## Resource boundaries

| Resource | Discovery | Preflight | Execution |
| --- | --- | --- | --- |
| Asset categories | `GET /api/v1/asset-category/bulk-actions/` | `POST /api/v1/asset-category/bulk-delete/preflight/` | `POST /api/v1/asset-category/bulk-delete/` |
| Portfolios | `GET /api/v1/portfolio/bulk-actions/` | `POST /api/v1/portfolio/bulk-delete/preflight/` | `POST /api/v1/portfolio/bulk-delete/` |
| Portfolio groups | `GET /api/v1/portfolio-group/bulk-actions/` | `POST /api/v1/portfolio-group/bulk-delete/preflight/` | `POST /api/v1/portfolio-group/bulk-delete/` |

Each discovery response advertises one destructive action with `explicit`
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

Execution repeats preflight immediately before invoking domain deletion. A
blocked selection returns HTTP `409` and does not call the delete service. The
underlying delete operation still performs its own conflict checks, protecting
against authorization or reference changes between preflight and execution.

Request validation errors return `422`. Unsupported modes or options return
`400`. A preflight that discovers missing or protected rows returns `200` with
`allowed: false`; execution of that same selection returns `409`.

## Provider discovery

The six discovery and preflight operation IDs are also exposed through
`/.well-known/command-center/connection-contract` as resource operations. The
three execution operation IDs remain mutation operations:

- `listAssetCategoryBulkActions` / `preflightBulkDeleteAssetCategories` /
  `bulkDeleteAssetCategories`
- `listPortfolioBulkActions` / `preflightBulkDeletePortfolios` /
  `bulkDeletePortfolios`
- `listPortfolioGroupBulkActions` / `preflightBulkDeletePortfolioGroups` /
  `bulkDeletePortfolioGroups`

The language-neutral manifest, schemas, and fixtures in command-center-sdk are
the contract authority. The API-owned Python models under
`apps.v1.schemas.bulk_actions` implement those wire formats without importing
deprecated MainSequence SDK Command Center modules.
