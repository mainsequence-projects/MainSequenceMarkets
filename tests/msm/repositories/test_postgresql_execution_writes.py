"""A batch's orders and their execution rows, written on PostgreSQL (ADR 0064, #131).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost. This checks only what SQLite cannot show: the ``ON CONFLICT``
statements compiled for PostgreSQL, run as the MetaTables API binds them, and the
database's own refusal of a trade whose account or asset is not its order's.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import sqlalchemy as sa

from msm.api import OrderManager
from msm.time_index.execution import write_execution
from tests.support.postgresql_markets import _insert as insert
from tests.support.markets_runtime import serve_runtime

WHEN = dt.datetime(2026, 11, 23, 15, 42, tzinfo=dt.UTC)


def test_a_batch_and_its_execution_rows_on_postgresql(postgresql_markets, monkeypatch) -> None:
    engine, context, operations = postgresql_markets
    serve_runtime(monkeypatch, lambda **_kwargs: SimpleNamespace(context=context))
    account = insert(engine, "ms_markets__account", unique_identifier="account-1")
    insert(engine, "ms_markets__asset", unique_identifier="AAPL")
    insert(engine, "ms_markets__asset", unique_identifier="MSFT")
    order = {
        "uid": uuid.uuid4(),
        "account_identifier": "account-1",
        "asset_identifier": "AAPL",
        "order_side": 1,
        "quantity": 10.0,
    }

    batch = OrderManager.create_batch(
        unique_identifier="batch-1", target_account_uid=account["uid"], target_time=WHEN, orders=[order]
    )
    again = OrderManager.create_batch(
        unique_identifier="batch-1",
        target_account_uid=account["uid"],
        target_time=WHEN,
        status="filled",
        orders=[{**order, "quantity": 99.0}],
    )
    (created,) = batch.orders
    operations.clear()
    state = {"order_time": WHEN, "status": "new"}
    first = write_execution(
        [{"order": created, "states": [state], "events": [{"event_time": WHEN}],
          "trades": [{"trade_time": WHEN, "trade_identifier": "fill-1", "quantity": 10.0}]}]
    )
    second = write_execution([{"order": created, "states": [{**state, "status": "filled"}]}])
    refused = write_execution(
        trades=[
            {"trade_time": WHEN, "trade_identifier": "fill-2", "order_uid": created.uid,
             "account_identifier": "account-1", "asset_identifier": "MSFT"}
        ]
    )

    assert (batch.failed, again.failed, first.failed, second.failed) == ([], [], [], [])
    assert again.order_manager.uid == batch.order_manager.uid
    assert again.order_manager.status == "filled"
    assert operations[:2] == ["transaction", "transaction"]
    assert "is not present in table" in refused.failed[0].detail
    with engine.connect() as connection:
        quantity = connection.execute(sa.text("SELECT quantity FROM ms_markets__order")).scalar_one()
        status = connection.execute(sa.text("SELECT status FROM ms_markets__ordersts")).scalar_one()
        trades = connection.execute(sa.text("SELECT count(*) FROM ms_markets__tradests")).scalar_one()
    assert (quantity, status, trades) == (10.0, "filled", 1)
