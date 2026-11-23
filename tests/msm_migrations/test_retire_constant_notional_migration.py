"""Revision 0036 retires ``constant_notional_exposure`` from the account target (ADR 0061).

The TimescaleDB test runs only when ``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` names an
empty, disposable ``markets_*`` database on localhost, on a server that loads TimescaleDB.
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

from msm_migrations import migration
from tests.support import postgresql_portfolios
from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database
from tests.support.sqlite_markets import _account, _asset, _insert, _portfolio

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0036_retire_constant_notional_exposure"
)
WHEN = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)
TIMESCALE_URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"


def _targets(connection) -> sa.Table:
    metadata = sa.MetaData()
    metadata.reflect(connection, only=[REVISION.TABLE])
    return metadata.tables[REVISION.TABLE]


def _seed_target(engine, **portfolio_exposure) -> dict:
    """One account target: an asset row in units and a portfolio row stating the exposure."""

    account = _account(engine)
    model = _insert(engine, "ms_markets__accountallocationmodel")
    target_allocation = _insert(
        engine,
        "ms_markets__accounttargetallocation",
        account_uid=account.hex,
        account_allocation_model_uid=model["uid"],
    )
    position_set = _insert(
        engine,
        "ms_markets__positionset",
        account_target_allocation_uid=target_allocation["uid"],
    )
    asset = _asset(engine, "AAPL").hex
    rows = {
        "asset": {
            "target_type": "asset",
            "target_uid": asset,
            "asset_uid": asset,
            "portfolio_uid": None,
            "single_asset_quantity": 10.0,
        },
        "portfolio": _portfolio_row(_portfolio(engine).hex, **portfolio_exposure),
    }
    for row in rows.values():
        _insert(
            engine,
            REVISION.TABLE,
            time_index=WHEN,
            position_set_uid=position_set["uid"],
            **row,
        )
    return {"position_set_uid": position_set["uid"], **rows["portfolio"]}


def _portfolio_row(portfolio_uid: str, **exposure) -> dict:
    return {
        "target_type": "portfolio",
        "target_uid": portfolio_uid,
        "asset_uid": None,
        "portfolio_uid": portfolio_uid,
        **exposure,
    }


def _refused(connection, portfolio_row: dict, **exposure) -> None:
    """A second portfolio row, one day later, is refused by the exposure check."""

    row = {
        "time_index": WHEN + dt.timedelta(days=1),
        "position_set_uid": portfolio_row["position_set_uid"],
        **_portfolio_row(portfolio_row["portfolio_uid"], **exposure),
    }
    with pytest.raises(sa.exc.IntegrityError, match=REVISION.SINGLE_EXPOSURE_CHECK):
        connection.execute(_targets(connection).insert(), row)
    connection.rollback()


def test_0036_refuses_a_target_that_still_states_an_amount(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "amount.sqlite", "0035")
    _seed_target(engine, constant_notional_exposure=300_000.0)
    with engine.connect() as connection:
        with pytest.raises(sa.exc.IntegrityError, match=REVISION.SINGLE_EXPOSURE_CHECK):
            command.upgrade(_config(connection), "0036")
        connection.rollback()

        version = connection.exec_driver_sql(
            f"SELECT version_num FROM {migration.version_table}"
        ).scalar_one()
        amounts = connection.exec_driver_sql(
            f"SELECT constant_notional_exposure FROM {REVISION.TABLE} "
            "WHERE target_type = 'portfolio'"
        ).scalars().all()

    assert version == "0035"
    assert amounts == [300_000.0]


def test_0036_keeps_shares_and_units_and_takes_exactly_one_of_them(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "share.sqlite", "0035")
    portfolio_row = _seed_target(engine, weight_notional_exposure=0.3)
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0036")
        connection.commit()

        targets = _targets(connection)
        kept = connection.execute(
            sa.select(
                targets.c.target_type,
                targets.c.weight_notional_exposure,
                targets.c.single_asset_quantity,
            ).order_by(targets.c.target_type)
        ).all()
        assert "constant_notional_exposure" not in targets.c
        _refused(connection, portfolio_row)
        _refused(connection, portfolio_row, weight_notional_exposure=0.3, single_asset_quantity=1.0)

    assert [tuple(row) for row in kept] == [("asset", None, 10.0), ("portfolio", 0.3, None)]


def test_0036_downgrade_restores_the_amount_and_the_three_field_check(
    tmp_path, sqlite_revisions
) -> None:
    def schema(connection) -> tuple[dict, dict]:
        inspector = sa.inspect(connection)
        columns = {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspector.get_columns(REVISION.TABLE)
        }
        checks = {
            check["name"]: check["sqltext"]
            for check in inspector.get_check_constraints(REVISION.TABLE)
        }
        return columns, checks

    with sqlite_revisions.engine(tmp_path / "at-0035.sqlite", "0035").connect() as connection:
        at_0035 = schema(connection)
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0036")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0035")
        connection.commit()

        assert schema(connection) == at_0035


@pytest.fixture
def timescale_targets():
    """The schema at revision 0035 on TimescaleDB, the target positions a hypertable."""

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
        command.upgrade(_config(connection), "0035")
        connection.commit()
        connection.exec_driver_sql(
            f"SELECT create_hypertable('{REVISION.TABLE}'::regclass, 'time_index'::name, "
            "create_default_indexes => FALSE, if_not_exists => TRUE, migrate_data => TRUE)"
        )
        connection.commit()
    yield engine
    engine.dispose()


def test_0036_on_timescaledb_rolls_back_when_a_target_states_an_amount(timescale_targets) -> None:
    engine = timescale_targets
    insert = postgresql_portfolios._insert
    account = insert(engine, "ms_markets__account", unique_identifier="account-1")
    model = insert(engine, "ms_markets__accountallocationmodel")
    target_allocation = insert(
        engine,
        "ms_markets__accounttargetallocation",
        account_uid=account["uid"],
        account_allocation_model_uid=model["uid"],
    )
    position_set = insert(
        engine,
        "ms_markets__positionset",
        account_target_allocation_uid=target_allocation["uid"],
    )
    calendar = insert(engine, "ms_markets__calendar")
    portfolio = insert(engine, "ms_markets__portfolio", calendar_uid=calendar["uid"])
    # One row a week, so the hypertable has a chunk per row; the last states an amount.
    for week, exposure in enumerate(
        ({"weight_notional_exposure": 0.3},) * 2 + ({"constant_notional_exposure": 300_000.0},)
    ):
        insert(
            engine,
            REVISION.TABLE,
            time_index=WHEN + dt.timedelta(weeks=week),
            position_set_uid=position_set["uid"],
            **_portfolio_row(portfolio["uid"], **exposure),
        )

    def state(connection) -> tuple[str, set[str], int]:
        return (
            connection.exec_driver_sql(
                f"SELECT version_num FROM {migration.version_table}"
            ).scalar_one(),
            {column["name"] for column in sa.inspect(connection).get_columns(REVISION.TABLE)},
            connection.exec_driver_sql(
                f"SELECT count(*) FROM show_chunks('{REVISION.TABLE}'::regclass)"
            ).scalar_one(),
        )

    with engine.connect() as connection:
        with pytest.raises(sa.exc.IntegrityError, match=REVISION.SINGLE_EXPOSURE_CHECK):
            command.upgrade(_config(connection), "0036")
        connection.rollback()
    with engine.connect() as connection:
        version, columns, chunks = state(connection)
        amounts = connection.exec_driver_sql(
            f"SELECT count(*) FROM {REVISION.TABLE} WHERE constant_notional_exposure IS NOT NULL"
        ).scalar_one()

    assert (version, "constant_notional_exposure" in columns, chunks, amounts) == (
        "0035",
        True,
        3,
        1,
    )

    # Once the account states a share instead, the upgrade drops the column on every chunk.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"UPDATE {REVISION.TABLE} SET weight_notional_exposure = 0.3, "
            "constant_notional_exposure = NULL WHERE constant_notional_exposure IS NOT NULL"
        )
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0036")
        connection.commit()
        version, columns, chunks = state(connection)
        with pytest.raises(sa.exc.IntegrityError, match=REVISION.SINGLE_EXPOSURE_CHECK):
            connection.execute(
                _targets(connection).insert(),
                {
                    "time_index": WHEN + dt.timedelta(weeks=1, days=1),
                    "position_set_uid": position_set["uid"],
                    **_portfolio_row(portfolio["uid"]),
                },
            )
        connection.rollback()

    assert (version, "constant_notional_exposure" in columns, chunks) == ("0036", False, 3)
