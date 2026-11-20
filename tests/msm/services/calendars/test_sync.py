"""Calendar writes and reads on a SQLite DataSource, end to end (ADR 0055)."""

from __future__ import annotations

import datetime as dt
import warnings

import pytest
import sqlalchemy as sa

from msm.api.calendars import Calendar, CalendarException, CalendarSessionRule
from msm.services.calendars import (
    PANDAS_MARKET_CALENDARS_SOURCE,
    SOURCE_VERSION_KEY,
    CalendarRangeError,
    CalendarSourceDefinition,
    apply_calendar_source_definition,
    get_calendar_record,
    load_calendar_definition,
    read_calendar_session_records,
    sync_pandas_market_calendar,
)
from tests.support.sqlite_markets import serve_row_operations

UTC = dt.UTC


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    return sqlite_markets


def library(version: str = "1.0", **changes) -> CalendarSourceDefinition:
    """What an adapter would read: a Monday-to-Friday week and two closures."""

    values = {
        "source": PANDAS_MARKET_CALENDARS_SOURCE,
        "source_identifier": "NYSE",
        "source_version": version,
        "timezone": "America/New_York",
        "valid_from": dt.date(1990, 1, 1),
        "valid_to": dt.date(2200, 12, 31),
        "rules": [
            {
                "session_label": "regular",
                "effective_from": dt.date(1990, 1, 1),
                "effective_to": None,
                "weekdays": "1111100",
                "opens_at_local": "09:30:00",
                "closes_at_local": "16:00:00",
                "open_day_offset": 0,
                "close_day_offset": 0,
                "is_primary": True,
            }
        ],
        "exceptions": [
            _exception("2024-11-28", "CLOSED", name="Thanksgiving"),
            _exception("2024-11-29", "EARLY_CLOSE", "regular", closes="13:00:00"),
            _exception("2024-12-25", "CLOSED", name="Christmas"),
        ],
    }
    values.update(changes)
    return CalendarSourceDefinition(**values)


def _exception(local_date, exception_type, session_label="", *, closes=None, name=None) -> dict:
    return {
        "local_date": dt.date.fromisoformat(local_date),
        "session_label": session_label,
        "exception_type": exception_type,
        "opens_at_local": None,
        "closes_at_local": closes,
        "name": name,
        "source": PANDAS_MARKET_CALENDARS_SOURCE,
        "metadata_json": None,
    }


def rows(markets, table: str) -> list[dict]:
    with markets.engine.connect() as connection:
        reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
        return [dict(row) for row in connection.execute(sa.select(reflected)).mappings()]


def writes(markets) -> list[str]:
    return [sql for sql in markets.statements if not sql.lstrip().upper().startswith("SELECT")]


def test_the_header_the_rules_and_the_exceptions_are_written_together(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )

    assert (result.created, result.changed, result.dry_run) == (True, True, False)
    assert len(result.exceptions_added) == 3
    calendar = rows(markets, "ms_markets__calendar")[0]
    assert (calendar["unique_identifier"], calendar["display_name"]) == ("NYSE", "NYSE")
    assert (calendar["source"], calendar["source_identifier"]) == (
        PANDAS_MARKET_CALENDARS_SOURCE,
        "NYSE",
    )
    assert (str(calendar["valid_from"]), str(calendar["valid_to"])) == ("1990-01-01", "2200-12-31")
    assert calendar["metadata_json"] == {SOURCE_VERSION_KEY: "1.0"}
    assert len(rows(markets, "ms_markets__calendarsessionrule")) == 1
    assert len(rows(markets, "ms_markets__calendarexception")) == 3
    # One transaction: the header insert, the rule delete and insert, the exception insert.
    assert len(writes(markets)) == 4


def test_writing_the_same_library_again_writes_nothing(markets) -> None:
    apply_calendar_source_definition(markets.context, definition=library(), unique_identifier="NYSE")
    before = len(writes(markets))

    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )

    assert (result.created, result.changed) == (False, False)
    assert result.exceptions_added == result.exceptions_removed == []
    assert len(writes(markets)) == before


