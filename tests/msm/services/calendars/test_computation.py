"""Dates and sessions computed from rules and exceptions (ADR 0055)."""

from __future__ import annotations

import datetime as dt

import pytest

from msm.services.calendars import (
    CalendarDefinition,
    CalendarRangeError,
    compute_dates,
    compute_sessions,
    format_local_time,
    is_business_day,
    iter_local_dates,
    normalize_weekdays,
    parse_local_time,
)

UTC = dt.UTC
ADAPTER = "pandas_market_calendars"


def nyse(*exceptions: dict, **values) -> CalendarDefinition:
    """NYSE around the end of 2024, as in the worked example of ADR 0055."""

    return CalendarDefinition.from_rows(
        timezone="America/New_York",
        rules=[
            {
                "session_label": "regular",
                "effective_from": "1985-01-01",
                "weekdays": "1111100",
                "opens_at_local": "09:30",
                "closes_at_local": "16:00",
            }
        ],
        exceptions=[
            {"local_date": "2024-11-28", "exception_type": "CLOSED", "name": "Thanksgiving Day", "source": ADAPTER},
            {"local_date": "2024-11-29", "session_label": "regular", "exception_type": "EARLY_CLOSE", "closes_at_local": "13:00:00", "source": ADAPTER},
            {"local_date": "2024-12-24", "session_label": "regular", "exception_type": "EARLY_CLOSE", "closes_at_local": "13:00:00", "source": ADAPTER},
            {"local_date": "2024-12-25", "exception_type": "CLOSED", "name": "Christmas Day", "source": ADAPTER},
            *exceptions,
        ],
        unique_identifier="NYSE",
        **values,
    )


def sessions_by_date(definition: CalendarDefinition, start: str, end: str) -> dict:
    return {
        session.local_date.isoformat(): (session.opens_at, session.closes_at)
        for session in compute_sessions(definition, start, end)
    }


def test_iter_local_dates_requires_ordered_range() -> None:
    assert list(iter_local_dates("2026-01-01", "2026-01-03")) == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        dt.date(2026, 1, 3),
    ]
    with pytest.raises(ValueError):
        list(iter_local_dates("2026-01-03", "2026-01-01"))


def test_worked_example_of_the_adr() -> None:
    sessions = sessions_by_date(nyse(), "2024-11-25", "2024-12-31")

    # 37 dates, 25 sessions, from 1 rule and 4 exceptions.
    assert len(sessions) == 25
    assert sessions["2024-11-27"] == (
        dt.datetime(2024, 11, 27, 14, 30, tzinfo=UTC),
        dt.datetime(2024, 11, 27, 21, 0, tzinfo=UTC),
    )
    assert "2024-11-28" not in sessions
    assert sessions["2024-11-29"] == (
        dt.datetime(2024, 11, 29, 14, 30, tzinfo=UTC),
        dt.datetime(2024, 11, 29, 18, 0, tzinfo=UTC),
    )
    assert "2024-11-30" not in sessions


def test_local_times_follow_daylight_saving() -> None:
    sessions = sessions_by_date(nyse(), "2024-07-01", "2024-07-01")

    # New York is four hours behind UTC in July and five in November.
    assert sessions["2024-07-01"][0] == dt.datetime(2024, 7, 1, 13, 30, tzinfo=UTC)


def test_date_facts() -> None:
    facts = {date.local_date.isoformat(): date for date in compute_dates(nyse(), "2024-11-27", "2024-12-01")}

    wednesday, thanksgiving, friday, saturday = (
        facts["2024-11-27"],
        facts["2024-11-28"],
        facts["2024-11-29"],
        facts["2024-11-30"],
    )
    assert (wednesday.is_business_day, wednesday.is_holiday, wednesday.is_weekend) == (True, False, False)
    assert (thanksgiving.is_business_day, thanksgiving.is_holiday, thanksgiving.is_weekend) == (False, True, False)
    assert thanksgiving.holiday_name == "Thanksgiving Day"
    assert (friday.is_business_day, friday.is_early_close) == (True, True)
    assert (saturday.is_business_day, saturday.is_holiday, saturday.is_weekend) == (False, False, True)
    assert is_business_day(nyse(), "2024-11-27")
    assert not is_business_day(nyse(), "2024-11-28")


def test_a_user_row_wins_for_its_date() -> None:
    """The CustomNYSE example of ADR 0055: a desk's own rows on top of the library's."""

    custom = nyse(
        {"local_date": "2024-12-24", "exception_type": "OPEN", "source": "user"},
        {"local_date": "2024-12-31", "exception_type": "CLOSED", "source": "user"},
    )
    sessions = sessions_by_date(custom, "2024-12-23", "2024-12-31")

    # The date has a user row, so the library's early close is ignored.
    assert sessions["2024-12-24"] == (
        dt.datetime(2024, 12, 24, 14, 30, tzinfo=UTC),
        dt.datetime(2024, 12, 24, 21, 0, tzinfo=UTC),
    )
    assert "2024-12-31" not in sessions
    # Every other date is as the library has it.
    assert "2024-12-25" not in sessions
    assert sessions["2024-12-26"] == sessions_by_date(nyse(), "2024-12-26", "2024-12-26")["2024-12-26"]


