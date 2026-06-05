# FastAPI v1

The local `apps/v1` FastAPI app exposes the migrated public asset registry
surface for this repository.

## Scope

This API is intentionally thin:

- route declarations, validation, and OpenAPI metadata live under `apps/v1`
- reusable catalog and category workflows live under `src/msm/services`
- asset, category, and index frontend route composition is backed by
  `src/msm/services/asset_master_lists.py`
- MetaTable catalogue discovery and row management is backed by
  `src/msm/services/catalog.py`

## Runtime Bootstrap

When `MSM_AUTO_REGISTER_NAMESPACE` is set for local development, `apps/v1`
now performs startup-time runtime attachment instead of waiting for the first
request to hit a row operation.

Current local-dev behavior:

- the app calls `msm.start_engine(...)` during startup for the `apps/v1`
  table set
- schema and catalog mutation must already have been handled by
  `mainsequence migrations upgrade --provider migrations:migration head`
- the app uses the real project/session data source already configured for the
  Main Sequence client session
- if the session cannot resolve a valid DynamicTable data source, startup
  should fail instead of redirecting writes into an ad hoc local store

## Implemented Routes

### Accounts

- `GET /api/v1/account/`
  - supports `search`, `limit`, and `offset`
  - returns `{ count, results }`
  - `results` contains the library `msm.api.accounts.Account` contract:
    `uid`, `unique_identifier`, `account_name`, `is_paper`,
    `account_is_active`, `holdings_data_node_uid`, and `metadata_json`
- `GET /api/v1/account/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for account detail
    pages
  - resolves the account by `uid`
- `GET /api/v1/account/{account_uid}/holdings/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `holdings_date`
  - returns one holdings snapshot backed by `AccountHoldingsStorage`
  - each holding exposes `direction` (`1` long, `-1` short)
  - `quantity` is rendered as the signed frontend quantity
    (`AccountHoldingsStorage.quantity * direction`)
  - returns 200 with an empty `holdings` list when the account exists but no
    holdings snapshot matches
  - nullable compatibility fields such as `id`, `snapshot_uid`, `nav`, and
    `price` are not invented when the storage row does not provide them
- `GET /api/v1/account/{account_uid}/target-positions/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `target_positions_date`
  - resolves active account target portfolios, selects one `PositionSetTable`
    snapshot, and returns its `TargetPositionsStorage` exposure rows
  - returns 200 with an empty `positions` list when the account exists but no
    target-position snapshot matches
  - asset details include `uid`, `unique_identifier`, and latest
    `AssetSnapshotsStorage` `name` / `ticker`; no OpenFIGI or numeric asset id
    fields are returned

### Assets

- `GET /api/v1/asset/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, `offset`
  - supports `categories__uid` for nested category asset tables
  - returns the library `msm.api.assets.Asset` contract:
    `uid`, `unique_identifier`, and `asset_type`
- `GET /api/v1/asset/{uid}/summary/`
  - returns a reusable `FrontEndDetailSummary` response for detail-page
    summary cards
  - resolves the asset by `uid`
  - includes asset identity, badges, inline fields, highlight fields, label
    management placeholders, and page-specific extensions
- `GET /api/v1/asset/{uid}/get_pricing_details/`
  - returns the current pricing details row for one asset
  - response mirrors `msm_pricing.api.AssetCurrentPricingDetails`
  - returns 404 when no current pricing details row exists for the asset

### Asset Categories

- `GET /api/v1/asset-category/`
  - supports `response_format=frontend_list`
  - returns the library `msm.api.assets.AssetCategory` contract
- `GET /api/v1/asset-category/{uid}/`
  - supports `response_format=frontend_detail`
  - returns one library `msm.api.assets.AssetCategory` row
- `POST /api/v1/asset-category/`
  - creates a category
  - derives `unique_identifier` from `display_name` when omitted
  - replaces memberships when `assets` are supplied
  - returns the created library `msm.api.assets.AssetCategory` row
- `PATCH /api/v1/asset-category/{uid}/`
  - updates category metadata
  - replaces memberships when `assets` are supplied
  - returns the updated library `msm.api.assets.AssetCategory` row
- `DELETE /api/v1/asset-category/{uid}/`
  - deletes a single category
  - returns `null` on success
- `POST /api/v1/asset-category/bulk-delete/`
  - deletes by explicit `uids`
  - also supports compatibility filters with `select_all=true`

### Indexes

- `GET /api/v1/index/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, and `offset`
  - returns the library `msm.api.indices.Index` contract
- `GET /api/v1/index/{uid}/`
  - returns one index registry record by `uid`
  - always includes `index_type` and includes `metadata_json` when present on
    the underlying row
- `DELETE /api/v1/index/{uid}/`
  - deletes one index registry record
  - returns `null` on success

### Catalogues

- `GET /api/v1/catalog/`
  - lists catalogue entries from the markets MetaTable catalogue
  - supports `search`, `limit`, and `offset`
  - returns catalogue identity fields, backend `meta_table_uid`, support flags,
    and row-management endpoint templates
  - does not expose physical schema or physical table name fields
- `GET /api/v1/catalog/{catalog_uid}/rows/`
  - lists rows for one catalogue entry selected by catalogue row `uid`
  - returns a generic row contract with `columns` and row `values`
- `DELETE /api/v1/catalog/{catalog_uid}/rows/{uid}/`
  - deletes one row from the selected catalogue-backed MetaTable
  - resolves the backend table through the catalogue entry
  - relies on backend foreign-key cascade behavior for related rows

## Compatibility Notes

The `response_format=frontend_list` and `response_format=frontend_detail`
query parameters are still accepted on migrated legacy routes, but list and
direct detail rows now prefer core library API models over frontend projections.

The nested category asset table should use `GET /api/v1/asset/` with
`categories__uid`. The dedicated `POST /api/v1/asset/query/` route is still
future work for this local API.

## Validation

The focused FastAPI coverage for this surface lives under:

- `tests/msm/fastapi/v1/`

Use `/openapi.json`, `/docs`, and `/redoc` from the local app for contract
inspection.
