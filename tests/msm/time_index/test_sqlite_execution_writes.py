"""A batch's orders and what happens to them, written without an updater run (ADR 0064, #131).

``OrderManager.create_batch`` writes the batch and its ``Order`` rows in one transaction;
``write_execution`` writes the orders' state rows, events and trades in one transaction.
Both run end to end on a migrated SQLite DataSource, through MetaTables' own SQLite
backend, which enforces the tables' keys.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from metatables import MetaTable

from msm.api import Order, OrderManager
from msm.time_index.execution import OrderExecution, write_execution
from msm.time_index.execution.writes import MAX_TRANSACTION_STATEMENTS
from tests.support.sqlite_markets import _account, _asset, _count, _rows, serve_row_operations

WHEN = dt.datetime(2026, 11, 23, 15, 42, tzinfo=dt.UTC)


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    engine = sqlite_markets.engine
    account = _account(engine)
    (row,) = _rows(engine, "SELECT unique_identifier FROM ms_markets__account WHERE uid = :uid", uid=account.hex)
    _asset(engine, "AAPL")
    _asset(engine, "MSFT")
    sqlite_markets.account = account
    sqlite_markets.account_identifier = row["unique_identifier"]
    sqlite_markets.transactions = []
    execute_transaction = MetaTable.execute_transaction.__func__

    def counted(cls, transaction, *, timeout=None):
        sqlite_markets.transactions.append(len(transaction.statements))
        return execute_transaction(cls, transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(counted))
    return sqlite_markets


def _order(markets, asset: str = "AAPL", **terms) -> dict:
    return {
        "uid": uuid.uuid4(),
        "account_identifier": markets.account_identifier,
        "asset_identifier": asset,
        "order_side": 1,
        "order_type": "market",
        "quantity": 10.0,
        **terms,
    }


def _batch(markets, orders, identifier: str = "batch-1"):
    return OrderManager.create_batch(
        unique_identifier=identifier,
        target_account_uid=markets.account,
        target_time=WHEN,
        status="submitted",
        orders=orders,
    )


# The batch -------------------------------------------------------------------------------


def test_a_batch_and_its_orders_are_one_transaction(markets) -> None:
    orders = [_order(markets), _order(markets, "MSFT", order_side=-1)]

    batch = _batch(markets, orders)

    assert markets.transactions == [3]  # the batch, its orders, the batch's row to answer
    assert batch.failed == []
    assert batch.order_manager.unique_identifier == "batch-1"
    assert [order.uid for order in batch.orders] == [order["uid"] for order in orders]
    assert {order.order_manager_identifier for order in batch.orders} == {"batch-1"}
    assert _count(markets.engine, "ms_markets__order") == 2


def test_a_batch_sent_again_writes_no_order_twice(markets) -> None:
    orders = [_order(markets)]
    _batch(markets, orders)

    again = _batch(markets, [{**orders[0], "quantity": 99.0}])

    assert again.failed == []
    (stored,) = _rows(markets.engine, "SELECT quantity FROM ms_markets__order")
    assert stored["quantity"] == 10.0  # an order never changes once written


def test_a_refused_order_does_not_stop_the_others(markets) -> None:
    good, unknown_asset = _order(markets), _order(markets, "NOPE")
    invalid = {"uid": "not-a-uuid", "account_identifier": markets.account_identifier}

    batch = _batch(markets, [good, unknown_asset, invalid])

    assert [order.uid for order in batch.orders] == [good["uid"]]
    assert [(item.uid, item.position) for item in batch.failed] == [
        (None, 2),
        (unknown_asset["uid"], None),
    ]
    assert "FOREIGN KEY" in batch.failed[1].detail
    assert _count(markets.engine, "ms_markets__order") == 1
    assert _count(markets.engine, "ms_markets__ordermanager") == 1


def test_an_order_of_another_batch_is_refused(markets) -> None:
    order = _order(markets, order_manager_identifier="batch-2")

    batch = _batch(markets, [order])

    assert batch.orders == []
    assert "is not the batch's 'batch-1'" in batch.failed[0].detail


def test_a_replacement_names_an_order_of_its_own_account_and_asset(markets) -> None:
    first = _order(markets)
    _batch(markets, [first])
    other_asset = _order(markets, "MSFT", replaces_order_uid=first["uid"])
    replacement = _order(markets, replaces_order_uid=first["uid"], quantity=12.0)

    batch = _batch(markets, [other_asset, replacement], identifier="batch-2")

    assert [order.uid for order in batch.orders] == [replacement["uid"]]
    assert [item.uid for item in batch.failed] == [other_asset["uid"]]


# The execution rows ----------------------------------------------------------------------


def _created(markets, *orders) -> list[Order]:
    batch = _batch(markets, list(orders))
    markets.transactions.clear()
    return batch.orders


def test_orders_with_their_states_events_and_trades_are_one_transaction(markets) -> None:
    first, second = _created(markets, _order(markets), _order(markets, "MSFT"))

    written = write_execution(
        [
            OrderExecution(
                order=first,
                states=[{"order_time": WHEN, "status": "filled", "filled_quantity": 10.0}],
                events=[{"event_time": WHEN, "order_status": "filled"}],
                trades=[{"trade_time": WHEN, "trade_identifier": "fill-1", "quantity": 10.0, "price": 101.2}],
            ),
            {
                "order": second.model_dump(),
                "states": [{"order_time": WHEN, "status": "new"}],
            },
        ],
        trades=[
            {
                "trade_time": WHEN + dt.timedelta(minutes=1),
                "trade_identifier": "fill-2",
                "order_uid": str(second.uid),
                "account_identifier": markets.account_identifier,
                "asset_identifier": "MSFT",
                "quantity": 5.0,
            }
        ],
    )

    assert markets.transactions == [3]  # one statement per table
    assert written.failed == []
    assert [row["order_uid"] for row in written.order_states] == [first.uid, second.uid]
    assert written.trades[0] | {"account_identifier": markets.account_identifier} == written.trades[0]
    assert (written.trades[0]["order_uid"], written.trades[0]["asset_identifier"]) == (first.uid, "AAPL")
    assert _count(markets.engine, "ms_markets__ordersts") == 2
    assert _count(markets.engine, "ms_markets__ordereventsts") == 1
    assert _count(markets.engine, "ms_markets__tradests") == 2


def test_writing_a_state_again_updates_it(markets) -> None:
    (order,) = _created(markets, _order(markets))
    write_execution([{"order": order, "states": [{"order_time": WHEN, "status": "new"}]}])

    write_execution([{"order": order, "states": [{"order_time": WHEN, "status": "filled"}]}])

    assert _rows(markets.engine, "SELECT status FROM ms_markets__ordersts") == [{"status": "filled"}]


def test_a_trade_that_contradicts_its_order_is_refused_and_the_rest_written(markets) -> None:
    (order,) = _created(markets, _order(markets))

    written = write_execution(
        [
            {
                "order": order,
                "states": [{"order_time": WHEN, "status": "filled"}],
                "trades": [
                    {"trade_time": WHEN, "trade_identifier": "fill-1", "asset_identifier": "MSFT"},
                    {"trade_time": WHEN, "trade_identifier": "fill-2"},
                    {"trade_time": WHEN, "trade_identifier": "fill-2"},
                    {"trade_time": "2026-11-23T15:42:00", "trade_identifier": "fill-3"},
                    {"trade_time": WHEN, "trade_identifier": "fill-4", "fees": 1.0},
                ],
            }
        ]
    )

    assert [row["trade_identifier"] for row in written.trades] == ["fill-2"]
    assert [(item.table, item.key["trade_identifier"]) for item in written.failed] == [
        ("trades", "fill-1"),
        ("trades", "fill-2"),
        ("trades", "fill-3"),
        ("trades", "fill-4"),
    ]
    assert "is not its order's 'AAPL'" in written.failed[0].detail
    assert "repeats an earlier row" in written.failed[1].detail
    assert "has no timezone" in written.failed[2].detail
    assert "Unknown columns: fees" in written.failed[3].detail
    assert len(written.order_states) == 1


def test_an_order_the_database_refuses_stays_out_alone(markets) -> None:
    (order,) = _created(markets, _order(markets))
    missing = {"uid": uuid.uuid4(), "account_identifier": markets.account_identifier, "asset_identifier": "AAPL"}

    written = write_execution(
        [
            {"order": order, "states": [{"order_time": WHEN, "status": "new"}]},
            {"order": missing, "states": [{"order_time": WHEN, "status": "new"}],
             "trades": [{"trade_time": WHEN, "trade_identifier": "fill-x"}]},
        ]
    )

    # The transaction was refused, so each order was written on its own.
    assert markets.transactions == [2, 1, 2]
    assert [row["order_uid"] for row in written.order_states] == [order.uid]
    assert [(item.table, item.key) for item in written.failed] == [
        ("order_states", {"order_time": WHEN.isoformat(), "order_uid": str(missing["uid"])}),
        ("trades", {"trade_time": WHEN.isoformat(), "trade_identifier": "fill-x"}),
    ]
    assert _count(markets.engine, "ms_markets__ordersts") == 1
    assert _count(markets.engine, "ms_markets__tradests") == 0


def test_a_trade_without_an_order_is_written(markets) -> None:
    written = write_execution(
        trades=[
            {
                "trade_time": WHEN,
                "trade_identifier": "transfer-1",
                "account_identifier": markets.account_identifier,
                "asset_identifier": "AAPL",
                "quantity": 1.0,
            }
        ]
    )

    assert written.failed == []
    assert written.trades[0]["order_uid"] is None


def test_a_call_too_large_for_one_transaction_writes_nothing(markets, monkeypatch) -> None:
    (order,) = _created(markets, _order(markets))
    monkeypatch.setattr(
        "msm.repositories.execution.execution_rows_per_statement", lambda table: 1
    )
    states = [
        {"order_time": WHEN + dt.timedelta(seconds=second), "status": "new"}
        for second in range(MAX_TRANSACTION_STATEMENTS + 1)
    ]

    with pytest.raises(ValueError, match="at most 32. Nothing was written"):
        write_execution([{"order": order, "states": states}])

    assert markets.transactions == []
    assert _count(markets.engine, "ms_markets__ordersts") == 0
