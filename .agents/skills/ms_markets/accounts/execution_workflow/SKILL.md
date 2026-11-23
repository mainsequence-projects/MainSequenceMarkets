---
name: mainsequence-markets-execution-workflow
description: Use this skill when a library or application that uses ms-markets records orders, order batches, order status events or trades (fills) for an account; creates OrderManager batches with their Order rows; writes OrdersTS, OrderEventsTS or TradesTS rows with write_execution; declares its own instances of those tables; or upgrades its execution rows to ms-markets 6.0.0.
---

# Orders, Order Events And Trades

Use this skill when a workflow sends orders to a venue and records what happened: the
batch, each order, its state over time, its status events and its fills.

ms-markets is a record library: it stores what the application tells it, in two requests
per batch, and computes nothing.

## Owning Context

Read with:

1. `docs/knowledge/msm/execution/index.md`: the records and the two calls
2. `docs/ADR/0064-an-order-has-its-own-row.md`: why an order has its own row
3. `.agents/skills/ms_markets/platform/producer_boundary/SKILL.md`: the application's own
   tables (instances) and what Markets never does with them
4. `.agents/skills/ms_markets/platform/metatable_migrations/SKILL.md`: migrating them
5. `.agents/skills/ms_markets/accounts/account_workflow/SKILL.md`: the account itself

## The Records

| Record | Table | Key | Where it lives | Written by |
| --- | --- | --- | --- | --- |
| A batch of orders | `OrderManager` | `unique_identifier` | Markets | `OrderManager.create_batch` |
| An order | `Order` | `uid`, the order's own UUID | Markets | `OrderManager.create_batch` |
| An order's state over time | `OrdersTS` | `(order_time, order_uid)` | The application's instance | `write_execution` |
| An order's status events | `OrderEventsTS` | `(event_time, order_uid)` | The application's instance | `write_execution` |
| A trade (fill) | `TradesTS` | `(trade_time, trade_identifier)` | The application's instance | `write_execution` |

- An `Order` row holds the account, the asset, the batch (`order_manager_identifier`)
  and the terms the order was created with: `order_side`, `order_type`, `quantity`,
  `limit_price`, `time_in_force`, `expires_time`, `client_order_id`. It never changes.
- `OrdersTS` holds what the venue reports: `status`, `filled_quantity`, `filled_price`,
  `order_remote_id`, `venue_metadata`, `comments`.
- `OrdersTS.order_uid` and `OrderEventsTS.order_uid` reference `Order.uid`. A trade's
  `(order_uid, account_identifier, asset_identifier)` references the same three columns
  of its `Order`, so a trade of an order has the order's account and asset. A trade
  without an order (a transfer, a corporate action) has `order_uid = None`.
- Every key is `RESTRICT`.

## Declare The Application's Tables

The application writes its execution rows into its own instances of the three storages,
in its own namespace, migrated by its own provider. Declare them on the application's
own base:

```python
from metatables import sqlalchemy_naming_convention
from msm.storage_instances import configured_time_index_instance
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


def _instance(storage):
    return configured_time_index_instance(
        storage, instance_key="main", namespace="my-app", storage_app="my_app", base=Base
    )


MyOrders = _instance(OrdersStorage)
MyOrderEvents = _instance(OrderEventsStorage)
MyTrades = _instance(TradesStorage)
```

The instances carry the contract's keys into Markets' `Order`, `Account` and `Asset`.
Attach them to the application's runtime (`msm.start_engine(models=[MyOrders,
MyOrderEvents, MyTrades, ...])`). Never write Markets' own `OrdersTS`, `OrderEventsTS` or
`TradesTS` from an application: they are `write_execution`'s defaults only for Markets
itself.

## Create A Batch With Its Orders

Mint each order's uid before sending it to the venue and keep it with the order: it is
the order's identity in every record, unique across accounts. A venue's ids go in
`client_order_id` (what the application sent) and, later, `order_remote_id` (what the
venue answered).

```python
import datetime as dt
import uuid

from msm.api import OrderManager

orders = [
    {
        "uid": uuid.uuid4(),
        "account_identifier": "account-1",
        "asset_identifier": "AAPL",
        "order_side": 1,
        "order_type": "limit",
        "quantity": 10.0,
        "limit_price": 101.5,
        "time_in_force": "day",
    },
]
batch = OrderManager.create_batch(
    unique_identifier="rebalance-2026-11-23T15:42",
    target_account_uid=account_uid,
    target_time=dt.datetime.now(dt.UTC),
    status="submitted",
    orders=orders,
)
```

- One Markets call, one transaction: the batch is upserted on `unique_identifier` and its
  orders inserted. An order's `order_manager_identifier` is the batch's; leave it out.
- Sending the same batch again is safe: an order that exists is left as it is, and the
  batch's own fields (`status`, `execution_end`, ...) are updated.
- The answer is `OrderBatch`: `order_manager`, `orders` (the `Order` rows written) and
  `failed` (`uid`, `position`, `detail` of each order not written).

## Record What Happens

```python
from msm.time_index.execution import write_execution

