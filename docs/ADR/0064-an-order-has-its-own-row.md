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

A Markets `Order` table holds one row per order: its identifier, account, asset and order
manager. `OrdersTS` keeps the order's state over time; `OrderEventsTS` and `TradesTS` keep
its events and fills.

### 2. An order's identifier is an internal UUID, unique across accounts (owner)

`order_identifier` is the order's own UUID, minted by the application that creates the
order. It is unique across every account, not per account. A venue's ids stay in
`order_remote_id` and `client_order_id`.

### 3. `OrdersTS` is unique on `(order_time, order_identifier)` (owner)

The account, the asset and the order manager are properties of the order, so they leave
`OrdersTS` and live on the `Order` row. `OrderEventsTS` already has this shape:
`(event_time, order_identifier)`.

### 4. Trades are written inline with their orders (owner)

One call writes an order's state rows, its events and its trades in one MetaTables statement
transaction (MetaTables ADR 0026), without an updater run. A trade written under its order
takes the order's identifier. This is the write of issue #131.

### 5. The execution tables reference the order

- `OrdersTS.order_identifier` and `OrderEventsTS.order_identifier` reference `Order`, not
  null.
- `TradesTS.order_identifier` references `Order` and stays nullable: a trade without an order
  is still recorded.
- The keys are `RESTRICT`, as the execution tables' keys to accounts and assets are today.

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

## What It Changes

- **ADR 0050.** Orders are unique across accounts. Order events have a key to their order,
  so the account delete removes an account's events through its orders, and
  `ordered_by_another_account` goes. The delete removes, in order: order events, trades,
  order state rows, orders, order managers.
- **Execution Engine ADR 0001.** Its recorder writes a round as decision 7 says: the
  `OrderManager` and `Order` rows in one Markets call, then the `OrdersTS`, `OrderEventsTS`
  and `TradesTS` rows in one transaction. Its fund fills can hold a key to their trade,
  `(trade_time, trade_identifier)`.
- **`msm.time_index.execution`.** `validate_execution_frame` reads the key columns from each
  table, so it follows the new keys. `OrderEvents` already runs without `asset_identifier` in
  its key, so `Orders` and `Trades` can too. Their time-index statistics are kept per order
  and per trade.
- **Migrations.** A Markets revision creates `Order` and changes the keys of the three Markets
  execution tables. Every application's instances of those tables need a revision in the
  application's own migrations. This is a major release.
- **SQLite.** Dropping a column that holds a foreign key rebuilds the table. No key points
  into `OrdersTS` or `TradesTS`, so the rebuild does not change how the database refuses a
  delete.

## Consequences

- A trade and an event can only name an order that exists.
- An order's account, asset and order manager are stored once.
- Writing a batch takes two requests, whatever its size, instead of a run per table.
- Reading an order with its trades is one lookup by key. `TradesTS.order_identifier` needs
  an index for it.

## Not Decided Here

- The names: `Order`, and whether the columns become `order_uid` of type UUID (the naming of
  ADR 0048) or keep `order_identifier`.
- Whether the order's terms (side, type, quantity, limit price, time in force, expiry) move
  to `Order` or stay on `OrdersTS`, where a replaced order can change them.
- Whether a trade under an order must have the order's account and asset, enforced by a key
  to `(uid, account, asset)` of `Order`.
- The size limit of one call: one transaction holds at most 32 statements.
- A read of orders with their trades.

## Not Verified

- That existing `OrdersTS` rows have UUID identifiers, and that no two accounts share one.
  The hosted data was not read. A backfill of `Order` from `OrdersTS` fails on either.
- The time of the two requests on the hosted API.
