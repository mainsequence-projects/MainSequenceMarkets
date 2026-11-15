# Accounts

Route group for account identity, detail summaries, holdings snapshots, and
account target-position assignment. Target-allocation candidate searches resolve
valid asset and portfolio targets, and holdings read endpoints support both
direct account snapshots and virtual-fund-grouped views.

!!! note "Pre-3.0 field names"
    Through ms-markets 3.x every response that carries `holdings_storage_table_uid` or `source_storage_table_uid` also
    repeats it under its pre-3.0 `*_data_node_uid` name, which OpenAPI marks
    deprecated, and requests accept either name. ms-markets 4.0 removes the
    pre-3.0 names ([ADR 0048](../../ADR/0048-time-index-vocabulary-rename.md)).

- `GET /api/v1/account/`
  - supports `search`, `limit`, and `offset`
  - returns `command-center.resource_collection@v1`
  - exposes `GET /api/v1/account/discovery/`
  - `items` contains the library `msm.api.accounts.Account` contract:
    `uid`, `unique_identifier`, `account_name`, `is_paper`,
    `account_is_active`, `holdings_storage_table_uid`, and `metadata_json`
- `POST /api/v1/account/`
  - creates one `Account` identity row from the `msm.api.accounts.AccountCreate`
    payload (`unique_identifier`, `account_name`, `is_paper`,
    `account_is_active`, `account_group_uid`, `holdings_storage_table_uid`,
    `metadata_json`) and returns it with `201`
  - `409` when the row cannot be stored, for example a duplicate
    `unique_identifier`
  - ADR 0047: providers register accounts here instead of writing the Account
    table; the write runs as the Markets workload and records the acting
    identity
- `POST /api/v1/account/registration/` (`registerAccount`)
  - registers an account and writes one holdings snapshot in one MetaTables
    transaction ([ADR 0051](../../ADR/0051-account-registration-in-one-transaction.md)).
    A connector calls it once to register an account and once per holdings sync
  - request body: `account` (`unique_identifier`, `account_name`, optional
    `is_paper` and `account_is_active`; a flag left out keeps an existing
    account's value), `assets` (each with `unique_identifier`, `asset_type`
    `{asset_type, display_name, description}` and an optional `snapshot`
    `{name, ticker, exchange_code, asset_ticker_group_id}`), optional
    `cash_currency`, `holdings_date`, `overwrite` and `positions`
    (`asset_identifier`, positive `quantity`, `direction`, `extra_details`).
    At most 1,000 distinct assets and 1,000 positions
  - two reads whatever the size: the named assets with their latest snapshots,
    and the account by `unique_identifier` with its holdings at `holdings_date`.
    Then one transaction creates the missing asset types, assets and cash
    currency asset (`currency` type), writes changed snapshots, creates the
    account or updates the fields that differ, and writes the holdings. When
    nothing differs, no transaction is sent
  - a position may name an asset in `assets`, the cash currency or an existing
    asset; one `400` names every other identifier
  - an existing asset keeps its `asset_type`: a different requested type is a
    `409` listing each such asset, and nothing is written
  - a snapshot row is written at `holdings_date` when the asset has none, or when
    its latest snapshot is earlier and differs in `name`, `ticker`,
    `exchange_code` or `asset_ticker_group_id` (a missing value equals an empty
    string); never over or before a later one
  - idempotent on `(account.unique_identifier, holdings_date)`: holdings equal to
    the stored ones are not written again (`200`, with either `overwrite`);
    different holdings are a `409` without `overwrite`, and nothing in the call
    is written; with `overwrite` they replace the set's rows
  - returns `account`, `asset_uids` by identifier, `holdings_set_uid`,
    `holdings_date` and `written`: per table (`asset_types`, `assets`,
    `asset_snapshots`, `accounts`, `holdings_sets`, `holdings`) the rows
    `created` and `changed`
  - audited as `registry_write("account", "register")`, with one record per
    row created or changed, each carrying the account's `unique_identifier`
  - writes only Markets tables: a provider writes its own account sidecar
    afterwards with the returned account uid (ADR 0047)
  - `MarketsClient.register_account(...)` calls this route and returns
    `AccountRegistrationResponse`
