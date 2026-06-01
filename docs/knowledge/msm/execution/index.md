# Execution

The execution concept owns order-manager intent rows and timestamped execution
facts for orders, order status events, and trades.

## Scope

Execution answers these questions:

- Which manager or strategy emitted an order?
- Which account or asset is targeted?
- Which order events and trades were observed?

## Primary Modules

- `msm.data_nodes.execution`: DataNodes for orders, order events, and trades.
- `msm.models.execution`: SQLAlchemy models for `OrderManagerTable`.
- `msm.api.execution`: typed row API for `OrderManager`.
- `msm.repositories.execution` and `msm.services.execution`: MetaTable operation
  builders and service helpers for order-manager intent records.

## Key Contracts

Execution DataNodes use explicit time indexes for each event family:

- `order_time` for orders.
- `event_time` for order status events.
- `trade_time` for trades.

Their storage MetaTable identifiers use the same `CamelCase` style as domain
MetaTables plus a `TS` suffix: `OrdersTS`, `OrderEventsTS`, and `TradesTS`.
There are no separate row-oriented `Order`, `OrderStatusEvent`, `Trade`, or
`OrderTargetQuantity` MetaTables; those facts are storage-first, matching the
account-holdings pattern.

Execution records should preserve enough raw platform or broker payload in JSON
fields for audit, but normalized identifiers should still be present for joins.
Core execution does not carry a `FundTable` foreign key. Fund-linked execution
workflows should be added in `msm_portfolios` as extensions when needed.

Use class-owned lifecycle methods only for order-manager intent:

```python
import datetime as dt

from msm.api.execution import OrderManager

manager = OrderManager.create_batch(
    unique_identifier="rebalance-2026-05-26",
    target_account_uid="00000000-0000-0000-0000-000000000000",
    target_time=dt.datetime.now(dt.UTC),
    status="created",
)
```

Publish observed orders, order events, and trades through their DataNodes:
`Orders`, `OrderEvents`, and `Trades`.

## Extension Notes

Add new execution storage shapes in `msm.data_nodes.execution`. Add new
registry or manager metadata in `msm.models.execution`, then expose it through
repository and service functions.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
- [Models](../models/index.md)
