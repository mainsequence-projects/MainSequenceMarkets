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
- pricing market-data set and binding workflows are backed by
  `msm_pricing.api`

## Route ADRs

- [Calendar CRUD And Summary Route](ADR/0001-calendar-crud-route.md): route
  group for calendar identity CRUD, summary, and bounded date, session, and
  event maintenance.
- [Pricing Market Data Routes](pricing_market_data.md): route group for
  pricing market-data set and concept binding management.

## Runtime Bootstrap

When `MSM_AUTO_REGISTER_NAMESPACE` is set for local development, `apps/v1`
now performs startup-time runtime attachment instead of waiting for the first
request to hit a row operation.

Current local-dev behavior:

- the app calls `msm.start_engine(...)` during startup for the `apps/v1`
  table set
- the app calls `msm_pricing.bootstrap.attach_pricing_schemas(...)` during
  startup for the pricing rows used by asset pricing details and pricing
  market-data management
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
- `POST /api/v1/account/{account_uid}/add-holdings/`
  - writes one account holdings snapshot and returns the same
    `AccountHoldingsSnapshotResponse` contract as the holdings read endpoint
  - request body contains `holdings_date`, `overwrite`, and `positions`
  - each position uses `unique_identifier` as the stored `asset_identifier`
  - `asset_uid`, when provided, is validation only and must match the asset row
    for the supplied `unique_identifier`
  - `quantity` is stored as a positive magnitude and `direction` stores side
  - `target_trade_time`, when provided, must match `holdings_date`
  - `overwrite=false` rejects an existing snapshot; `overwrite=true` replaces
    rows for the holdings set through one scoped MetaTable operation so the
    delete and replacement insert share the same backend transaction boundary
- `GET /api/v1/account/{account_uid}/target-positions/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `target_positions_date`
  - resolves active account target portfolios, selects one `PositionSetTable`
    snapshot, and returns its `TargetPositionsStorage` exposure rows
  - each position carries `target_type`, `target_uid`, and exactly one concrete
    target reference: `asset_uid` or `portfolio_uid`
  - returns 200 with an empty `positions` list when the account exists but no
    target-position snapshot matches
  - asset details include `uid`, `unique_identifier`, and latest
    `AssetSnapshotsStorage` `name` / `ticker`; no OpenFIGI or numeric asset id
    fields are returned
  - portfolio details include `uid`, `unique_identifier`, and optional
    `portfolio_index_uid`; portfolio targets are mandate exposure, not custody
    holdings

### Assets

- `GET /api/v1/asset/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, `offset`
  - supports `categories__uid` for nested category asset tables
  - returns the library `msm.api.assets.Asset` contract:
    `uid`, `unique_identifier`, and `asset_type`
- `GET /api/v1/asset/{uid}/`
  - supports `response_format=frontend_detail`
  - resolves the asset by `uid`
  - returns `AssetDetailResponse` with top-level `uid`, `unique_identifier`,
    `asset_type`, and `current_snapshot`
  - `current_snapshot` is the latest `AssetSnapshotsStorage` row for the
    asset `unique_identifier` / snapshot `asset_identifier`
  - does not use numeric asset IDs for asset identity
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

### Calendars

- `GET /api/v1/calendar/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, and `offset`
  - supports exact filters for `unique_identifier`, `calendar_type`, `source`,
    and `source_identifier`
  - supports `unique_identifier_contains`
  - returns the library `msm.api.calendars.Calendar` contract
- `POST /api/v1/calendar/`
  - creates one calendar identity row
  - request body uses the library `CalendarCreate` contract
  - returns the created `Calendar` row
- `GET /api/v1/calendar/{uid}/`
  - supports `response_format=frontend_detail`
  - returns one library `Calendar` row by uid
- `GET /api/v1/calendar/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for calendar detail
    pages
  - resolves the calendar by `uid`
  - includes calendar identity, type/timezone badges, validity horizon, label
    management placeholders, and related date/session/event route links
- `PATCH /api/v1/calendar/{uid}/`
  - updates mutable calendar identity fields
  - request body uses the library `CalendarUpdate` contract
  - returns the updated `Calendar` row
- `DELETE /api/v1/calendar/{uid}/`
  - deletes one calendar identity row
  - returns `null` on success
  - related date, session, and event rows are removed by database cascade
