# Accounts

Route group for account identity, detail summaries, holdings snapshots, and
account target-position assignment. Target-allocation candidate searches resolve
valid asset and portfolio targets, and holdings read endpoints support both
direct account snapshots and virtual-fund-grouped views.

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
    `published_index_uid`; portfolio targets are mandate exposure, not custody
    holdings

## Related Concepts

- [Accounts knowledge](../../knowledge/msm/accounts/index.md)
