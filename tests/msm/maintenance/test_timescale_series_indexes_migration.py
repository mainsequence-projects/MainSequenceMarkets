"""Revision 0031 on TimescaleDB hypertables (issue 96).

Set ``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost, on a server that loads TimescaleDB, to run these tests; they are
skipped otherwise. The six dataset tables are made hypertables as MetaTables makes them on a
TimescaleDB DataSource, with one chunk per week of rows. Revision 0031 builds their series
index chunk by chunk, outside the upgrade's transaction, and an upgrade after an
interrupted build finishes it.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os

import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from tests.support.migrations import _config
from tests.support.postgresql_markets import _insert, _portfolio

URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"
WEEKS = 12
WHEN = dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.UTC)
MIGRATION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0031_portfolio_dataset_series_indexes"
)


@pytest.fixture
def hypertables():
    """The schema at revision 0030, the six dataset tables hypertables of `WEEKS` chunks."""

    url = os.environ.get(URL_VARIABLE)
    if not url:
        pytest.skip(f"Set {URL_VARIABLE} to a disposable TimescaleDB database")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith("markets_"):
        pytest.fail("These tests accept only a disposable markets_* database on localhost")
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
        command.upgrade(_config(connection), "0030")
        connection.commit()
        for table in MIGRATION.SERIES_INDEXES:
            connection.exec_driver_sql(
                f"SELECT create_hypertable('{table}'::regclass, 'time_index'::name, "
                "create_default_indexes => FALSE, if_not_exists => TRUE, migrate_data => TRUE)"
            )
        connection.commit()
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    _portfolio_id, identifier = _portfolio(engine)
    for table in MIGRATION.SERIES_INDEXES:
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        for week in range(WEEKS):
            _insert(
                engine,
                table,
                time_index=WHEN + dt.timedelta(weeks=week),
                portfolio_identifier=identifier,
                **assets,
            )
    yield engine
    engine.dispose()


def _dsn(engine) -> str:
    return engine.url.set(drivername="postgresql").render_as_string(hide_password=False)


def _state(engine) -> dict[str, tuple[bool | None, int, int]]:
    """Per table: whether its series index is valid (None: absent), chunks, chunk indexes."""

    with engine.connect() as connection:
        return {
            table: (
                connection.execute(
                    sa.text(
                        "SELECT index_state.indisvalid FROM pg_index AS index_state "
                        "JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid "
                        "WHERE index_class.relname = :index"
                    ),
                    {"index": index},
                ).scalar(),
                connection.execute(
                    sa.text("SELECT count(*) FROM show_chunks(CAST(:table AS regclass))"), {"table": table}
                ).scalar_one(),
                len(
                    connection.execute(
                        MIGRATION._CHUNK_INDEXES, {"table": table, "columns": MIGRATION.SERIES_COLUMNS}
                    ).all()
                ),
            )
            for table, index in MIGRATION.SERIES_INDEXES.items()
        }


def _migrate(engine, revision: str) -> None:
    with engine.connect() as connection:
        config = _config(connection)
        if revision == "0031":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)
        connection.commit()


def test_0031_indexes_every_chunk_and_the_downgrade_removes_them(hypertables) -> None:
    _migrate(hypertables, "0031")

    assert _state(hypertables) == {table: (True, WEEKS, WEEKS) for table in MIGRATION.SERIES_INDEXES}

    _migrate(hypertables, "0030")

    assert _state(hypertables) == {table: (None, WEEKS, 0) for table in MIGRATION.SERIES_INDEXES}


def test_an_upgrade_after_an_interrupted_build_finishes_it(hypertables) -> None:
    table, index = next(iter(MIGRATION.SERIES_INDEXES.items()))
    dsn = _dsn(hypertables)
    # Another session holds the fifth chunk, so a chunk-by-chunk build stops there: the
    # four chunks before it keep their index and the hypertable's index stays invalid.
    with psycopg.connect(dsn) as holder:
        (chunk,) = holder.execute(
            f"SELECT chunk FROM show_chunks('{table}'::regclass) AS chunk ORDER BY chunk LIMIT 1 OFFSET 4"
        ).fetchone()
        holder.execute(f"LOCK TABLE {chunk} IN ACCESS EXCLUSIVE MODE")
        with psycopg.connect(dsn, autocommit=True) as builder:
            builder.execute("SET lock_timeout = '1s'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                builder.execute(
                    f'CREATE INDEX "{index}" ON "{table}" (portfolio_identifier, time_index) '
                    "WITH (timescaledb.transaction_per_chunk)"
                )
        holder.rollback()
    assert _state(hypertables)[table] == (False, WEEKS, 4)

    _migrate(hypertables, "0031")

    assert _state(hypertables) == {table: (True, WEEKS, WEEKS) for table in MIGRATION.SERIES_INDEXES}
