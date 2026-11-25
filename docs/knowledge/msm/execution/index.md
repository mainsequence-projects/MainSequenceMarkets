# Execution

The execution concept owns batches of orders (`OrderManager`), the orders themselves
(`Order`), and what happens to them over time: their state, status events and trades
([ADR 0064](../../../ADR/0064-an-order-has-its-own-row.md)).

## Scope

Execution answers these questions:

- Which batch created an order, for which account and asset, on which terms?
- What did the venue report about the order over time?
- Which order events and trades were observed, and for which order?

## Primary Modules

- `msm.models.execution`: SQLAlchemy models for `OrderManagerTable` and `OrderTable`.
- `msm.api.execution`: typed rows `OrderManager` and `Order`; `OrderManager.create_batch`.
- `msm.time_index.execution`: the storages `OrdersTS`, `OrderEventsTS` and `TradesTS`,
  their updaters, and `write_execution`.
- `msm.repositories.execution`: the statements both writes compile.

## Key Contracts

An order has one `Order` row, keyed by `uid`: the order's own UUID, minted by the
application that creates it and unique across accounts. The row holds the account,
asset, order manager and the terms the order was created with (side, type, quantity,
limit price, time in force, expiry, `client_order_id`). It never changes once written;
a replaced order is a new order that names the one it replaces (`replaces_order_uid`,
same account and asset).

The execution storages reference it:

| Storage | Key | References |
|---|---|---|
| `OrdersTS` | `(order_time, order_uid)` | `Order.uid`; holds status, fills, `order_remote_id`, venue metadata |
| `OrderEventsTS` | `(event_time, order_uid)` | `Order.uid` |
| `TradesTS` | `(trade_time, trade_identifier)` | `(order_uid, account_identifier, asset_identifier)` of its `Order`, when it has one |

A trade of an order therefore has the order's account and asset; a trade without an
order has a null `order_uid`. Every key is `RESTRICT`. Core execution does not carry
fund or `VirtualFundTable` references.

## Writing a batch

A batch is two requests, whatever its size, and no updater run (issue #131):

```python
import datetime as dt
import uuid

from msm.api.execution import OrderManager
from msm.time_index.execution import write_execution

batch = OrderManager.create_batch(
    unique_identifier="rebalance-2026-05-26",
    target_account_uid="00000000-0000-0000-0000-000000000000",
    target_time=dt.datetime.now(dt.UTC),
    status="submitted",
    orders=[
        {"uid": uuid.uuid4(), "account_identifier": "account-1", "asset_identifier": "AAPL",
         "order_side": 1, "order_type": "market", "quantity": 10.0},
    ],
)

now = dt.datetime.now(dt.UTC)
written = write_execution(
    [
        {
            "order": batch.orders[0],
            "states": [{"order_time": now, "status": "filled", "filled_quantity": 10.0}],
            "events": [{"event_time": now, "order_status": "filled"}],
            "trades": [{"trade_time": now, "trade_identifier": "fill-1", "quantity": 10.0}],
        }
    ],
    orders_table=MyOrders,           # the application's classes on OrdersInstance etc.
    order_events_table=MyOrderEvents,
    trades_table=MyTrades,
)
```

- `create_batch` upserts the `OrderManager` row and inserts its orders in one
  transaction. An order that exists already is left as it is, so a batch sent again
  writes no order twice. It answers `OrderBatch`: the batch, the orders written, and
  `failed`.
- `write_execution` upserts the state rows, events and trades on each table's key in one
  transaction, on the application's own runtime. A row written under an order takes its
  `order_uid` (a trade also its account and asset); one that states another value is
  refused. Trades of an order written by an earlier call go in `trades=[...]` with their
  `order_uid`. A call that does not fit one MetaTables transaction (32 statements,
  12,100,000 bytes) is refused before anything is sent.
- Both write every row they may (issue #128): a row that fails validation or repeats a
  key is listed in `failed`; when the database refuses the transaction, each order is
  written on its own, so only the refused ones stay out.

The `Orders`, `OrderEvents` and `Trades` updaters still write a frame set with
`set_frame`, through an update execution.

## Upgrading to 6.0.0

Revision `0037` migrates Markets' own execution tables. An application's instances
reference Markets' `Order`, so its orders need `Order` rows before its own revision adds
that key: `msm.time_index.execution.upgrade.orders_from_legacy_states(old_rows)` builds
them from the instance's pre-6.0.0 `OrdersTS` rows for `Order.upsert_many`, and
`order_uid_for_identifier` gives each identifier the uid revision `0037` gives it. The
skill `.agents/skills/ms_markets/accounts/execution_workflow/SKILL.md` has the steps.

## Extension Notes

Add new execution storage shapes in `msm.time_index.execution`. Add new
registry or manager metadata in `msm.models.execution`, then expose it through
repository and service functions.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
- [Models](../models/index.md)