- `GET /api/v1/account/by-uids/?uid__in=<uid>&uid__in=<uid>`
  - batch lookup by uid; `uid__in` is repeated or comma-separated, at most 500
  - returns the matching `Account` rows in request order inside a
    `ResourceCollection`; unknown uids are omitted, so `totalItems` is the
    number found
  - a bounded lookup for consumers that hydrate core columns from their own
    rows, not a browsable collection: no `limit`, `offset`, search or
    discovery route
  - `include=<sidecar MetaTable uid>` (repeated or comma-separated, at most
    10) attaches provider sidecar rows under `includes[<uid>]` on every item
    (`null` when the sidecar has no row). A sidecar is a provider table with a
    single-column foreign key to this resource's `uid`, proven from the
    MetaTables catalog; each sidecar is read once for all returned uids. The
    Markets workload needs `data_viewer` on the sidecar (`409` otherwise,
    `404` for a uid that is not a visible MetaTable, `400` for a table that is
    not a sidecar of this resource). Plain columns come back as stored; Markets
    never decrypts a provider column, never selects a column the catalog marks
    as application-encrypted and drops any encryption-envelope value, so
    `include` never returns ciphertext. `includes` is `{}` when nothing is included
- `GET /api/v1/account/{uid}/`
  - returns one canonical `Account` row by uid
- `PATCH /api/v1/account/{uid}/`
  - updates the mutable fields of one `Account` row from the
    `msm.api.accounts.AccountUpdate` payload (`account_name`, `is_paper`,
    `account_is_active`, `account_group_uid`, `holdings_storage_table_uid`,
    `metadata_json`); omitted fields are unchanged
  - `404` when the uid is unknown
- `DELETE /api/v1/account/{uid}/`
  - deletes the account with its whole history in one transaction
    ([ADR 0050](../../ADR/0050-account-deletion.md)): its orders, trades and the
    order events of those orders, its order managers, virtual funds with their
    holdings sets and rows, target allocations with their position sets and
    target rows, holdings sets with their rows, then the account
  - only Markets tables receive statements. A table in another namespace loses
    rows only through its own foreign key: a `CASCADE` key deletes them with
    their parent, and the response lists that table in
    `other_namespace_cascades`; a `RESTRICT` key refuses the whole delete. Rows
    with no key, such as order events in a provider's copy of the events
    storage, stay
  - returns `deleted_rows`, the Markets rows per table counted just before the
    delete ran
  - `404` when the uid is unknown; `409` when a key refuses the delete,
    including orders of other accounts that name its order managers or virtual
    funds of other accounts allocated from its holdings sets; nothing is deleted
  - there is no delete for a single virtual fund, target allocation, position
    set or holdings set: an account's history is kept for as long as the account
    exists ([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md))
- `POST /api/v1/account/bulk-delete/preflight/`
  - takes the Command Center bulk-action request with explicit uids and returns,
    without deleting, per account the Markets rows the delete removes
    (`accounts[].row_counts`) and its blockers, the MetaTables impact, and the
    tables in other namespaces it reaches (`other_namespace_cascades`,
    `other_namespace_restricts`). Markets cannot count rows in those tables, so
    they are warnings, not blockers
- `POST /api/v1/account/bulk-delete/`
  - runs the preflight, answers `409` when it reports a blocker, then deletes
    each account as `DELETE /api/v1/account/{uid}/` does, each in its own
    transaction; `409` lists any account that could not be deleted
  - the same identities that may delete a portfolio may delete an account; both
    routes are registry writes that record the acting identity
