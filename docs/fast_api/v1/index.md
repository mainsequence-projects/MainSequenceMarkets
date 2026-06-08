# FastAPI v1

The local `apps/v1` FastAPI app exposes the migrated public asset registry
surface for this repository.

## Scope

This API is intentionally thin:

- route declarations, validation, and OpenAPI metadata live under `apps/v1`
- reusable asset category workflows live under `src/msm/services`
- asset, category, and index frontend route composition is backed by
  `src/msm/services/asset_master_lists.py`
- pricing market-data set and binding workflows are backed by
  `msm_pricing.api`
- portfolio detail and latest-weight workflows are backed by
  `src/msm_portfolios/services`
- virtual-fund identity and holdings snapshot workflows are backed by
  `src/msm/services/accounts/virtual_funds_public_api.py`

## Route ADRs

- [Calendar CRUD And Summary Route](ADR/0001-calendar-crud-route.md): route
  group for calendar identity CRUD, summary, and bounded date, session, and
  event maintenance.
- [Pricing Market Data Routes](pricing_market_data.md): route group for
  pricing market-data set and concept binding management.
- [Portfolio Routes](portfolio.md): route group for portfolio identity,
  detail-page composition, latest weights, and delete operations.
- [Virtual Fund Routes](virtualfund.md): route group for account-owned
  virtual-fund identity and holdings snapshots.

## Runtime Bootstrap

When `MSM_AUTO_REGISTER_NAMESPACE` is set for local development, `apps/v1`
now performs startup-time runtime attachment instead of waiting for the first
request to hit a row operation.

Current local-dev behavior:

- the app calls `msm_portfolios.start_engine(...)` during startup for the
  `apps/v1` table set because this surface includes portfolio-backed account
  target-position routes
- the startup table set includes portfolio-backed target-position tables, so
  target-position routes resolve against the existing shared markets runtime
  instead of starting a second portfolio runtime on first request
- the startup table set includes `PortfolioMetadata` and
  `PortfolioWeightsStorage` so portfolio detail and latest-weights routes use
  the same shared markets runtime
- the startup table set includes `VirtualFund`, `VirtualFundHoldingsSet`, and
  `VirtualFundHoldingsStorage` so virtual-fund routes attach to the shared
  markets runtime
- the app calls `msm_pricing.bootstrap.attach_pricing_schemas(...)` during
  startup for the pricing rows used by asset pricing details and pricing
  market-data management
- schema mutation must already have been handled by
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
- `GET /api/v1/account/target-allocation/targets/`
  - supports `search`, `target_type=all|asset|portfolio`, `limit`, and
    `offset`
  - returns one paginated candidate list for target-position assignment
  - searches valid `TargetPositionsStorage` targets across `AssetTable` and
    `PortfolioTable`
  - backed by one compiled MetaTable `select` operation using `UNION ALL`
    rather than separate asset and portfolio searches
  - asset candidates include latest `AssetSnapshotsStorage` name/ticker labels
    when present
  - each result contains `target_type`, `target_uid`, `asset_uid`, and
    `portfolio_uid`, so the selected row can be written directly into a target
    position payload
- `GET /api/v1/account/{account_uid}/holdings/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `holdings_date`
  - returns one holdings snapshot backed by `AccountHoldingsStorage`
  - each holding exposes the storage `asset_identifier`, positive `quantity`,
    `direction` (`1` long, `-1` short), and computed `signed_quantity`
  - returns 200 with an empty `holdings` list when the account exists but no
    holdings snapshot matches
  - snapshot-level fields are `holdings_set_uid`, `holdings_date`, and
    `holdings`
- `GET /api/v1/account/{account_uid}/holdings/by-fund/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `holdings_date`
  - selects one `AccountHoldingsSetTable` source snapshot for the account
  - groups persisted `VirtualFundHoldingsStorage` allocation rows by
    `VirtualFundTable.uid` where each `VirtualFundHoldingsSetTable` references
    the selected source account holdings set
  - returns `account_uid`, `source_account_holdings_set_uid`, `holdings_date`,
    `funds`, `residuals`, and `allocation_warnings`
  - each fund contains `virtual_fund_uid`,
    `virtual_fund_unique_identifier`, `target_portfolio_uid`,
    `holdings_set_uid`, and grouped holdings rows
  - grouped holding rows expose the storage `asset_identifier`, positive
    allocated `quantity`, first-class `allocation_strategy`, `direction`,
    computed `signed_quantity`, and `allocation` metadata parsed from
    `extra_details`
  - `allocation` contains `target_gap_signed_quantity`, `scale`,
    `target_row_key`, and `position_set_uid` when those fields were persisted
    by the virtual-fund allocation apply step
  - `residuals` are derived as source account signed quantity minus total
    virtual-fund allocated signed quantity per asset
  - asset labels use latest `AssetSnapshotsStorage` rows; OpenFIGI and numeric
    asset IDs are not used
  - this read endpoint does not rerun or apply the allocation planner
