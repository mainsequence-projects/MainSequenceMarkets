"""Revision 0034 on TimescaleDB hypertables.

Set ``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost, on a server that loads TimescaleDB, to run this test; it is skipped
otherwise. The six account history tables are made hypertables, as MetaTables makes them on
a TimescaleDB DataSource; holdings, orders and order events get one chunk per week of rows.
Revision 0034 builds each index chunk by chunk, outside the upgrade's transaction, as
revision 0031 does (see its test for an interrupted build).
"""

from __future__ import annotations

import datetime as dt
import importlib
import os

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database
from tests.support.postgresql_portfolios import _insert

URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"
WEEKS = 12
WHEN = dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.UTC)
MIGRATION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0034_account_history_indexes"
)
TIME_COLUMNS = {
    "ms_markets__accountholdingsts": "time_index",
    "ms_markets__accountallocationlinests": "time_index",
    "ms_markets__virtualfundholdingsts": "time_index",
    "ms_markets__ordersts": "order_time",
    "ms_markets__tradests": "trade_time",
    "ms_markets__ordereventsts": "event_time",
}


@pytest.fixture
def hypertables():
    """The schema at revision 0033, the six history tables hypertables."""

    url = os.environ.get(URL_VARIABLE)
    if not url:
        pytest.skip(f"Set {URL_VARIABLE} to a disposable TimescaleDB database")
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
        command.upgrade(_config(connection), "0033")
        connection.commit()
        for table, time_column in TIME_COLUMNS.items():
            connection.exec_driver_sql(
                f"SELECT create_hypertable('{table}'::regclass, '{time_column}'::name, "
                "create_default_indexes => FALSE, if_not_exists => TRUE, migrate_data => TRUE)"
            )
        connection.commit()
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    account = _insert(engine, "ms_markets__account", unique_identifier="account-1")
    _insert(
        engine,
        "ms_markets__ordermanager",
        unique_identifier="manager-1",
        target_account_uid=account["uid"],
    )
    for week in range(WEEKS):
        when = WHEN + dt.timedelta(weeks=week)
        holdings_set = _insert(
            engine, "ms_markets__accountholdingsset", account_uid=account["uid"], time_index=when
        )
        _insert(
            engine,
            "ms_markets__accountholdingsts",
            time_index=when,
            account_uid=account["uid"],
            asset_identifier="AAA",
            holdings_set_uid=holdings_set["uid"],
            direction=1,
        )
        _insert(
            engine,
            "ms_markets__ordersts",
            order_time=when,
            order_identifier=f"order-{week}",
            account_identifier="account-1",
            order_manager_identifier="manager-1",
            asset_identifier="AAA",
        )
        _insert(
            engine, "ms_markets__ordereventsts", event_time=when, order_identifier=f"order-{week}"
        )
    yield engine
    engine.dispose()


def _state(engine) -> dict[str, tuple[bool | None, int, int]]:
    """Per index: whether it is valid (None: absent), its table's chunks, its chunk indexes."""

    with engine.connect() as connection:
        return {
            index: (
                connection.execute(
                    sa.text(
                        "SELECT index_state.indisvalid FROM pg_index AS index_state "
                        "JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid "
                        "WHERE index_class.relname = :index"
                    ),
                    {"index": index},
                ).scalar(),
                connection.execute(
                    sa.text("SELECT count(*) FROM show_chunks(CAST(:table AS regclass))"),
                    {"table": table},
                ).scalar_one(),
                len(
                    connection.execute(
                        MIGRATION._CHUNK_INDEXES, {"table": table, "columns": list(columns)}
                    ).all()
                ),
            )
            for table, index, columns in MIGRATION.INDEXES
        }


def _migrate(engine, revision: str) -> None:
    with engine.connect() as connection:
        config = _config(connection)
        if revision == "0034":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)
        connection.commit()


def test_0034_indexes_every_chunk_and_the_downgrade_removes_them(hypertables) -> None:
    chunks = {
        table: WEEKS
        for table in (
            "ms_markets__accountholdingsts",
            "ms_markets__ordersts",
            "ms_markets__ordereventsts",
        )
    }

    _migrate(hypertables, "0034")

    assert _state(hypertables) == {
        index: (True, chunks.get(table, 0), chunks.get(table, 0))
        for table, index, _columns in MIGRATION.INDEXES
    }

    _migrate(hypertables, "0033")

    assert _state(hypertables) == {
        index: (None, chunks.get(table, 0), 0) for table, index, _columns in MIGRATION.INDEXES
    }