- `GET /api/v1/calendar/{calendar_uid}/dates/`
  - lists `CalendarDate` rows for one calendar
  - supports `start_date`, `end_date`, flag filters, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/dates/`
  - creates one date row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/dates/bulk-upsert/`
  - bulk upserts date rows under the path calendar uid
- `GET`, `PATCH`, and `DELETE /api/v1/calendar/{calendar_uid}/dates/{date_uid}/`
  - manage one date row and require it to belong to the path calendar uid
- `GET /api/v1/calendar/{calendar_uid}/sessions/`
  - lists `CalendarSession` rows for one calendar
  - supports `start_date`, `end_date`, `session_label`, `is_primary`,
    `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/sessions/`
  - creates one session row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/sessions/bulk-upsert/`
  - bulk upserts session rows under the path calendar uid
- `GET`, `PATCH`, and
  `DELETE /api/v1/calendar/{calendar_uid}/sessions/{session_uid}/`
  - manage one session row and require it to belong to the path calendar uid
- `GET /api/v1/calendar/{calendar_uid}/events/`
  - lists `CalendarEvent` rows for one calendar
  - supports `start_date`, `end_date`, `event_type`, `event_label`,
    `target_type`, `target_uid`, `target_identifier`, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/events/`
  - creates one event row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/events/bulk-upsert/`
  - bulk upserts event rows under the path calendar uid
- `GET`, `PATCH`, and `DELETE /api/v1/calendar/{calendar_uid}/events/{event_uid}/`
  - manage one event row and require it to belong to the path calendar uid

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

### Pricing Market Data

- `GET /api/v1/pricing/market_data/`
  - returns the discoverability card for pricing market-data set and binding
    operations
- `GET /api/v1/pricing/market_data/sets/`
  - supports `limit`, `offset`, `status`, and `set_key`
  - returns `PaginatedResponse[PricingMarketDataSet]`
  - uses the Django REST Framework-style `{ count, next, previous, results }`
    envelope
- `GET /api/v1/pricing/market_data/sets/{uid}/`
  - returns one `PricingMarketDataSet` by uid
- `GET /api/v1/pricing/market_data/sets/by-key/{set_key}/`
  - returns one `PricingMarketDataSet` by set key
- `POST /api/v1/pricing/market_data/sets/`
  - creates one set with `PricingMarketDataSetCreate`
  - returns `PricingMarketDataSet`
- `POST /api/v1/pricing/market_data/sets/upsert/`
  - upserts one set with `PricingMarketDataSetUpsert`
  - returns `PricingMarketDataSet`
- `PATCH /api/v1/pricing/market_data/sets/{uid}/`
  - updates one set with `PricingMarketDataSetUpdate`
  - returns `PricingMarketDataSet`
- `DELETE /api/v1/pricing/market_data/sets/{uid}/`
  - deletes one set through `PricingMarketDataSet.delete(uid)`
  - returns `{ detail, uid, deleted_count }`
- `GET /api/v1/pricing/market_data/bindings/`
  - supports `limit`, `offset`, `market_data_set_uid`, and `concept_key`
  - returns `PaginatedResponse[PricingMarketDataSetBinding]`
- `GET /api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/`
  - lists bindings owned by one pricing market-data set
  - returns `PaginatedResponse[PricingMarketDataSetBinding]`
- `GET /api/v1/pricing/market_data/bindings/{uid}/`
  - returns one `PricingMarketDataSetBinding` by uid
- `GET /api/v1/pricing/market_data/bindings/resolve/`
  - supports `market_data_set` and required `concept_key`
  - returns `{ market_data_set, concept_key, data_node_uid }`
- `POST /api/v1/pricing/market_data/bindings/`
  - creates one binding with `PricingMarketDataSetBindingCreate`
  - returns `PricingMarketDataSetBinding`
- `POST /api/v1/pricing/market_data/bindings/upsert/`
  - upserts one binding with `PricingMarketDataSetBindingUpsert`
  - returns `PricingMarketDataSetBinding`
- `PATCH /api/v1/pricing/market_data/bindings/{uid}/`
  - updates one binding with `PricingMarketDataSetBindingUpdate`
  - returns `PricingMarketDataSetBinding`
- `DELETE /api/v1/pricing/market_data/bindings/{uid}/`
  - deletes one binding through `PricingMarketDataSetBinding.delete(uid)`
  - returns `{ detail, uid, deleted_count }`

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
