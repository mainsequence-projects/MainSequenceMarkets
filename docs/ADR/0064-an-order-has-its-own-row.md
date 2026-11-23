# 0064. An Order Has Its Own Row

## Status

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23, from the analysis of
issue #131. Nothing in it is implemented.

- The decisions marked (owner) were made by the owner on 2026-11-23. Everything else is a
  proposal, the names included.
- It would amend [ADR 0050](0050-account-deletion.md): orders are unique across accounts,
  and order events get a key.
- It changes the records [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md)
  writes: its recorder writes the orders of a round with their trades in one transaction.

## Context

An order has no row of its own. It exists only as its rows in `OrdersTS`
(`src/msm/time_index/execution/storage.py`), one for each `order_time` at which its state was
recorded. So nothing can reference an order:

- `OrdersTS` is unique on `(order_time, order_identifier, account_identifier,
  asset_identifier)`. A foreign key needs a unique target, and `order_identifier` alone is
  not unique there: one order has several rows.
- `TradesTS.order_identifier` is a plain nullable string, with no key and no index.
- `OrderEventsTS.order_identifier` is a plain string, with no key.
- ADR 0050 records that orders are unique per account, not across accounts. The account
  delete therefore keeps an order event whose identifier another account's order also uses
  (`ordered_by_another_account` in `src/msm/repositories/account_deletion.py`).

Because nothing references an order, the account and the asset are part of every execution
table's unique key, and a trade is linked to its order only by what its writer put in a
string column.

