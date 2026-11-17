"""A bulk upsert of any length on PostgreSQL, end to end (MainSequenceMarkets#84).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost. The statements run through psycopg as the MetaTables API binds
them, with ``prepare=True``, so a statement that binds more values than PostgreSQL
takes is refused here as it is there. Each statement's SQL text and bound values are
recorded and checked against the limits ``bulk_upsert_model`` keeps.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from metatables import MetaTable

from msm.api.assets import Asset
from msm.api.calendars import Calendar, CalendarException
from msm.models import AssetTable
from msm.repositories import crud
from msm.repositories.crud import (
    MAX_STATEMENT_PARAMETERS,
    MAX_STATEMENT_SQL_CHARACTERS,
    UPSERT_STATUS_COLUMN,
    bulk_upsert_model,
)
from tests.msm.repositories.test_postgresql_account_registration import (  # noqa: F401
    postgresql_markets,
)

KEY = ("unique_identifier",)


@pytest.fixture
def markets(postgresql_markets, monkeypatch):  # noqa: F811
    engine, context, operations = postgresql_markets
    run = MetaTable.execute_operation
    statements = []

    def execute_operation(operation, *, timeout=None):
        statements.append(operation.statement)
        return run(operation, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", execute_operation)
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=context),
    )
    return SimpleNamespace(engine=engine, context=context, statements=statements)


def _assets(count: int) -> list[dict]:
    return [{"unique_identifier": f"A{index:05d}", "asset_type": "equity"} for index in range(count)]


def _upsert(markets, values):
    return bulk_upsert_model(markets.context, model=AssetTable, values=values, conflict_columns=KEY)


def _statuses(result) -> list[tuple[str, str]]:
    return [(row["unique_identifier"], row[UPSERT_STATUS_COLUMN]) for row in result["rows"]]


def _stored(markets, sql: str) -> list[tuple]:
    with markets.engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(sql)]


def _assert_inside_the_limits(markets) -> None:
    assert max(len(statement.sql) for statement in markets.statements) <= MAX_STATEMENT_SQL_CHARACTERS
    assert (
        max(len(statement.parameters) for statement in markets.statements)
        <= MAX_STATEMENT_PARAMETERS
    )


def test_a_long_list_is_upserted_in_statements_inside_the_limits(markets) -> None:
    values = _assets(12_000)
    _upsert(markets, [values[11_999], values[5], values[7000]])
    versions = "SELECT unique_identifier, ctid::text, xmin::text FROM ms_markets__asset ORDER BY 1"
    before = {row[0]: row[1:] for row in _stored(markets, versions)}
    markets.statements.clear()
    values[5] = {**values[5], "asset_type": "bond"}

    result = _upsert(markets, values)

    expected = {11_999: "unchanged", 5: "updated", 7000: "unchanged"}
    assert _statuses(result) == [
        (row["unique_identifier"], expected.get(index, "inserted"))
        for index, row in enumerate(values)
    ]
    assert result["row_count"] == 12_000
    assert _stored(markets, "SELECT count(*), count(DISTINCT uid) FROM ms_markets__asset") == [
        (12_000, 12_000)
    ]
    assert _stored(markets, "SELECT unique_identifier FROM ms_markets__asset WHERE asset_type = 'bond'") == [
        ("A00005",)
    ]
    assert len(markets.statements) > 1
    _assert_inside_the_limits(markets)
    # As one statement these rows are over the limit MetaTables enforces.
    assert sum(len(statement.sql) for statement in markets.statements) > MAX_STATEMENT_SQL_CHARACTERS
    # The unchanged rows are the row versions they were; the updated row is a new one.
    after = {row[0]: row[1:] for row in _stored(markets, versions)}
    assert after["A11999"] == before["A11999"]
    assert after["A07000"] == before["A07000"]
    assert after["A00005"] != before["A00005"]

    markets.statements.clear()
    again = _upsert(markets, values)

    assert {status for _identifier, status in _statuses(again)} == {"unchanged"}
    assert {row[0]: row[1:] for row in _stored(markets, versions)} == after


def test_more_statements_than_one_transaction_holds(markets, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_SQL_CHARACTERS", 20_000)
    values = _assets(4000)
    _upsert(markets, values[1000:1003])
    markets.statements.clear()

    result = _upsert(markets, values)

    assert len(markets.statements) > 32
    assert max(len(statement.sql) for statement in markets.statements) <= 20_000
    assert _statuses(result) == [
        (row["unique_identifier"], "unchanged" if 1000 <= index < 1003 else "inserted")
        for index, row in enumerate(values)
    ]


def test_the_row_api_upserts_more_assets_than_one_statement_holds(markets) -> None:
    """About 5,500 asset rows fill one statement's SQL text (measured for issue 84)."""

    values = _assets(6000)

    rows = Asset.upsert_many(values)

    assert [row.unique_identifier for row in rows] == [row["unique_identifier"] for row in values]
    assert len({row.uid for row in rows}) == 6000
    assert len(markets.statements) > 1
    _assert_inside_the_limits(markets)


def test_calendar_exceptions_longer_than_one_statement_are_upserted(markets) -> None:
    """About 2,300 exception rows fill one statement's SQL text (measured for issue 84)."""

    calendar = Calendar.create(
        unique_identifier="ISSUE-84",
        display_name="Issue 84",
        calendar_type="CUSTOM",
        valid_from=dt.date(2000, 1, 1),
        valid_to=dt.date(2100, 12, 31),
    )
    first = dt.date(2000, 1, 1)
    values = [
        {
            "calendar_uid": calendar.uid,
            "local_date": first + dt.timedelta(days=index),
            "exception_type": "CLOSED",
            "name": f"Closed {index}",
        }
        for index in range(3000)
    ]
    markets.statements.clear()

    rows = CalendarException.upsert_many(values)

    assert [row.local_date for row in rows] == [row["local_date"] for row in values]
    assert {row.source for row in rows} == {"user"}
    assert _stored(markets, "SELECT count(*) FROM ms_markets__calendarexception") == [(3000,)]
    writes = [statement for statement in markets.statements if "ON CONFLICT" in statement.sql]
    assert len(writes) > 1
    _assert_inside_the_limits(markets)