def test_a_user_open_row_cancels_a_library_closure() -> None:
    custom = nyse({"local_date": "2024-12-25", "exception_type": "OPEN", "source": "user"})

    assert is_business_day(custom, "2024-12-25")


def test_open_runs_a_session_on_a_date_the_rule_has_none() -> None:
    saturday = nyse(
        {
            "local_date": "2024-11-30",
            "session_label": "regular",
            "exception_type": "OPEN",
            "closes_at_local": "12:00",
            "source": ADAPTER,
        }
    )
    sessions = sessions_by_date(saturday, "2024-11-30", "2024-11-30")

    # The open is the rule's; the close is the row's.
    assert sessions["2024-11-30"] == (
        dt.datetime(2024, 11, 30, 14, 30, tzinfo=UTC),
        dt.datetime(2024, 11, 30, 17, 0, tzinfo=UTC),
    )
    date = compute_dates(saturday, "2024-11-30", "2024-11-30")[0]
    assert (date.is_business_day, date.is_weekend) == (True, True)


def test_late_open_and_early_close_on_one_date() -> None:
    both = nyse(
        {"local_date": "2024-12-02", "session_label": "regular", "exception_type": "LATE_OPEN", "opens_at_local": "11:00", "source": ADAPTER},
        {"local_date": "2024-12-02", "session_label": "regular", "exception_type": "EARLY_CLOSE", "closes_at_local": "14:00", "source": ADAPTER},
    )
    session = compute_sessions(both, "2024-12-02", "2024-12-02")[0]

    assert session.opens_at == dt.datetime(2024, 12, 2, 16, 0, tzinfo=UTC)
    assert session.closes_at == dt.datetime(2024, 12, 2, 19, 0, tzinfo=UTC)
    assert (session.is_late_open, session.is_early_close) == (True, True)


def test_a_read_outside_the_range_is_refused() -> None:
    bounded = nyse(valid_from="1990-01-01", valid_to="2200-12-31")

    assert compute_sessions(bounded, "2200-12-29", "2200-12-31")
    with pytest.raises(CalendarRangeError, match="NYSE.*1990-01-01 to 2200-12-31"):
        compute_sessions(bounded, "2200-12-29", "2201-01-02")
    with pytest.raises(CalendarRangeError):
        compute_dates(bounded, "1989-12-31", "1990-01-02")
    with pytest.raises(CalendarRangeError):
        is_business_day(bounded, "2201-01-02")


def test_a_null_bound_is_not_checked() -> None:
    unbounded = nyse(valid_from="1990-01-01")

    assert len(compute_sessions(unbounded, "2500-01-04", "2500-01-10")) == 5
    with pytest.raises(CalendarRangeError):
        compute_sessions(unbounded, "1989-12-29", "1990-01-02")


def test_always_open_calendar_is_one_rule_and_no_exception() -> None:
    always_open = CalendarDefinition.from_rows(
        timezone="UTC",
        rules=[
            {
                "effective_from": "1990-01-01",
                "weekdays": "1111111",
                "opens_at_local": "00:00:00",
                "closes_at_local": "00:00:00",
                "close_day_offset": 1,
            }
        ],
    )
    sessions = compute_sessions(always_open, "2026-01-03", "2026-01-04")

    assert [(session.opens_at, session.closes_at) for session in sessions] == [
        (dt.datetime(2026, 1, 3, tzinfo=UTC), dt.datetime(2026, 1, 4, tzinfo=UTC)),
        (dt.datetime(2026, 1, 4, tzinfo=UTC), dt.datetime(2026, 1, 5, tzinfo=UTC)),
    ]
    # A calendar that runs every weekday has no weekend.
    assert not any(date.is_weekend for date in compute_dates(always_open, "2026-01-03", "2026-01-04"))


def test_a_session_can_open_the_evening_before() -> None:
    globex = CalendarDefinition.from_rows(
        timezone="America/Chicago",
        rules=[
            {
                "effective_from": "2012-11-19",
                "weekdays": "1111100",
                "opens_at_local": "17:00",
                "closes_at_local": "16:00",
                "open_day_offset": -1,
            }
        ],
    )
    session = compute_sessions(globex, "2024-12-02", "2024-12-02")[0]

    assert session.opens_at == dt.datetime(2024, 12, 1, 23, 0, tzinfo=UTC)
    assert session.closes_at == dt.datetime(2024, 12, 2, 22, 0, tzinfo=UTC)


