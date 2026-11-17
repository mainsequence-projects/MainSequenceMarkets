"""Calendar writes and reads on PostgreSQL, end to end (ADR 0055).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost. The statements run through psycopg as the MetaTables API binds
them, so the one-transaction calendar write, its multi-row inserts and the paged
exception reads are exercised on the dialect the hosted Markets API uses.
"""

from __future__ import annotations

import datetime as dt
import warnings
from types import SimpleNamespace

import pytest

from msm.api.calendars import Calendar, CalendarException
from msm.services.calendars import (
    PANDAS_MARKET_CALENDARS_SOURCE,
    CalendarRangeError,
    sync_pandas_market_calendar,
)
from tests.msm.repositories.test_postgresql_account_registration import (  # noqa: F401
    postgresql_markets,
)

UTC = dt.UTC


@pytest.fixture
def markets(postgresql_markets, monkeypatch):  # noqa: F811
    engine, context, operations = postgresql_markets
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=context),
    )
    return SimpleNamespace(engine=engine, context=context, operations=operations)


def _count(markets, table: str, where: str = "true") -> int:
    with markets.engine.connect() as connection:
        return connection.exec_driver_sql(f"SELECT count(*) FROM {table} WHERE {where}").scalar_one()


def test_a_library_calendar_is_written_to_its_horizon_in_one_transaction(markets) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        calendar = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")

    assert (calendar.valid_from, calendar.valid_to) == (dt.date(1990, 1, 1), dt.date(2200, 12, 31))
    assert markets.operations.count("transaction") == 1
    assert _count(markets, "ms_markets__calendarsessionrule") == 1
    exceptions = _count(markets, "ms_markets__calendarexception")
    assert 2000 < exceptions < 3000
    assert _count(
        markets, "ms_markets__calendarexception", f"source = '{PANDAS_MARKET_CALENDARS_SOURCE}'"
    ) == exceptions

    # The exceptions of two centuries are more than one read returns: they are paged.
    sessions = Calendar.sessions(calendar.uid, dt.date(1990, 1, 1), dt.date(2200, 12, 31))
    assert len(sessions) > 50000
    assert (sessions[0].local_date, sessions[-1].local_date) == (
        dt.date(1990, 1, 2),
        dt.date(2200, 12, 31),
    )
    november = {
        session.local_date.isoformat(): session
        for session in Calendar.sessions(calendar.uid, dt.date(2024, 11, 27), dt.date(2024, 11, 29))
    }
    assert sorted(november) == ["2024-11-27", "2024-11-29"]
    assert november["2024-11-29"].closes_at == dt.datetime(2024, 11, 29, 18, 0, tzinfo=UTC)
    with pytest.raises(CalendarRangeError):
        Calendar.sessions(calendar.uid, dt.date(2200, 12, 1), dt.date(2201, 1, 31))


def test_writing_it_again_keeps_user_rows_and_writes_nothing_new(markets) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        first = sync_pandas_market_calendar(
            markets.context, source_identifier="NYSE", unique_identifier="CustomNYSE"
        )
        calendar_uid = first.calendar["uid"]
        closed = CalendarException.create(
            calendar_uid=calendar_uid,
            local_date=dt.date(2024, 12, 31),
            exception_type="CLOSED",
            name="Desk closed",
            metadata_json={"ticket": 7},
        )
        full_day = CalendarException.upsert(
            calendar_uid=calendar_uid, local_date=dt.date(2024, 12, 24), exception_type="OPEN"
        )
        transactions = markets.operations.count("transaction")
        again = sync_pandas_market_calendar(
            markets.context, source_identifier="NYSE", unique_identifier="CustomNYSE"
        )
        dry = sync_pandas_market_calendar(
            markets.context, source_identifier="NYSE", unique_identifier="CustomNYSE", dry_run=True
        )

    assert (closed.source, full_day.source, closed.metadata_json) == ("user", "user", {"ticket": 7})
    assert (again.created, again.changed, dry.changed) == (False, False, False)
    assert markets.operations.count("transaction") == transactions
    assert _count(markets, "ms_markets__calendarexception", "source = 'user'") == 2
    sessions = {
        session.local_date.isoformat(): session
        for session in Calendar.sessions(calendar_uid, dt.date(2024, 12, 23), dt.date(2024, 12, 31))
    }
    # The user's full day replaces the library's early close; the user's closure holds.
    assert sessions["2024-12-24"].closes_at == dt.datetime(2024, 12, 24, 21, 0, tzinfo=UTC)
    assert "2024-12-31" not in sessions
    assert "2024-12-25" not in sessions

    with pytest.raises(ValueError, match="CLOSED exception next to OPEN"):
        CalendarException.create(
            calendar_uid=calendar_uid, local_date=dt.date(2024, 12, 24), exception_type="CLOSED"
        )

    # Deleting the calendar deletes its rules and exceptions.
    Calendar.delete(calendar_uid)
    assert _count(markets, "ms_markets__calendarexception") == 0
    assert _count(markets, "ms_markets__calendarsessionrule") == 0