now = dt.datetime.now(dt.UTC)
written = write_execution(
    [
        {
            "order": batch.orders[0],
            "states": [{"order_time": now, "status": "filled", "filled_quantity": 10.0,
                        "filled_price": 101.4, "order_remote_id": "venue-987"}],
            "events": [{"event_time": now, "order_status": "filled"}],
            "trades": [{"trade_time": now, "trade_identifier": "venue-fill-1",
                        "trade_side": 1, "quantity": 10.0, "price": 101.4}],
        },
    ],
    orders_table=MyOrders,
    order_events_table=MyOrderEvents,
    trades_table=MyTrades,
)
```

- One transaction on the application's runtime, no update execution: the orders' state
  rows first, then their events, then their trades, each upserted on its table's key.
  Writing a state row again at the same `order_time` updates it.
- `order` is an `Order` row from `create_batch`, or a mapping with its `uid`,
  `account_identifier` and `asset_identifier`. A state row and an event take its
  `order_uid`; a trade also its account and asset. Leave them out: a row that states
  another value is refused.
- A later fill of an order written earlier goes in `trades=[...]`, with its `order_uid`,
  `account_identifier` and `asset_identifier`. So does a trade without an order.
- Timestamps carry a timezone. Columns not given are written as null.
- The answer is `ExecutionWrite`: the rows written per table (`order_states`,
  `order_events`, `trades`) and `failed` (`table`, `key`, `detail`).

## Read The Answer

Both calls write every row they may (issue #128); nothing in `failed` was written.

| Refused | Why | What the rest does |
| --- | --- | --- |
| One row | Unknown column, missing required value, naive timestamp, a value of the wrong type, a key repeated in the call, a value that contradicts its order | Written |
| One order's rows | The database refused them: the order does not exist, an unknown asset or account, another application's key | Written, each order in its own transaction |
| The call | It needs more than 32 statements or 12,100,000 bytes, one MetaTables transaction | Nothing written; `ValueError` before anything is sent |

Retry what `failed` lists after correcting it; the rows written are not written twice.

## Rules

- Never update or delete an `Order` row. A replaced order is a new order with its own uid
  that names the one it replaces: `replaces_order_uid`, same account and asset.
- One uid per order, across every account. Never reuse a venue id as the uid.
- Record execution with `create_batch` and `write_execution`. The `Orders`,
  `OrderEvents` and `Trades` updaters still exist for a frame set with `set_frame`, but
  each run is an update execution of many sequential requests.
- ms-markets has no read of an order with its trades; read the application's own tables.
- An account is deleted with its whole history (ADR 0050). Rows in the application's
  instances reference its orders with `RESTRICT`: the application deletes them first, or
  the account delete is refused.

## Upgrading An Application To 6.0.0

6.0.0 re-keys the execution tables (ADR 0064). Markets' revision `0037` migrates
Markets' own tables. The application migrates its instances, in this order:

1. **Markets is at 6.0.0.** Its migration created `Order` and re-keyed its own tables.
2. **Give the application's orders their `Order` rows.** Read the instance's `OrdersTS`
   rows as they still are (`order_time`, `order_identifier`, `account_identifier`,
   `asset_identifier`, `order_manager_identifier` and the terms) with plain SQL, then:

   ```python
   from msm.api import Order
   from msm.time_index.execution.upgrade import orders_from_legacy_states

   Order.upsert_many(orders_from_legacy_states(old_rows))
   ```

   Each identifier becomes `order_uid_for_identifier(identifier)`: itself when it is a
   UUID, else its `uuid5`, exactly as revision `0037` maps Markets' own. An identifier
   whose rows name two accounts or assets raises `ValueError`; correct those rows first.
3. **The application's revision** re-keys its instances as revision `0037` does: add
   `order_uid`, set it with `order_uid_for_identifier` on every state row, event and trade
   (null for a trade without an order), drop `order_identifier` and the columns that
   moved to `Order` from `OrdersTS`, create the new unique indexes and the keys into
   `Order`. Revision `0037` is the template:
   `msm_migrations/versions/mainsequence_markets/0037_an_order_has_its_own_row.py`.
4. **Switch the writes** to `create_batch(..., orders=...)` and `write_execution`.
   `create_batch` now answers `OrderBatch`; read the batch from `batch.order_manager`.