def test_a_new_rule_changes_the_regular_week_from_its_first_date() -> None:
    changed = CalendarDefinition.from_rows(
        timezone="UTC",
        rules=[
            {"effective_from": "2020-01-01", "effective_to": "2025-12-31", "weekdays": "1111001", "opens_at_local": "10:00", "closes_at_local": "17:00"},
            {"effective_from": "2026-01-01", "weekdays": "1111100", "opens_at_local": "09:00", "closes_at_local": "17:00"},
        ],
    )

    # 2025-12-28 is a Sunday and 2026-01-02 a Friday.
    assert is_business_day(changed, "2025-12-28")
    assert not is_business_day(changed, "2025-12-26")
    assert is_business_day(changed, "2026-01-02")
    assert not is_business_day(changed, "2026-01-04")
    assert compute_sessions(changed, "2026-01-02", "2026-01-02")[0].opens_at.hour == 9


def test_a_date_only_calendar_has_sessions_without_times() -> None:
    settlement = CalendarDefinition.from_rows(
        rules=[{"effective_from": "2020-01-01", "weekdays": "1111100"}],
        exceptions=[{"local_date": "2026-01-01", "exception_type": "CLOSED", "source": ADAPTER}],
    )
    sessions = compute_sessions(settlement, "2025-12-31", "2026-01-02")

    assert [session.local_date.isoformat() for session in sessions] == ["2025-12-31", "2026-01-02"]
    assert all(session.opens_at is None and session.closes_at is None for session in sessions)


def test_an_exception_for_one_session_leaves_the_others() -> None:
    two_sessions = CalendarDefinition.from_rows(
        timezone="UTC",
        rules=[
            {"session_label": "regular", "effective_from": "2020-01-01", "weekdays": "1111100", "opens_at_local": "09:00", "closes_at_local": "17:00"},
            {"session_label": "evening", "effective_from": "2020-01-01", "weekdays": "1111100", "opens_at_local": "18:00", "closes_at_local": "22:00", "is_primary": False},
        ],
        exceptions=[
            {"local_date": "2026-01-05", "session_label": "evening", "exception_type": "CLOSED", "source": ADAPTER},
            {"local_date": "2026-01-06", "exception_type": "CLOSED", "source": ADAPTER},
        ],
    )

    assert [s.session_label for s in compute_sessions(two_sessions, "2026-01-05", "2026-01-05")] == ["regular"]
    assert compute_sessions(two_sessions, "2026-01-06", "2026-01-06") == []
    assert [s.session_label for s in compute_sessions(two_sessions, "2026-01-07", "2026-01-07")] == ["regular", "evening"]
    assert [s.session_label for s in compute_sessions(two_sessions, "2026-01-07", "2026-01-07", session_label="evening")] == ["evening"]


def test_local_time_text() -> None:
    assert format_local_time("09:30") == "09:30:00"
    assert format_local_time(dt.time(13, 0)) == "13:00:00"
    assert format_local_time(None) is None
    assert parse_local_time("16:00:00") == dt.time(16, 0)
    with pytest.raises(ValueError):
        parse_local_time("4pm")
    with pytest.raises(ValueError):
        parse_local_time("16:00:00+01:00")


def test_weekday_mask() -> None:
    assert normalize_weekdays("1111100") == "1111100"
    for bad in ("11111", "1111102", "MTWTF--"):
        with pytest.raises(ValueError):
            normalize_weekdays(bad)


def test_a_date_no_rule_covers_is_neither_a_holiday_nor_a_weekend() -> None:
    """An exchange that opened in 2013 has no holiday in 2012."""

    late = CalendarDefinition.from_rows(
        timezone="America/New_York",
        rules=[
            {
                "effective_from": "2013-08-26",
                "weekdays": "1111100",
                "opens_at_local": "09:30",
                "closes_at_local": "16:00",
            }
        ],
    )
    before = compute_dates(late, "2012-01-02", "2012-01-08")
    after = {date.local_date.isoformat(): date for date in compute_dates(late, "2013-08-26", "2013-09-02")}

    assert not any(date.is_business_day or date.is_holiday or date.is_weekend for date in before)
    assert after["2013-08-26"].is_business_day
    assert after["2013-08-31"].is_weekend and not after["2013-08-31"].is_holiday
    # No exception here, so Labor Day is a business day; a rule runs on that weekday.
    assert after["2013-09-02"].is_business_day
    no_rules = CalendarDefinition.from_rows()
    assert not any(
        date.is_holiday or date.is_weekend for date in compute_dates(no_rules, "2024-01-01", "2024-01-07")
    )
