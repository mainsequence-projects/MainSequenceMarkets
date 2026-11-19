"""The portfolio delete on PostgreSQL, the hosted dialect (issue 93, ADR 0049).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. The statements run
through psycopg as the MetaTables API binds them, a statement list in one transaction with
its row guards (see ``test_postgresql_account_registration``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from msm.models import PortfolioTable
from msm_portfolios.repositories import portfolio_deletion as repository
from msm_portfolios.services import PortfolioDeleteConflictError, delete_portfolio_record
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.msm.repositories.test_postgresql_account_registration import (  # noqa: F401
    postgresql_markets,
)

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}
PROVIDER_TABLE = "provider_ns__portfoliosts__copy"
PROVIDER_CONSTRAINT = "fk_provider_ns_portfoliosts_copy_portfolio"


@pytest.fixture
def markets(postgresql_markets, monkeypatch):  # noqa: F811
    from metatables import TimeIndexMetaTable

    def refuse_delete_after_date(self, *args, **kwargs):
        raise AssertionError("The portfolio delete must not call delete_after_date.")

    monkeypatch.setattr(TimeIndexMetaTable, "delete_after_date", refuse_delete_after_date)
    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: None))
    engine, context, operations = postgresql_markets
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    return engine, context, operations


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


def _rows_in(engine, identifier: str, **rows: int) -> None:
    """``rows[key]`` rows of the portfolio in dataset ``key``, one a day."""

    for key, count in rows.items():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(DATASETS[key])
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        for day in range(count):
            _insert(
                engine,
                DATASETS[key],
                time_index=WHEN + dt.timedelta(days=day),
                portfolio_identifier=identifier,
                **assets,
            )


def explain(engine, operation) -> list:
    """PostgreSQL's plan for a compiled read with sequential scans priced out (``FORMAT JSON``).

    The read is bound as MetaTables binds it. With ``enable_seqscan`` off the planner
    takes any usable index even on the tests' few rows, so the plan shows whether one
    exists for the read's conditions.
    """

    from metatables.api.backend.backends.restricted_sql import parameters_for

    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
    with engine.connect() as connection:
        connection.exec_driver_sql("SET enable_seqscan = off")
        return connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement.sql}", values).scalar_one()


def dataset_reads(plan: list) -> dict[str, list[str]]:
    """How the plan reads each dataset table: per plan node that reads it, the index it uses.

    ``None`` stands for a node that reads the table without an index.
    """

    reads: dict[str, list[str]] = {table_name: [] for table_name in DATASETS.values()}

    def visit(node: dict) -> None:
        if node.get("Relation Name") in reads:
            index = node.get("Index Name") or next(
                (
                    child.get("Index Name")
                    for child in node.get("Plans", ())
                    if child.get("Node Type") == "Bitmap Index Scan"
                ),
                None,
            )
            reads[node["Relation Name"]].append(index)
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan[0]["Plan"])
    return reads


def series_indexes() -> dict[str, list[str]]:
    """Per dataset table, its index that leads with ``portfolio_identifier``, once."""

    return {
        table.table_name: [index.name for index in table.model.__table__.indexes if not index.unique]
        for table in PORTFOLIO_DATASET_TABLES
    }


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


def test_the_portfolio_and_its_seven_datasets_go_in_one_transaction(markets, monkeypatch) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)
    _insert(
        engine,
        "ms_markets__portfoliodatasetavailability",
        portfolio_uid=portfolio,
        values_meta_table_uid="0a0a0a0a-0000-4000-8000-000000000001",
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

    from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage

    # The catalog names the core values table: no other application's table to check.
    core = SimpleNamespace(uid="0a0a0a0a-0000-4000-8000-000000000001")
    monkeypatch.setattr(PortfoliosStorage, "get_time_index_meta_table", classmethod(lambda cls: core))

    deleted = delete_portfolio_record(context, uid=portfolio)

    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert operations == ["read", "transaction"]
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliodatasetavailability") == 0
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliogroupmembership") == 0
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_of_another_application_refuses_everything_and_is_named(markets) -> None:
    engine, context, operations = markets
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
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_account_history_written_in_between_stops_the_guard(markets, monkeypatch) -> None:
    engine, context, _operations = markets
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

    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_one_read_counts_several_portfolios_in_each_dataset(markets) -> None:
    engine, context, operations = markets
    first, first_identifier = _portfolio(engine)
    _rows_in(engine, first_identifier, weights=2, rebalance_state=1)
    second, second_identifier = _portfolio(engine)
    _rows_in(engine, second_identifier, values=3, state=1, cash_flows=2)
    empty, _empty_identifier = _portfolio(engine)
    _other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)  # Not selected: none of its rows is counted.
    operations.clear()

    counted = repository.count_portfolio_delete_rows(context, uids=[first, second, empty, uuid.uuid4()])

    assert operations == ["read"]
    assert {uid: {key: row[key] for key in DATASETS} for uid, row in counted.items()} == {
        str(first): {key: {"weights": 2, "rebalance_state": 1}.get(key, 0) for key in DATASETS},
        str(second): {key: {"values": 3, "state": 1, "cash_flows": 2}.get(key, 0) for key in DATASETS},
        str(empty): {key: 0 for key in DATASETS},
    }


def test_each_count_reads_the_portfolios_rows_through_the_series_index(markets) -> None:
    engine, context, _operations = markets
    portfolios = []
    for _ in range(3):
        portfolio, identifier = _portfolio(engine)
        _datasets(engine, identifier)
        portfolios.append(portfolio)

    plan = explain(engine, repository.build_count_portfolio_delete_rows_operation(context, uids=portfolios))

    # Each dataset count reads the portfolio's rows through the series index (issue 96).
    assert dataset_reads(plan) == series_indexes()
