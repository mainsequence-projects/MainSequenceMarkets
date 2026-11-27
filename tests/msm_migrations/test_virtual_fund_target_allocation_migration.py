"""Revision 0040: a virtual fund names its target allocation (ADR 0029, issue 157).

The upgrade adds ``account_target_allocation_uid`` to ``ms_markets__virtualfund`` in
place, fills it from each fund's key, and makes it unique with the portfolio. Set
``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` to a disposable ``markets_*`` database on
localhost to run the PostgreSQL cases; they are skipped otherwise.
"""

from __future__ import annotations

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
from msm.services.accounts.account_virtual_allocations import (
    virtual_fund_unique_identifier_for_target,
)
from msm_migrations.registry import metatable_provider_models
from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0040_virtual_fund_names_its_target_allocation"
)
URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"
FUND = REVISION.FUND
TABLES = MarketsBase.metadata.tables


@pytest.fixture(params=["sqlite", "postgresql"])
def at_0039(request, tmp_path, sqlite_revisions):
    """An engine on a database at revision 0039, on SQLite or on PostgreSQL."""

    if request.param == "sqlite":
        engine = sqlite_revisions.engine(tmp_path / "at-0039.sqlite", "0039")
    else:
        url = os.environ.get(URL_VARIABLE)
        if not url:
            pytest.skip(f"Set {URL_VARIABLE} to a disposable PostgreSQL database")
        parsed = make_url(url)
        if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith(
            "markets_"
        ):
            pytest.fail("These tests accept only a disposable markets_* database on localhost")
        parsed = worker_database(parsed)
        engine = sa.create_engine(parsed.set(drivername="postgresql+psycopg"), poolclass=NullPool)
        with engine.connect() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
            connection.commit()
            command.upgrade(_config(connection), "0039")
            connection.commit()
    yield engine
    engine.dispose()


def _funds_at_0039() -> sa.Table:
    return sa.table(
        FUND,
        sa.column("uid", sa.Uuid()),
        sa.column("unique_identifier", sa.String()),
        sa.column("account_uid", sa.Uuid()),
        sa.column("target_portfolio_uid", sa.Uuid()),
    )


def _seed(connection) -> dict[uuid.UUID, uuid.UUID]:
    """Two accounts; the first has two allocations, each with a fund of one portfolio.

    Answers each fund's allocation by fund uid.
    """

    calendar, model = uuid.uuid4(), uuid.uuid4()
    shared, second = uuid.uuid4(), uuid.uuid4()
    first_account, other_account = uuid.uuid4(), uuid.uuid4()
    stored, another, other_stored = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection.execute(
        TABLES["ms_markets__calendar"].insert(),
        [{"uid": calendar, "unique_identifier": "c", "display_name": "C", "calendar_type": "exchange",
          "timezone": "UTC"}],
    )
    connection.execute(
        TABLES["ms_markets__portfolio"].insert(),
        [
            {"uid": portfolio, "unique_identifier": f"p-{portfolio}", "calendar_uid": calendar,
             "backtest_table_price_column_name": "close"}
            for portfolio in (shared, second)
        ],
    )
    connection.execute(
        TABLES["ms_markets__account"].insert(),
        [
            {"uid": account, "unique_identifier": f"a-{account}", "account_name": "A",
             "is_paper": True, "account_is_active": True}
            for account in (first_account, other_account)
        ],
    )
    connection.execute(
        TABLES["ms_markets__accountallocationmodel"].insert(),
        [{"uid": model, "allocation_model_name": "Model"}],
    )
    connection.execute(
        TABLES["ms_markets__accounttargetallocation"].insert(),
        [
            {"uid": allocation, "unique_identifier": key, "account_uid": account,
             "account_allocation_model_uid": model, "is_active": True}
            for allocation, key, account in (
                (stored, str(first_account), first_account),
                (another, "another", first_account),
                (other_stored, str(other_account), other_account),
            )
        ],
    )
    funds = {
        uuid.uuid4(): (first_account, shared, stored),
        uuid.uuid4(): (first_account, second, stored),
        # The same portfolio under the account's other allocation is another fund.
        uuid.uuid4(): (first_account, shared, another),
        uuid.uuid4(): (other_account, shared, other_stored),
    }
    connection.execute(
        _funds_at_0039().insert(),
        [
            {
                "uid": fund,
                "unique_identifier": virtual_fund_unique_identifier_for_target(
                    account_uid=account,
                    target_portfolio_uid=portfolio,
                    account_target_allocation_uid=allocation,
                ),
                "account_uid": account,
                "target_portfolio_uid": portfolio,
            }
            for fund, (account, portfolio, allocation) in funds.items()
        ],
    )
    connection.commit()
    return {fund: allocation for fund, (_account, _portfolio, allocation) in funds.items()}