def test_a_new_library_version_changes_only_what_differs(markets) -> None:
    apply_calendar_source_definition(markets.context, definition=library(), unique_identifier="NYSE")
    unchanged = {
        row["uid"]
        for row in rows(markets, "ms_markets__calendarexception")
        if str(row["local_date"]) != "2024-11-29"
    }
    newer = library(
        "2.0",
        exceptions=[
            _exception("2024-11-28", "CLOSED", name="Thanksgiving"),
            # The library dropped the early close and learned a closure.
            _exception("2024-12-25", "CLOSED", name="Christmas"),
            _exception("2025-01-09", "CLOSED"),
        ],
    )

    result = apply_calendar_source_definition(
        markets.context, definition=newer, unique_identifier="NYSE"
    )

    assert (result.previous_source_version, result.source_version) == ("1.0", "2.0")
    assert [str(row["local_date"]) for row in result.exceptions_added] == ["2025-01-09"]
    assert [str(row["local_date"]) for row in result.exceptions_removed] == ["2024-11-29"]
    assert not result.rules_changed
    stored = rows(markets, "ms_markets__calendarexception")
    assert sorted(str(row["local_date"]) for row in stored) == ["2024-11-28", "2024-12-25", "2025-01-09"]
    # A row that did not change keeps its uid: it was not rewritten.
    assert unchanged <= {row["uid"] for row in stored}
    assert rows(markets, "ms_markets__calendar")[0]["metadata_json"][SOURCE_VERSION_KEY] == "2.0"


def test_a_dry_run_reports_and_writes_nothing(markets) -> None:
    apply_calendar_source_definition(markets.context, definition=library(), unique_identifier="NYSE")
    before = len(writes(markets))
    newer = library("2.0", exceptions=[_exception("2025-01-09", "CLOSED")])

    result = apply_calendar_source_definition(
        markets.context, definition=newer, unique_identifier="NYSE", dry_run=True
    )

    assert (result.dry_run, result.changed) == (True, True)
    assert len(result.exceptions_added) == 1
    assert len(result.exceptions_removed) == 3
    assert len(writes(markets)) == before
    assert len(rows(markets, "ms_markets__calendarexception")) == 3


def test_a_users_exception_survives_the_adapter_and_wins(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="CustomNYSE"
    )
    calendar_uid = result.calendar["uid"]
    full_day = CalendarException.create(
        calendar_uid=calendar_uid, local_date="2024-11-29", exception_type="open"
    )
    closed = CalendarException.create(
        calendar_uid=calendar_uid, local_date="2024-12-31", exception_type="CLOSED", name="Desk closed"
    )
    assert (full_day.source, closed.source) == ("user", "user")

    again = apply_calendar_source_definition(
        markets.context,
        definition=library(
            "2.0", exceptions=[_exception("2024-11-28", "CLOSED", name="Thanksgiving")]
        ),
        unique_identifier="CustomNYSE",
    )

    assert len(again.exceptions_removed) == 2
    stored = rows(markets, "ms_markets__calendarexception")
    assert sorted((str(row["local_date"]), row["source"]) for row in stored) == [
        ("2024-11-28", PANDAS_MARKET_CALENDARS_SOURCE),
        ("2024-11-29", "user"),
        ("2024-12-31", "user"),
    ]
    sessions = {
        session.local_date.isoformat(): session
        for session in Calendar.sessions(calendar_uid, dt.date(2024, 11, 27), dt.date(2024, 12, 31))
    }
    assert "2024-11-28" not in sessions
    assert sessions["2024-11-29"].closes_at == dt.datetime(2024, 11, 29, 21, 0, tzinfo=UTC)
    assert "2024-12-31" not in sessions
    assert not Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 31))
    assert Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 30))