Writing is slow for the same reason. An application writes its orders with an `Orders`
updater run and its trades with a `Trades` updater run, one after the other. A run is a
MetaTables update execution of 13 sequential requests, about 37 s in the hosted Production
Environment for a frame of 2 rows (mainsequence-projects/MetaTables#154). Issue #131
measured a sync with fills at 147.1 s, of which about 86 s were the two runs.

## Decision

### 1. An order has its own row (owner)

A Markets `Order` table holds one row per order. `OrdersTS` keeps the order's state over
time; `OrderEventsTS` and `TradesTS` keep its events and fills. Decision 10 says which
columns are on the order's row.

### 2. An order's identifier is an internal UUID, unique across accounts (owner)

The order's identifier is its own UUID, minted by the application that creates the order.
It is unique across every account, not per account. A venue's ids stay in
`order_remote_id` and `client_order_id`.

### 3. `OrdersTS` is unique on `(order_time, order_uid)` (owner)

The account, the asset and the order manager are properties of the order, so they leave
`OrdersTS` and live on the `Order` row. `OrderEventsTS` already has this shape:
`(event_time, order_identifier)`, which becomes `(event_time, order_uid)`. The column's
name is decision 9's.

### 4. Trades are written inline with their orders (owner)

One call writes an order's state rows, its events and its trades in one MetaTables statement
transaction (MetaTables ADR 0026), without an updater run. A trade written under its order
takes the order's `order_uid`. This is the write of issue #131.

### 5. The execution tables reference the order

- `OrdersTS.order_uid` and `OrderEventsTS.order_uid` reference `Order.uid`, not null.
- `TradesTS.order_uid` stays nullable: a trade without an order is still recorded.
- A trade's `(order_uid, account_identifier, asset_identifier)` references the same three
  columns of `Order`, which has a unique index on them. The database then refuses a trade
  whose account or asset is not its order's, and no code checks it. A trade without an
  order passes: PostgreSQL and SQLite do not check a key with a null column (`MATCH
  SIMPLE`, the default of both).
- The keys are `RESTRICT`, as the execution tables' keys to accounts and assets are today.
- An application's instances of these tables get the same keys: `storage_instances`
  already copies keys of several columns.

### 6. `TradesTS` is unique on `(trade_time, trade_identifier)`

A trade's account and asset never change, so they leave its unique key. They stay as
columns of `TradesTS`, because a trade may have no order.

### 7. The `Order` row lives in the Markets namespace

It sits next to `OrderManager`, and is written by the same Markets call that writes the
batch: `create_batch` takes the batch's orders and writes the `OrderManager` row and the
`Order` rows in one transaction. An application's instances of `OrdersTS`, `OrderEventsTS`
and `TradesTS` already hold keys to Markets' `OrderManager`; their keys to `Order` follow
the same pattern.

An application then writes a batch in two requests:

1. The Markets call: the batch and its orders.
2. Its own transaction: the orders' state rows, their events and their trades.

A sync with fills is one request, the second.

### 8. Bulk calls follow the rule of issue #128

Both calls write every row they may and answer what they did not, with the reason. A refused
order refuses the state rows, events and trades written under it. A refused trade does not
refuse its order.

### 9. The column is `order_uid`, a UUID

The value is a UUID, so it is stored as one; a string column would not refuse a value that
is not one. ADR 0048 names a column after the identity it holds, `*_uid` for a uid, as
`OrderManager.target_account_uid` does. A UUID in a time-index key has a precedent:
`VirtualFundHoldingsStorage` is keyed on `virtual_fund_uid`.

- `Order.uid` is the order's UUID, minted by the application. `Order` has no separate
  `unique_identifier`; it is upserted on `uid`.
- `order_identifier` is renamed `order_uid` in `OrdersTS`, `OrderEventsTS` and `TradesTS`.
  The keys change anyway, so nothing keeps the old name.

### 10. What is known when the order is created is on `Order`

- **`Order`:** `uid`, `account_identifier`, `asset_identifier`, `order_manager_identifier`,
  `order_side`, `order_type`, `quantity`, `limit_price`, `time_in_force`, `expires_time` and
  `client_order_id`. `create_batch` knows all of them when it writes the order, and none of
  them changes.
- **`OrdersTS`:** `order_time`, `order_uid`, `status`, `filled_quantity`, `filled_price`,
  `order_remote_id`, `venue_metadata` and `comments`: what the venue reports. The remote id
  arrives with the venue's answer, in the same write as the state, so a sync makes no
  Markets call to update the `Order` row.
- **A replaced order is a new order.** It has its own `Order` row, which names the order it
  replaces (`replaces_order_uid`). Many venues already give a replacement a new id. An
  `Order` row therefore never changes after it is written.

### 11. One call takes what one transaction holds

ms-markets sets no row limit of its own: a cap would be a business rule made of a MetaTables
limit.

- Inside the transaction, each table's rows are split into statements by the limits
  `bulk_upsert_model` keeps today (#84): 32,766 bound values, 10,000 rows and 1,000,000 SQL
  characters per statement. A trade row has about 15 columns, so a statement holds about
  2,000 trades, and a transaction of 32 statements tens of thousands of rows.
- A call is never split into several transactions: an order is written with its trades or
  not at all.
- A call that does not fit one transaction (more than 32 statements, or a request larger
  than the 12,100,000 bytes MetaTables accepts) is refused before anything is sent, with the
  limit it exceeded.
- If real batches come near that, it is a MetaTables issue, not a limit to add here.

## What It Changes

- **ADR 0050.** Orders are unique across accounts. Order events have a key to their order,
  so the account delete removes an account's events through its orders, and
  `ordered_by_another_account` goes. The delete finds an account's orders on `Order`, which
  has an index on `account_identifier`, in place of the `(account_identifier, order_time)`
  index of `OrdersTS`. It removes, in order: order events, trades, order state rows, orders,
  order managers.
- **Execution Engine ADR 0001.** Its recorder writes a round as decision 7 says: the
  `OrderManager` and `Order` rows in one Markets call, then the `OrdersTS`, `OrderEventsTS`
  and `TradesTS` rows in one transaction. Its fund fills can hold a key to their trade,
  `(trade_time, trade_identifier)`.
- **`msm.time_index.execution`.** `validate_execution_frame` reads the key columns from each
  table, so it follows the new keys. `_normalize_execution_values` raises on the `UUID`
  dtype today and needs a branch for it. `OrderEvents` already runs without
  `asset_identifier` in its key, so `Orders` and `Trades` can too. Their time-index
  statistics are kept per order and per trade.
- **Migrations.** A Markets revision creates `Order` and changes the keys and columns of the
  three Markets execution tables. Every application's instances of those tables need a
  revision in the application's own migrations. This is a major release.
- **SQLite.** Dropping a column that holds a foreign key rebuilds the table. No key points
  into `OrdersTS` or `TradesTS`, so the rebuild does not change how the database refuses a
  delete.

## Consequences

- A trade and an event can only name an order that exists, and a trade under an order has
  the order's account and asset.
- An order's account, asset, manager and terms are stored once, and never change.
- Writing a batch takes two requests, whatever its size, instead of a run per table.
- Reading an order with its trades is one lookup by key. `TradesTS.order_uid` needs an index
  for it.

## Not Decided Here

- The names `Order` and `replaces_order_uid`.
- A read of orders with their trades.

## Not Verified

- That existing `OrdersTS` rows have UUID identifiers, and that no two accounts share one.
  The hosted data was not read. A backfill of `Order` from `OrdersTS` fails on either.
- That the order terms of existing `OrdersTS` rows never change between rows of one order;
  the backfill takes them from one row.
- That a call of a few thousand rows finishes within MetaTables' write deadline on the hosted
  API.
- The time of the two requests on the hosted API.