def _stored_allocations(connection) -> dict[uuid.UUID, uuid.UUID | None]:
    funds = sa.table(FUND, sa.column("uid", sa.Uuid()), sa.column(REVISION.COLUMN, sa.Uuid()))
    return {
        row.uid: getattr(row, REVISION.COLUMN)
        for row in connection.execute(sa.select(funds.c.uid, funds.c[REVISION.COLUMN]))
    }


def _table_of(difference) -> str | None:
    item = difference[0] if isinstance(difference, list) else difference
    for value in item[1:]:
        table = getattr(value, "table", None)
        name = getattr(table, "name", None) or getattr(value, "name", None)
        if name == FUND or value == FUND:
            return FUND
    return None


def test_the_revision_builds_a_funds_key_as_ms_markets_does() -> None:
    account, portfolio, allocation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert REVISION.fund_unique_identifier(account, portfolio, allocation) == (
        virtual_fund_unique_identifier_for_target(
            account_uid=account,
            target_portfolio_uid=portfolio,
            account_target_allocation_uid=allocation,
        )
    )


def test_0040_fills_each_funds_allocation_from_its_key(at_0039) -> None:
    with at_0039.connect() as connection:
        expected = _seed(connection)
        command.upgrade(_config(connection), "0040")
        connection.commit()

        assert _stored_allocations(connection) == expected


def test_0040_refuses_a_fund_that_matches_no_allocation_and_changes_nothing(at_0039) -> None:
    with at_0039.connect() as connection:
        _seed(connection)
        (account,) = connection.execute(
            sa.select(TABLES["ms_markets__account"].c.uid).limit(1)
        ).scalars()
        portfolio = connection.execute(
            sa.select(TABLES["ms_markets__portfolio"].c.uid).limit(1)
        ).scalar_one()
        stray = uuid.uuid4()
        connection.execute(
            _funds_at_0039().insert(),
            [{"uid": stray, "unique_identifier": "a key of the caller's own",
              "account_uid": account, "target_portfolio_uid": portfolio}],
        )
        connection.commit()

        with pytest.raises(RuntimeError) as refused:
            command.upgrade(_config(connection), "0040")
        connection.rollback()

        columns = {column["name"] for column in sa.inspect(connection).get_columns(FUND)}
        version = connection.exec_driver_sql(
            "SELECT version_num FROM ms_markets__alembic_version"
        ).scalar_one()
    assert str(refused.value).startswith("Revision 0040 refuses to run: 1 virtual funds")
    assert f"uid {stray}, account {account}, unique_identifier \"a key of the caller's own\"" in str(
        refused.value
    )
    assert REVISION.COLUMN not in columns
    assert version == "0039"