def test_one_library_calendar_backs_several_stored_calendars(markets) -> None:
    first = apply_calendar_source_definition(markets.context, definition=library(), unique_identifier="NYSE")
    second = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="CustomNYSE", display_name="Desk NYSE"
    )

    assert first.calendar["uid"] != second.calendar["uid"]
    assert sorted(row["unique_identifier"] for row in rows(markets, "ms_markets__calendar")) == [
        "CustomNYSE",
        "NYSE",
    ]
    assert len(rows(markets, "ms_markets__calendarexception")) == 6
    assert Calendar.get_by_unique_identifier("CustomNYSE").display_name == "Desk NYSE"


def test_a_calendar_written_from_another_source_is_refused(markets) -> None:
    apply_calendar_source_definition(markets.context, definition=library(), unique_identifier="NYSE")
    Calendar.create(unique_identifier="DESK", display_name="Desk", calendar_type="CUSTOM")

    with pytest.raises(ValueError, match="from pandas_market_calendars calendar 'NYSE'"):
        apply_calendar_source_definition(
            markets.context,
            definition=library(source_identifier="LSE"),
            unique_identifier="NYSE",
        )
    with pytest.raises(ValueError, match="written by hand"):
        apply_calendar_source_definition(
            markets.context, definition=library(), unique_identifier="DESK"
        )


