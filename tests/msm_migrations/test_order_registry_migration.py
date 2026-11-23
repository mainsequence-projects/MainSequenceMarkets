"""Revision 0037 gives each order its own row (ADR 0064).

The TimescaleDB test runs only when ``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` names an
empty, disposable ``markets_*`` database on localhost, on a server that loads TimescaleDB.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from msm.base import MarketsBase
from msm.models import OrderTable
from msm.time_index.execution import upgrade
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage
from msm_migrations import migration
from msm_migrations.registry import metatable_provider_models
from tests.support import postgresql_portfolios
from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database
from tests.support.sqlite_markets import _account, _asset, _insert

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0037_an_order_has_its_own_row"
)
WHEN = dt.datetime(2026, 11, 23, 15, 42, tzinfo=dt.UTC)
TIMESCALE_URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"
EXECUTION_TABLES = {
    model.__table__.name for model in (OrderTable, OrdersStorage, OrderEventsStorage, TradesStorage)
}


def _identifier(engine, table: str) -> str:
    with engine.connect() as connection:
        return connection.exec_driver_sql(f"SELECT unique_identifier FROM {table} LIMIT 1").scalar_one()


def _seed(engine, orders: dict[str, str]) -> dict[str, str]:
    """State rows of each order identifier (two, the second filled), a trade and an event;
    ``orders`` maps each identifier to its asset."""

    account = _account(engine)
    for asset in set(orders.values()):
        _asset(engine, asset)
    _insert(engine, "ms_markets__ordermanager", unique_identifier="batch-1", target_account_uid=account.hex)
    identifier = _identifier(engine, "ms_markets__account")
    for position, (order, asset) in enumerate(orders.items()):
        for minute, status in enumerate(("new", "filled")):
            _insert(
                engine,
                REVISION.ORDERS,
                order_time=WHEN + dt.timedelta(minutes=minute),
                order_identifier=order,
                account_identifier=identifier,
                asset_identifier=asset,
                order_manager_identifier="batch-1",
                order_type="limit",
                limit_price=100.0 + minute,  # the earliest row's terms are the order's
                client_order_id="",
                status=status,
            )
        _insert(
            engine,
            REVISION.TRADES,
            trade_time=WHEN,
            trade_identifier=f"fill-{position}",
            account_identifier=identifier,
            asset_identifier=asset,
            order_identifier=order,
            quantity=10.0,
        )
        _insert(engine, REVISION.EVENTS, event_time=WHEN, order_identifier=order, order_status="filled")
    return {"account_identifier": identifier}


def _rows(connection, sql: str) -> list[dict]:
    return [dict(row) for row in connection.exec_driver_sql(sql).mappings()]


def test_0037_gives_each_order_one_row_and_keys_its_rows_to_it(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "orders.sqlite", "0036")
    order_uid = uuid.uuid4()
    seeded = _seed(engine, {"broker-123": "AAPL", str(order_uid): "MSFT"})
    _insert(
        engine,
        REVISION.TRADES,
        trade_time=WHEN,
        trade_identifier="transfer",
        account_identifier=seeded["account_identifier"],
        asset_identifier="AAPL",
        order_identifier="",
    )
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0037")

        orders = _rows(connection, f"SELECT * FROM {REVISION.ORDER} ORDER BY asset_identifier")
        states = _rows(connection, f"SELECT order_uid, status FROM {REVISION.ORDERS} ORDER BY order_time")
        trades = _rows(connection, f"SELECT trade_identifier, order_uid FROM {REVISION.TRADES} ORDER BY trade_identifier")
        events = _rows(connection, f"SELECT order_uid FROM {REVISION.EVENTS}")

    legacy = REVISION.order_uid("broker-123")
    assert legacy == uuid.uuid5(REVISION.ORDER_UID_NAMESPACE, "broker-123")
    assert [uuid.UUID(order["uid"]) for order in orders] == [legacy, order_uid]
    assert orders[0] | {
        "account_identifier": seeded["account_identifier"],
        "order_manager_identifier": "batch-1",
        "order_type": "limit",
        "limit_price": 100.0,
        "client_order_id": None,
    } == orders[0]
    assert {uuid.UUID(row["order_uid"]) for row in states} == {legacy, order_uid}
    assert [row["status"] for row in states] == ["new", "new", "filled", "filled"]
    assert [(row["trade_identifier"], row["order_uid"] and uuid.UUID(row["order_uid"])) for row in trades] == [
        ("fill-0", legacy),
        ("fill-1", order_uid),
        ("transfer", None),
    ]
    assert {uuid.UUID(row["order_uid"]) for row in events} == {legacy, order_uid}


def test_applications_map_their_orders_as_0037_maps_markets_own() -> None:
    """An application's instances reference Markets' Order rows, so its identifiers must
    become the same uids, and its orders take the same terms."""

    assert upgrade.ORDER_UID_NAMESPACE == REVISION.ORDER_UID_NAMESPACE
    assert upgrade.ORDER_TERMS == REVISION.ORDER_TERMS
    for identifier in ("broker-123", str(uuid.uuid4()), "B3C37335-98DE-5460-92FA-55D1C01048DE"):
        assert upgrade.order_uid_for_identifier(identifier) == REVISION.order_uid(identifier)


def test_0037_leaves_the_tables_as_the_models_declare_them(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "head.sqlite", "0037")
    metatable_provider_models()
    with engine.connect() as connection:
        differences = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), MarketsBase.metadata
        )

    assert [
        difference
        for difference in differences
        if _table_of(difference) in EXECUTION_TABLES
    ] == []


def _table_of(difference) -> str | None:
    item = difference[0] if isinstance(difference, list) else difference
    for value in item[1:]:
        table = getattr(value, "table", None)
        name = getattr(table, "name", None) or getattr(value, "name", None)
        if isinstance(name, str) and name in EXECUTION_TABLES:
            return name
        if isinstance(value, str) and value in EXECUTION_TABLES:
            return value
    return None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("shared", "state rows of more than one account or asset"),
        ("orphan_trade", "name an order with no state row"),
        ("repeated_trade", "more than one trade at the same time"),
    ],
)
def test_0037_refuses_rows_that_cannot_be_keyed_and_changes_nothing(
    tmp_path, sqlite_revisions, change, message
) -> None:
    engine = sqlite_revisions.engine(tmp_path / f"{change}.sqlite", "0036")
    seeded = _seed(engine, {"order-1": "AAPL"})
    row = {
        "account_identifier": seeded["account_identifier"],
        "asset_identifier": "AAPL",
    }
    if change == "shared":
        _asset(engine, "MSFT")
        _insert(engine, REVISION.ORDERS, order_time=WHEN, order_identifier="order-1", **{**row, "asset_identifier": "MSFT"})
    elif change == "orphan_trade":
        _insert(engine, REVISION.TRADES, trade_time=WHEN, trade_identifier="fill-x", order_identifier="gone", **row)
    else:
        _insert(engine, REVISION.TRADES, trade_time=WHEN, trade_identifier="fill-0", order_identifier="order-1",
                **{**row, "account_identifier": _identifier_of_new_account(engine)})

    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match=message):
            command.upgrade(_config(connection), "0037")
        connection.rollback()
        version = connection.exec_driver_sql(f"SELECT version_num FROM {migration.version_table}").scalar_one()
        tables = set(sa.inspect(connection).get_table_names())

    assert version == "0036"
    assert REVISION.ORDER not in tables


def _identifier_of_new_account(engine) -> str:
    account = _account(engine)
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT unique_identifier FROM ms_markets__account WHERE uid = ?", (account.hex,)
        ).scalar_one()


def test_0037_downgrade_puts_the_identifiers_back_as_the_uids_text(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0036")
    _seed(engine, {"broker-123": "AAPL"})
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0037")
        command.downgrade(_config(connection), "0036")

        states = _rows(connection, f"SELECT order_identifier, asset_identifier, order_type FROM {REVISION.ORDERS}")
        trades = _rows(connection, f"SELECT order_identifier FROM {REVISION.TRADES}")
        tables = set(sa.inspect(connection).get_table_names())

    uid = str(REVISION.order_uid("broker-123"))
    assert states == [{"order_identifier": uid, "asset_identifier": "AAPL", "order_type": "limit"}] * 2
    assert trades == [{"order_identifier": uid}]
    assert REVISION.ORDER not in tables


@pytest.fixture
def timescale_execution():
    """The schema at revision 0036 on TimescaleDB, the three execution tables hypertables."""

    url = os.environ.get(TIMESCALE_URL_VARIABLE)
    if not url:
        pytest.skip(f"Set {TIMESCALE_URL_VARIABLE} to a disposable TimescaleDB database")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith(
        "markets_"
    ):
        pytest.fail("These tests accept only a disposable markets_* database on localhost")
    parsed = worker_database(parsed)
    # Each connect is a new session: TimescaleDB creates its extension only as a session's
    # first use of it.
    engine = sa.create_engine(parsed.set(drivername="postgresql+psycopg"), poolclass=NullPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("DROP EXTENSION IF EXISTS timescaledb CASCADE")
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
        connection.commit()
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE EXTENSION timescaledb")
        connection.commit()
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0036")
        connection.commit()
        for table, time_column in (
            (REVISION.ORDERS, "order_time"),
            (REVISION.EVENTS, "event_time"),
            (REVISION.TRADES, "trade_time"),
        ):
            connection.exec_driver_sql(
                f"SELECT create_hypertable('{table}'::regclass, '{time_column}'::name, "
                "create_default_indexes => FALSE, if_not_exists => TRUE, migrate_data => TRUE)"
            )
        connection.commit()
    yield engine
    engine.dispose()


def test_0037_on_timescaledb_keys_every_chunk_to_its_order(timescale_execution) -> None:
    engine = timescale_execution
    insert = postgresql_portfolios._insert
    account = insert(engine, "ms_markets__account", unique_identifier="account-1")
    insert(engine, "ms_markets__asset", unique_identifier="AAPL")
    insert(engine, "ms_markets__ordermanager", unique_identifier="batch-1", target_account_uid=account["uid"])
    # One order a week, so each hypertable has a chunk per order.
    for week in range(3):
        when = WHEN + dt.timedelta(weeks=week)
        order = f"broker-{week}"
        insert(engine, REVISION.ORDERS, order_time=when, order_identifier=order,
               account_identifier="account-1", asset_identifier="AAPL", order_manager_identifier="batch-1")
        insert(engine, REVISION.EVENTS, event_time=when, order_identifier=order)
        insert(engine, REVISION.TRADES, trade_time=when, trade_identifier=f"fill-{week}",
               account_identifier="account-1", asset_identifier="AAPL", order_identifier=order)

    with engine.connect() as connection:
        command.upgrade(_config(connection), "0037")
        connection.commit()
        chunks = {
            table: connection.exec_driver_sql(
                f"SELECT count(*) FROM show_chunks('{table}'::regclass)"
            ).scalar_one()
            for table in (REVISION.ORDERS, REVISION.EVENTS, REVISION.TRADES)
        }
        keyed = {
            table: connection.exec_driver_sql(
                f"SELECT count(*) FROM {table} AS t JOIN {REVISION.ORDER} AS o ON o.uid = t.order_uid"
            ).scalar_one()
            for table in (REVISION.ORDERS, REVISION.EVENTS, REVISION.TRADES)
        }
        orders = connection.exec_driver_sql(f"SELECT count(*) FROM {REVISION.ORDER}").scalar_one()
        # TimescaleDB names the key on each chunk after the hypertable's.
        with pytest.raises(sa.exc.IntegrityError, match='is not present in table "ms_markets__order"'):
            connection.exec_driver_sql(
                f"INSERT INTO {REVISION.TRADES} (trade_time, trade_identifier, account_identifier, "
                "asset_identifier, order_uid) SELECT trade_time, 'other', 'account-1', 'AAPL', "
                f"gen_random_uuid() FROM {REVISION.TRADES} LIMIT 1"
            )
        connection.rollback()

    assert orders == 3
    assert chunks == dict.fromkeys(chunks, 3)
    assert keyed == dict.fromkeys(keyed, 3)