def test_0040_adds_the_column_in_place_on_sqlite(tmp_path, sqlite_revisions) -> None:
    """A rebuilt table would be created last, which changes the order of SQLite's key
    actions on an account delete (revision 0035)."""

    def entry(connection) -> tuple:
        return tuple(
            connection.exec_driver_sql(
                f"SELECT rowid, rootpage FROM sqlite_master WHERE name = '{FUND}'"
            ).one()
        )

    engine = sqlite_revisions.engine(tmp_path / "in-place.sqlite", "0039")
    with engine.connect() as connection:
        before = entry(connection)
        command.upgrade(_config(connection), "0040")
        connection.commit()

        assert entry(connection) == before
        (key,) = [
            key
            for key in connection.exec_driver_sql(f"PRAGMA foreign_key_list({FUND})").mappings()
            if key["from"] == REVISION.COLUMN
        ]
    assert (key["table"], key["to"], key["on_delete"]) == (REVISION.ALLOCATION, "uid", "CASCADE")


def test_0040_leaves_the_fund_table_as_the_model_declares_it(at_0039) -> None:
    metatable_provider_models()
    with at_0039.connect() as connection:
        command.upgrade(_config(connection), "0040")
        connection.commit()
        dialect = connection.dialect.name
        differences = [
            difference
            for difference in compare_metadata(
                MigrationContext.configure(connection, opts={"compare_type": True}),
                MarketsBase.metadata,
            )
            if _table_of(difference)
        ]

    if dialect == "sqlite":
        # SQLite adds the column in place only as a nullable column. SQLAlchemy reflects
        # a SQLite key's name and delete action only from a table-level constraint, and
        # SQLite adds a column's key inline; the key is there as declared
        # (test_0040_adds_the_column_in_place_on_sqlite).
        (nullable,) = [difference for difference in differences if isinstance(difference, list)]
        assert [(kind, column, existing, new) for kind, _s, _t, column, _kw, existing, new in nullable] == [
            ("modify_nullable", REVISION.COLUMN, True, False)
        ]
        assert [
            (kind, key.name, [column.name for column in key.columns], key.ondelete)
            for kind, key in (difference for difference in differences if not isinstance(difference, list))
        ] == [
            ("remove_fk", None, [REVISION.COLUMN], None),
            ("add_fk", REVISION.KEY, [REVISION.COLUMN], REVISION.ON_DELETE),
        ]
    else:
        assert differences == []


def test_the_key_deletes_a_fund_with_its_allocation_and_one_fund_per_portfolio(at_0039) -> None:
    with at_0039.connect() as connection:
        expected = _seed(connection)
        command.upgrade(_config(connection), "0040")
        connection.commit()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        fund, allocation = next(iter(expected.items()))
        row = connection.execute(
            sa.select(TABLES[FUND]).where(TABLES[FUND].c.uid == fund)
        ).mappings().one()

        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    TABLES[FUND].insert(),
                    [{**row, "uid": uuid.uuid4(), "unique_identifier": "a second fund"}],
                )
        allocations = TABLES["ms_markets__accounttargetallocation"]
        connection.execute(allocations.delete().where(allocations.c.uid == allocation))
        connection.commit()

        remaining = _stored_allocations(connection)
    assert remaining == {
        other: other_allocation
        for other, other_allocation in expected.items()
        if other_allocation != allocation
    }


def test_0040_downgrade_restores_the_fund_table_of_0039(tmp_path, sqlite_revisions) -> None:
    def schema(connection) -> tuple:
        inspector = sa.inspect(connection)
        return (
            [column["name"] for column in inspector.get_columns(FUND)],
            sorted(index["name"] for index in inspector.get_indexes(FUND)),
            sorted(key["name"] for key in inspector.get_foreign_keys(FUND)),
            connection.exec_driver_sql(
                f"SELECT sql FROM sqlite_master WHERE name = '{FUND}'"
            ).scalar_one(),
        )

    with sqlite_revisions.engine(tmp_path / "at-0039.sqlite", "0039").connect() as connection:
        at_0039 = schema(connection)
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0040")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0039")
        connection.commit()

        assert schema(connection) == at_0039