def test_a_read_outside_the_range_is_refused(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar_uid = result.calendar["uid"]

    with pytest.raises(CalendarRangeError, match="1990-01-01 to 2200-12-31"):
        Calendar.sessions(calendar_uid, dt.date(2200, 12, 1), dt.date(2201, 1, 31))
    with pytest.raises(CalendarRangeError):
        Calendar.dates(calendar_uid, dt.date(1989, 12, 1), dt.date(1990, 1, 31))
    # A caller that inspects history reads the part the calendar is complete for.
    clamped = read_calendar_session_records(
        markets.context,
        calendar_uid=str(calendar_uid),
        start_date=dt.date(2200, 12, 29),
        end_date=dt.date(2201, 1, 31),
        clamp_to_range=True,
    )
    assert [str(row["local_date"]) for row in clamped] == ["2200-12-29", "2200-12-30", "2200-12-31"]
    with pytest.raises(LookupError):
        Calendar.sessions("00000000-0000-0000-0000-000000000000", dt.date(2024, 1, 1), dt.date(2024, 1, 2))


def test_computed_dates_of_a_stored_calendar(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )

    dates = {
        date.local_date.isoformat(): date
        for date in Calendar.dates(result.calendar["uid"], dt.date(2024, 11, 28), dt.date(2024, 11, 30))
    }

    assert (dates["2024-11-28"].is_holiday, dates["2024-11-28"].holiday_name) == (True, "Thanksgiving")
    assert (dates["2024-11-29"].is_business_day, dates["2024-11-29"].is_early_close) == (True, True)
    assert dates["2024-11-30"].is_weekend


def test_only_the_exceptions_of_the_window_are_read(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar = get_calendar_record(markets.context, uid=str(result.calendar["uid"]))

    definition = load_calendar_definition(
        markets.context,
        calendar=calendar,
        start_date=dt.date(2024, 12, 1),
        end_date=dt.date(2024, 12, 31),
    )

    assert [entry.local_date.isoformat() for entry in definition.exceptions] == ["2024-12-25"]
    assert len(definition.rules) == 1


def test_a_closed_exception_cannot_stand_next_to_another_user_row(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar_uid = result.calendar["uid"]
    CalendarException.create(
        calendar_uid=calendar_uid,
        local_date="2024-12-30",
        session_label="regular",
        exception_type="EARLY_CLOSE",
        closes_at_local="13:00",
    )

    with pytest.raises(ValueError, match="CLOSED exception next to EARLY_CLOSE"):
        CalendarException.create(
            calendar_uid=calendar_uid,
            local_date="2024-12-30",
            session_label="regular",
            exception_type="CLOSED",
        )
    # The adapter's own closure on a date does not block a user's row for it.
    reopened = CalendarException.upsert(
        calendar_uid=calendar_uid, local_date="2024-12-25", exception_type="OPEN"
    )
    assert reopened.source == "user"
    assert Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 25))


def test_session_rules_are_rows_a_user_can_write(markets) -> None:
    calendar = Calendar.create(
        unique_identifier="DESK", display_name="Desk", calendar_type="CUSTOM", timezone="UTC"
    )
    assert (calendar.valid_from, calendar.valid_to) == (None, None)
    rule = CalendarSessionRule.upsert(
        calendar_uid=calendar.uid,
        effective_from="2026-01-01",
        weekdays="1111100",
        opens_at_local=dt.time(9, 0),
        closes_at_local="17:30",
    )

    assert (rule.session_label, rule.opens_at_local, rule.closes_at_local) == (
        "regular",
        "09:00:00",
        "17:30:00",
    )
    sessions = Calendar.sessions(calendar.uid, dt.date(2026, 1, 5), dt.date(2026, 1, 5))
    assert (sessions[0].opens_at, sessions[0].closes_at) == (
        dt.datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        dt.datetime(2026, 1, 5, 17, 30, tzinfo=UTC),
    )
    # Deleting the calendar deletes its rules and exceptions.
    Calendar.delete(calendar.uid)
    assert rows(markets, "ms_markets__calendarsessionrule") == []


def test_create_from_pandas_calendar_writes_the_library_to_its_horizon(markets) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        calendar = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")
        before = len(writes(markets))
        again = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")

    assert (calendar.unique_identifier, calendar.display_name) == ("CustomNYSE", "CustomNYSE")
    assert (calendar.source, calendar.source_identifier) == (PANDAS_MARKET_CALENDARS_SOURCE, "NYSE")
    assert (calendar.valid_from, calendar.valid_to) == (dt.date(1990, 1, 1), dt.date(2200, 12, 31))
    assert calendar.calendar_type == "TRADING"
    assert calendar.timezone == "America/New_York"
    assert calendar.metadata_json[SOURCE_VERSION_KEY]
    exceptions = rows(markets, "ms_markets__calendarexception")
    assert 2000 < len(exceptions) < 3000
    assert len(rows(markets, "ms_markets__calendarsessionrule")) == 1
    # Calling it again with the same library writes nothing.
    assert again.uid == calendar.uid
    assert len(writes(markets)) == before
    sessions = Calendar.sessions(calendar.uid, dt.date(2024, 11, 25), dt.date(2024, 12, 31))
    assert len(sessions) == 25


def test_a_library_calendar_with_no_holidays_has_no_last_date(markets) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        first = sync_pandas_market_calendar(
            markets.context, source_identifier="24/7", unique_identifier="CRYPTO"
        )
        second = sync_pandas_market_calendar(
            markets.context, source_identifier="24/7", unique_identifier="CRYPTO"
        )

    # A calendar with no holidays has nothing to project: it has no last date.
    assert (first.calendar["valid_from"], first.calendar["valid_to"]) == (dt.date(1990, 1, 1), None)
    assert not second.changed
    assert rows(markets, "ms_markets__calendarexception") == []


def test_writing_a_calendar_again_keeps_or_extends_its_start() -> None:
    """A calendar that starts after 1990-01-01, as a migrated one does, is taken back to it."""

    from msm.services.calendars.sync import _first_date

    assert _first_date(None, None) == dt.date(1990, 1, 1)
    assert _first_date(None, {"valid_from": "2022-01-01"}) == dt.date(1990, 1, 1)
    assert _first_date(None, {"valid_from": "1950-01-01"}) == dt.date(1950, 1, 1)
    assert _first_date("2015-06-01", {"valid_from": "1950-01-01"}) == dt.date(2015, 6, 1)


def test_a_rule_or_exception_is_found_by_its_calendar_whatever_the_uid_spelling(markets) -> None:
    import uuid

    from msm.services.calendars import (
        delete_calendar_exception_record,
        get_calendar_exception_record,
        get_calendar_session_rule_record,
    )

    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar_uid = uuid.UUID(str(result.calendar["uid"]))
    other = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="CustomNYSE"
    )
    exception = CalendarException.create(
        calendar_uid=calendar_uid, local_date="2024-12-31", exception_type="CLOSED"
    )
    rule = CalendarSessionRule.filter(calendar_uid=calendar_uid)[0]

    for spelling in (str(calendar_uid), calendar_uid.hex, str(calendar_uid).upper()):
        assert get_calendar_exception_record(
            markets.context, calendar_uid=spelling, uid=str(exception.uid)
        )
        assert get_calendar_session_rule_record(
            markets.context, calendar_uid=spelling, uid=str(rule.uid)
        )
    # A row of another calendar is not found under this one.
    assert (
        get_calendar_exception_record(
            markets.context, calendar_uid=str(other.calendar["uid"]), uid=str(exception.uid)
        )
        is None
    )
    assert delete_calendar_exception_record(
        markets.context, calendar_uid=str(calendar_uid), uid=str(exception.uid)
    )
    assert Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 31))


