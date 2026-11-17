"""The pandas_market_calendars adapter writes rules and exceptions (ADR 0055)."""

from __future__ import annotations

import datetime as dt
import warnings
from functools import cache

import pandas as pd
import pandas_market_calendars as mcal
import pytest

from msm.services.calendars import (
    DEFAULT_VALID_FROM,
    PANDAS_MARKET_CALENDARS_SOURCE,
    CalendarDefinition,
    build_pandas_market_calendar_definition,
    compute_sessions,
)

UTC_CHECK_END = dt.date(2099, 12, 31)
"""pandas stops applying daylight saving in 2100, so the library's UTC instants are compared to here."""


@cache
def source(name: str, valid_from: str | None = None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return build_pandas_market_calendar_definition(source_identifier=name, valid_from=valid_from)


def stored(name: str) -> CalendarDefinition:
    built = source(name)
    return CalendarDefinition.from_rows(
        timezone=built.timezone,
        rules=built.rules,
        exceptions=built.exceptions,
        valid_from=built.valid_from,
        valid_to=built.valid_to,
    )


def library_schedule(name: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return mcal.get_calendar(name).schedule(
            start_date=start.isoformat(), end_date=end.isoformat()
        )


@pytest.mark.parametrize("name", ["NYSE", "XMEX", "CME_Equity", "LSE"])
def test_the_stored_calendar_reproduces_the_library_session_for_session(name: str) -> None:
    built = source(name)
    start, end = built.valid_from, built.valid_to
    computed = compute_sessions(stored(name), start, end)
    schedule = library_schedule(name, start, end)

    assert [session.local_date for session in computed] == [value.date() for value in schedule.index]
    # Wall-clock times match over the whole range.
    local_open = schedule["market_open"].dt.tz_convert(built.timezone)
    local_close = schedule["market_close"].dt.tz_convert(built.timezone)
    assert [(s.opens_at_local, s.closes_at_local) for s in computed] == [
        (opens.time(), closes.time()) for opens, closes in zip(local_open, local_close, strict=True)
    ]
    # UTC instants match where the library still applies daylight saving.
    mine = {
        s.local_date: (s.opens_at, s.closes_at) for s in computed if s.local_date <= UTC_CHECK_END
    }
    theirs = {
        index.date(): (opens.to_pydatetime(), closes.to_pydatetime())
        for index, opens, closes in zip(
            schedule.index, schedule["market_open"], schedule["market_close"], strict=True
        )
        if index.date() <= UTC_CHECK_END
    }
    assert mine == theirs


def test_nyse_is_one_rule_and_about_twelve_exceptions_a_year() -> None:
    built = source("NYSE")

    assert built.source == PANDAS_MARKET_CALENDARS_SOURCE
    assert built.source_identifier == "NYSE"
    assert built.timezone == "America/New_York"
    assert (built.valid_from, built.valid_to) == (DEFAULT_VALID_FROM, dt.date(2200, 12, 31))
    assert built.rules == [
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
    ]
    years = built.valid_to.year - built.valid_from.year + 1
    assert 10 < len(built.exceptions) / years < 14
    assert {row["source"] for row in built.exceptions} == {PANDAS_MARKET_CALENDARS_SOURCE}


def test_nyse_exceptions_of_the_adr_worked_example() -> None:
    rows = {
        (row["local_date"].isoformat(), row["exception_type"]): row
        for row in source("NYSE").exceptions
        if dt.date(2024, 11, 25) <= row["local_date"] <= dt.date(2024, 12, 31)
    }

    assert sorted(rows) == [
        ("2024-11-28", "CLOSED"),
        ("2024-11-29", "EARLY_CLOSE"),
        ("2024-12-24", "EARLY_CLOSE"),
        ("2024-12-25", "CLOSED"),
    ]
    thanksgiving = rows[("2024-11-28", "CLOSED")]
    assert (thanksgiving["session_label"], thanksgiving["name"]) == ("", "Thanksgiving")
    early = rows[("2024-11-29", "EARLY_CLOSE")]
    assert (early["session_label"], early["closes_at_local"], early["opens_at_local"]) == (
        "regular",
        "13:00:00",
        None,
    )


def test_an_ad_hoc_closure_is_an_exception_without_a_name() -> None:
    sandy = [row for row in source("NYSE").exceptions if row["local_date"] == dt.date(2012, 10, 29)]

    assert [(row["exception_type"], row["name"]) for row in sandy] == [("CLOSED", None)]


def test_a_change_of_regular_hours_is_a_new_rule_on_the_day_it_changed() -> None:
    rules = source("CME_Equity").rules

    assert [
        (rule["effective_from"].isoformat(), rule["opens_at_local"], rule["closes_at_local"])
        for rule in rules
    ] == [
        ("1990-01-01", "17:00:00", "16:00:00"),
        ("2005-09-12", "15:30:00", "15:15:00"),
        ("2012-11-19", "17:00:00", "16:00:00"),
    ]
    # The session opens the evening before its local date.
    assert {rule["open_day_offset"] for rule in rules} == {-1}
    assert [rule["effective_to"] for rule in rules] == [
        dt.date(2005, 9, 11),
        dt.date(2012, 11, 18),
        None,
    ]


def test_a_calendar_with_no_holidays_has_no_range_end() -> None:
    always_open = source("24/7")

    assert (always_open.valid_from, always_open.valid_to) == (DEFAULT_VALID_FROM, None)
    assert always_open.exceptions == []
    assert [(rule["weekdays"], rule["opens_at_local"], rule["close_day_offset"]) for rule in always_open.rules] == [
        ("1111111", "00:00:00", 1)
    ]


def test_an_exchange_that_opened_later_has_no_rule_before_it() -> None:
    iex = source("IEX")

    assert iex.valid_from == DEFAULT_VALID_FROM
    assert iex.rules[0]["effective_from"] > dt.date(2013, 1, 1)
    # No closure is written for the years before the exchange existed.
    assert min(row["local_date"] for row in iex.exceptions) >= iex.rules[0]["effective_from"]


def test_a_mirrored_calendar_ends_where_its_holidays_can_be_computed() -> None:
    assert source("XSAU").valid_to == dt.date(2029, 12, 31)


def test_valid_from_is_the_callers_when_given() -> None:
    built = source("NYSE", "2020-01-01")

    assert built.valid_from == dt.date(2020, 1, 1)
    assert built.rules[0]["effective_from"] == dt.date(2020, 1, 1)
    assert min(row["local_date"] for row in built.exceptions) == dt.date(2020, 1, 1)


def test_valid_from_after_the_library_horizon_is_refused() -> None:
    with pytest.raises(ValueError, match="last date"):
        build_pandas_market_calendar_definition(source_identifier="NYSE", valid_from="2300-01-01")
