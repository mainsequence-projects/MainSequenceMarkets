# Execution

The execution concept owns trading workflow records: order managers, target
quantities, orders, order status events, trades, and execution errors.

## Scope

Execution answers these questions:

- Which manager or strategy emitted an order?
- Which account, fund, portfolio, or asset is targeted?
- Which order events and trades were observed?
- Which execution errors need to be stored for audit or recovery?

## Primary Modules

- `msm.execution.data_nodes`: DataNodes for orders, order events, trades, and
  execution errors.
- `msm.models.execution`: SQLAlchemy execution models.
- `msm.api.execution`: typed row APIs for `OrderManager`,
  `OrderTargetQuantity`, `Order`, `OrderStatusEvent`, `Trade`, and
  `ExecutionError`.
- `msm.repositories.execution` and `msm.services.execution`: MetaTable operation
  builders and service helpers for execution records.

## Key Contracts

Execution DataNodes use explicit time indexes for each event family:

- `order_time` for orders.
- `event_time` for order status events.
- `trade_time` for trades.
- `time_recorded` for execution errors.

Execution records should preserve enough raw platform or broker payload in JSON
fields for audit, but normalized identifiers should still be present for joins.

Use class-owned lifecycle methods where they express the domain operation:

```python
import datetime as dt

from msm.api.execution import Order, OrderManager

manager = OrderManager.create_batch(
    unique_identifier="rebalance-2026-05-26",
    target_account_uid="00000000-0000-0000-0000-000000000000",
    target_time=dt.datetime.now(dt.UTC),
    status="created",
)
event = Order.record_status(
    order_status="accepted",
    order_unique_identifier=manager.unique_identifier,
)
```

Append-only rows such as `OrderStatusEvent` and `ExecutionError` use explicit
creation methods and do not pretend that every lifecycle event is a generic
upsert.

## Extension Notes

Add new execution storage shapes in `data_nodes`. Add new registry or manager
metadata in `msm.models.execution`, then expose it through repository and
service functions.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../portfolios/index.md)
- [Models](../models/index.md)