def test_deleting_a_users_exception_restores_the_librarys_answer(markets) -> None:
    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar_uid = result.calendar["uid"]
    reopened = CalendarException.create(
        calendar_uid=calendar_uid, local_date="2024-12-25", exception_type="OPEN"
    )
    assert Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 25))

    CalendarException.delete(reopened.uid)

    assert not Calendar.is_business_day(calendar_uid, dt.date(2024, 12, 25))


def test_an_update_is_checked_like_a_new_row(markets) -> None:
    from msm.services.calendars import (
        update_calendar_exception_record,
        update_calendar_session_rule_record,
    )

    result = apply_calendar_source_definition(
        markets.context, definition=library(), unique_identifier="NYSE"
    )
    calendar_uid = str(result.calendar["uid"])
    closed = CalendarException.create(
        calendar_uid=calendar_uid, local_date="2024-12-31", exception_type="CLOSED"
    )
    early = CalendarException.create(
        calendar_uid=calendar_uid,
        local_date="2024-12-30",
        session_label="regular",
        exception_type="EARLY_CLOSE",
        closes_at_local="13:00",
    )
    rule = CalendarSessionRule.filter(calendar_uid=calendar_uid)[0]

    # Through the row API.
    with pytest.raises(ValueError, match="CLOSED exception has no open or close time"):
        CalendarException.update(closed.uid, closes_at_local="13:00")
    with pytest.raises(ValueError, match="EARLY_CLOSE exception sets closes_at_local only"):
        CalendarException.update(early.uid, opens_at_local="10:00")
    with pytest.raises(ValueError, match="effective_to must be greater than or equal"):
        CalendarSessionRule.update(rule.uid, effective_to="1980-01-01")
    with pytest.raises(LookupError):
        CalendarException.update("00000000-0000-0000-0000-000000000000", name="x")
    # Through the record services the routes call.
    with pytest.raises(ValueError, match="CLOSED exception has no open or close time"):
        update_calendar_exception_record(
            markets.context, calendar_uid=calendar_uid, uid=str(closed.uid), opens_at_local="10:00"
        )
    with pytest.raises(ValueError, match="effective_to must be greater than or equal"):
        update_calendar_session_rule_record(
            markets.context, calendar_uid=calendar_uid, uid=str(rule.uid), effective_to="1980-01-01"
        )

    # A valid change is written.
    later = CalendarException.update(early.uid, closes_at_local="14:00", name="Desk half day")
    assert (later.closes_at_local, later.name, later.source) == ("14:00:00", "Desk half day", "user")
    ended = CalendarSessionRule.update(rule.uid, effective_to="2199-12-31")
    assert ended.effective_to == dt.date(2199, 12, 31)