- `POST /api/v1/account/{account_uid}/add-holdings/`
  - writes one account holdings snapshot and returns the same
    `AccountHoldingsSnapshotResponse` contract as the holdings read endpoint
  - request body contains `holdings_date`, `overwrite`, and `positions`
  - each position uses the storage field name `asset_identifier`
  - `asset_uid`, when provided, is validation only and must match the asset row
    for the supplied `asset_identifier`
  - `quantity` is stored as a positive magnitude and `direction` stores side
  - `target_trade_time`, when provided, must match `holdings_date`
  - `overwrite=false` rejects an existing snapshot; `overwrite=true` replaces
    rows for the holdings set through one scoped MetaTable operation so the
    delete and replacement insert share the same backend transaction boundary
- `POST /api/v1/account/{account_uid}/add-target-positions/`
  - writes one account target-position snapshot and returns the same
    `AccountTargetPositionsSnapshotResponse` contract as the target-positions
    read endpoint
  - request body contains only `target_positions_date`, `overwrite`, and
    `positions`; account and target-allocation parent identity are derived from
    the account uid in the path
  - backend derives a deterministic account allocation model and
    account-target-allocation row from the account uid; the frontend does not
    send `account_allocation_model_uid`, target-allocation uid, display name, or
    parent metadata
  - each position uses `target_type`, `target_uid`, and exactly one concrete
    target reference: `asset_uid` for asset rows or `portfolio_uid` for
    portfolio rows
  - each position must provide exactly one of `weight_notional_exposure`,
    `constant_notional_exposure`, or `single_asset_quantity`
  - `single_asset_quantity` is valid only for direct asset target rows;
    portfolio target rows must use `weight_notional_exposure` or
    `constant_notional_exposure`
  - `overwrite=false` rejects an existing position set at the same timestamp;
    `overwrite=true` replaces rows through one scoped MetaTable operation so the
    parent upserts, delete, and replacement insert share the same backend
    transaction boundary
- `GET /api/v1/account/{account_uid}/target-positions/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `target_positions_date`
  - resolves active account target allocations, selects one `PositionSetTable`
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

### Portfolios

- `GET /api/v1/portfolio/`
  - supports `response_format=frontend_list`
  - supports `search`, `calendar_uid`, `calendar_name`, `limit`, and `offset`
  - returns `PaginatedResponse[Portfolio]` using the library
    `msm.api.portfolios.Portfolio` contract
- `GET /api/v1/portfolio/{uid}/`
  - returns a composed portfolio detail payload containing the core portfolio
    row, optional `PortfolioMetadata`, latest-weights tab link, and route links
  - missing metadata does not make the route return 404
- `GET /api/v1/portfolio/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for portfolio detail
    pages
  - uses the portfolio `uid` string as `entity.id`
- `GET /api/v1/portfolio/{uid}/weights/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `weights_date`
  - resolves weights through
    `Portfolio.portfolio_index_uid -> Index.unique_identifier`
  - returns one snapshot backed by `PortfolioWeightsStorage`
  - returns 200 with an empty `weights` list when the portfolio exists but no
    matching weights snapshot exists
  - asset labels use latest `AssetSnapshotsStorage` rows; OpenFIGI is not used
- `DELETE /api/v1/portfolio/{uid}/`
  - deletes one portfolio identity row
  - returns 409 when protected rows, such as account target-position history,
    still reference the portfolio
  - does not delete historical portfolio weights or values
- `POST /api/v1/portfolio/bulk-delete/`
  - deletes multiple portfolio identity rows by explicit `uids`
  - reports protected or missing rows in `failed`

### Virtual Funds

- `GET /api/v1/virtualfund/`
  - supports `response_format=frontend_list`
  - supports `search`, `account_uid`, `portfolio_uid`, `limit`, and `offset`
  - `portfolio_uid` filters `VirtualFund.target_portfolio_uid`
  - returns `PaginatedResponse[VirtualFund]` using the library
    `msm.api.virtual_funds.VirtualFund` contract
- `GET /api/v1/virtualfund/{uid}/`
  - returns a composed virtual-fund detail payload containing the core
    virtual-fund row, latest-holdings tab link, and route links
- `GET /api/v1/virtualfund/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for virtual-fund
    detail pages
  - uses the virtual-fund `uid` string as `entity.id`
- `GET /api/v1/virtualfund/{uid}/holdings/`
  - supports `order`, `limit=1`, `include_asset_detail`, and exact
    `holdings_date`
  - returns one snapshot backed by `VirtualFundHoldingsSetTable` and
    `VirtualFundHoldingsStorage`
  - returns 200 with an empty `holdings` list when the virtual fund exists but
    no matching holdings snapshot exists
  - holdings rows expose the storage `asset_identifier`, positive `quantity`,
    first-class `allocation_strategy`, `direction`, and computed
    `signed_quantity`
  - asset labels use latest `AssetSnapshotsStorage` rows; OpenFIGI is not used

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
