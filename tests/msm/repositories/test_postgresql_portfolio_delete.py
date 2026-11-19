"""The portfolio delete on PostgreSQL, the hosted dialect (issue 93, ADR 0049).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. The statements run
through psycopg as the MetaTables API binds them, a statement list in one transaction with
its row guards (see ``test_postgresql_account_registration``).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from msm.models import PortfolioTable
from msm_portfolios.repositories import portfolio_deletion as repository
from msm_portfolios.repositories.portfolio_deletion import PORTFOLIO_DATASET_TABLES
from msm_portfolios.services import PortfolioDeleteConflictError, delete_portfolio_record
from tests.msm.repositories.test_postgresql_account_registration import (  # noqa: F401
    postgresql_markets,
)

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}
PROVIDER_TABLE = "provider_ns__portfoliosts__copy"
PROVIDER_CONSTRAINT = "fk_provider_ns_portfoliosts_copy_portfolio"


class _DatasetTable:
    """A bound dataset storage; records each statistics refresh with the requests before it."""

    def __init__(self, key: str, uid: str, refreshes: list, operations: list) -> None:
        self.key, self.uid, self.refreshes, self.operations = key, uid, refreshes, operations

    def delete_after_date(self, after_date, *, dimension_filters, timeout=None):
        self.refreshes.append(
            (self.key, list(dimension_filters["portfolio_identifier"]), after_date, list(self.operations))
        )
        return {"deleted_count": 0}


@pytest.fixture
def markets(postgresql_markets, monkeypatch):  # noqa: F811
    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: None))
    engine, context, operations = postgresql_markets
    refreshes: list = []
    for number, table in enumerate(PORTFOLIO_DATASET_TABLES, start=1):
        bound = _DatasetTable(table.key, f"0a0a0a0a-0000-4000-8000-00000000000{number}", refreshes, operations)
        monkeypatch.setattr(
            table.model, "get_time_index_meta_table", classmethod(lambda cls, bound=bound: bound)
        )
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    return engine, context, operations, refreshes


def _insert(engine, table_name: str, **values) -> dict:
    """Insert one row, filling required columns the test does not care about."""

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    row = dict(values)
    for column in table.columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        kind = column.type
        if isinstance(kind, sa.Uuid):
            row[column.name] = uuid.uuid4()
        elif isinstance(kind, sa.Boolean):
            row[column.name] = True
        elif isinstance(kind, sa.DateTime):
            row[column.name] = WHEN
        elif isinstance(kind, sa.Date):
            row[column.name] = WHEN.date()
        elif isinstance(kind, sa.Integer):
            row[column.name] = 1
        elif isinstance(kind, (sa.Float, sa.Numeric)):
            row[column.name] = 1.0
        elif isinstance(kind, sa.JSON):
            row[column.name] = {}
        else:
            length = getattr(kind, "length", None) or 255
            row[column.name] = f"{uuid.uuid4().hex[:8]}-{column.name}"[:length]
    with engine.begin() as connection:
        connection.execute(table.insert(), row)
    return row


def _portfolio(engine) -> tuple[uuid.UUID, str]:
    calendar = _insert(engine, "ms_markets__calendar")
    portfolio = uuid.uuid4()
    identifier = f"portfolio-{portfolio.hex[:8]}"
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=portfolio,
        unique_identifier=identifier,
        calendar_uid=calendar["uid"],
        retired_at=None,
    )
    return portfolio, identifier


def _datasets(engine, identifier: str) -> None:
    for table_name in DATASETS.values():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        _insert(engine, table_name, time_index=WHEN, portfolio_identifier=identifier, **assets)


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }


def _count(engine, sql: str, **parameters) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(sql), parameters).scalar_one()


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(_count(engine, "SELECT count(*) FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio))


def test_the_portfolio_and_its_seven_datasets_go_in_one_transaction(markets) -> None:
    engine, context, operations, refreshes = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)
    _insert(
        engine,
        "ms_markets__portfoliodatasetavailability",
        portfolio_uid=portfolio,
        # The core values table: no other application's table to check.
        values_meta_table_uid="0a0a0a0a-0000-4000-8000-000000000002",
        weights_meta_table_uid=None,
        signal_meta_table_uid=None,
        population_state="unavailable",
        row_count=None,
        earliest_time_index=None,
        latest_time_index=None,
    )
    group = _insert(engine, "ms_markets__portfoliogroup")
    _insert(engine, "ms_markets__portfoliogroupmembership", portfolio_group_uid=group["uid"], portfolio_uid=portfolio)
    operations.clear()

    deleted = delete_portfolio_record(context, uid=portfolio)

    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert deleted["statistics_not_refreshed"] == []
    assert operations == ["read", "transaction"]
    # Each dataset's statistics are rebuilt once, after the transaction, deleting nothing.
    assert refreshes == [
        (key, [identifier], "9999-12-31T00:00:00+00:00", ["read", "transaction"]) for key in DATASETS
    ]
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliodatasetavailability") == 0
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliogroupmembership") == 0
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_of_another_application_refuses_everything_and_is_named(markets) -> None:
    engine, context, operations, refreshes = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {PROVIDER_TABLE} (time_index timestamptz NOT NULL, "
            f"portfolio_identifier varchar(255) NOT NULL CONSTRAINT {PROVIDER_CONSTRAINT} "
            "REFERENCES ms_markets__portfolio (unique_identifier) ON DELETE RESTRICT)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {PROVIDER_TABLE} VALUES (%(time)s, %(identifier)s)",
            {"time": WHEN, "identifier": identifier},
        )
    operations.clear()

    with pytest.raises(PortfolioDeleteConflictError, match="nothing was deleted") as refused:
        delete_portfolio_record(context, uid=portfolio)

    # MetaTables' impact is unavailable here, so the database refuses the last statement.
    assert PROVIDER_CONSTRAINT in str(refused.value)
    assert operations == ["read", "transaction", "read"]
    assert refreshes == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_account_history_written_in_between_stops_the_guard(markets, monkeypatch) -> None:
    engine, context, _operations, refreshes = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    count = repository.count_portfolio_delete_rows
    calls: list[object] = []

    def counted(context, *, uids):
        result = count(context, uids=uids)
        if not calls:
            account = _insert(engine, "ms_markets__account", is_paper=True, account_is_active=True)
            _insert(engine, "ms_markets__virtualfund", account_uid=account["uid"], target_portfolio_uid=portfolio)
        calls.append(uids)
        return result

    monkeypatch.setattr(repository, "count_portfolio_delete_rows", counted)

    with pytest.raises(PortfolioDeleteConflictError, match=r"VirtualFundTable\.target_portfolio_uid"):
        delete_portfolio_record(context, uid=portfolio)

    assert refreshes == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