- `GET /api/v1/account/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for account detail
    pages
  - resolves the account by `uid`
- `GET /api/v1/account/target-allocation/targets/`
  - supports `search`, `target_type=all|asset|portfolio`, `include_retired`,
    `limit`, and `offset`; retired portfolios are left out unless
    `include_retired=true`
    ([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md))
  - returns one paginated candidate list for target-position assignment
  - returns `command-center.resource_collection@v1` and exposes
    `GET /api/v1/account/target-allocation/targets/discovery/`
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
    `target_row_key`, and `position_set_uid` when the row carries them. Rows
    written since 3.6.0 carry `position_set_uid` only: a delta is computed from
    the target and the holdings, never stored (ADR 0053)
  - `residuals` are derived as source account signed quantity minus total
    virtual-fund allocated signed quantity per asset
  - asset labels use latest `AssetSnapshotsStorage` rows; OpenFIGI and numeric
    asset IDs are not used
  - this read endpoint does not rerun or apply the allocation planner; it
    shows what an allocation wrote
    ([ADR 0053](../../ADR/0053-virtual-fund-allocation-routes-and-described-policies.md))
- `GET /api/v1/account/virtual-fund-allocation-policies/`
  - operation `getVirtualFundAllocationPolicies`; answers every allocation
    policy with its `id`, `version`, `title`, `description` and the `path` of
    its description; holds no account data
- `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/`
  - operation `getVirtualFundAllocationPolicy`; describes one policy: each
    argument's JSON Schema 2020-12 and `arguments_schema` over all of them,
    generated from the class that validates a request's `policy.arguments`
  - an unknown id is a `404`
- `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/`
  - operation `planAccountVirtualFunds`; runs a policy and writes nothing
  - request body contains `position_set_uid`, `valuation_time` and an optional
    `policy` (`id`, `version`, `arguments`); without one,
    `proportional_attribution` runs with its defaults
  - the snapshot is the account's holdings set at exactly `valuation_time`;
    targets and holdings are both in units, so the body carries no price, NAV
    or valuation
  - answers `funds`, `lines`, `account_deltas`, `apply_blockers` and
    `plan_digest`; each line has an `owner` (`fund` or `direct`), a `target`,
    what is `assigned` and `delta = target - assigned`
  - a positive delta means units are missing, a negative one more units than
    the target asks for; the target is the full picture, so an asset the
    account holds that no target names has a target of zero
  - a plan has no status and no deficits list: a shortfall is a positive
    account delta
- `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`
  - operation `allocateAccountVirtualFunds`; plans again from the same inputs
    and writes the virtual funds, one holdings set per fund and the holdings
    rows in one transaction; never accepts a plan from the client
  - the body is the plan request plus an optional `plan_digest`; a recomputed
    plan with another digest is a `409` `plan_changed`
  - answers the plan with `applied`, `already_applied` and each fund's
    `virtual_fund_uid` and `holdings_set_uid`
  - a shortfall is not refused; an applied allocation is account history, so
    the same plan again writes nothing and a different allocation of the same
    snapshot is a `409` `allocation_exists`; a retired portfolio is a `409`
    `portfolio_retired`
  - errors are structured: `detail` has a `code`, a `message` and the `errors`
    it is about
- `POST /api/v1/account/{account_uid}/add-holdings/`
  - writes one account holdings snapshot and returns the same
    `AccountHoldingsSnapshotResponse` contract as the holdings read endpoint
  - costs three MetaTables operations whatever the number of positions: read
    the account, read every position's asset in one select, and write; the
    response is built from the rows the write returns, not read back
  - request body contains `holdings_date`, `overwrite`, and `positions`
  - each position uses the storage field name `asset_identifier`; one `400`
    names every unknown `asset_identifier`
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
  - every position is in units (ADR 0052): `asset_uid`, a positive `quantity`
    in the asset's own unit, and a `direction` (`1` long, `-1` short, default `1`)
  - an asset row (`target_type="asset"`, `target_uid=asset_uid`) is a direct
    target
  - a portfolio row (`target_type="portfolio"`, `target_uid=portfolio_uid`,
    plus `asset_uid`) is one asset of that virtual fund's unit basket; the rows
    of one `portfolio_uid` are the whole basket
  - the caller sizes each basket with its own prices and rules; the route values
    nothing and accepts no share of NAV or notional amount
  - `metadata_json` may record how a row was sized (scale factor, portfolio book
    time, mandate share, source); it is stored and never read
  - `overwrite=false` rejects an existing position set at the same timestamp;
    `overwrite=true` replaces rows through one scoped MetaTable operation so the
    parent upserts, delete, and replacement insert share the same backend
    transaction boundary
  - an empty `positions` list clears the account's target: it writes an empty
    position set at `target_positions_date`, so the target's history shows when
    it was cleared, and sets the account's target allocation inactive. The
    response is that empty snapshot; the read then answers no positions until a
    new target is written, which makes the allocation active again. A refused
    write (`overwrite=false` on an existing snapshot) changes neither the rows
    nor the allocation's `is_active`
  - a snapshot that names a retired portfolio is refused with `409`, whatever
    its date, and writes nothing: the statement locks the named portfolio rows
    and writes only when every one is live
    ([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md))
  - `MarketsClient.add_account_target_positions(...)`,
    `account_target_positions(...)` and `clear_account_target_positions(...)`
    call these routes and return `AccountTargetPositionsSnapshotResponse`
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
