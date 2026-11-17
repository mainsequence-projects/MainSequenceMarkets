"""Read a pandas_market_calendars calendar into session rules and exceptions (ADR 0055).

The adapter finds the calendar's regular weeks in the library's schedule and
writes them as rules. It then compares the schedule with what the rules alone
produce. Every date that differs becomes an exception, so the stored calendar
reproduces the library's schedule for the range, session for session, in local
wall-clock time.

The library computes its UTC instants with pandas, which stops applying
daylight saving in 2100. The stored local times do not have that limit.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from .computation import (
    DEFAULT_SESSION_LABEL,
    EXCEPTION_CLOSED,
    EXCEPTION_EARLY_CLOSE,
    EXCEPTION_LATE_OPEN,
    EXCEPTION_OPEN,
    WHOLE_DAY,
    format_local_time,
)
from .validation import coerce_local_date, iter_local_dates

PANDAS_MARKET_CALENDARS_SOURCE = "pandas_market_calendars"

DEFAULT_VALID_FROM = dt.date(1990, 1, 1)
"""First date the adapter writes when the caller passes none (ADR 0055, decision 2)."""

_UNBOUNDED_SAMPLE_DAYS = 366
"""Days past today read from a library calendar that has no holidays, to find its rules."""

_REGIME_WEEKS = 6
"""Weeks in a row a week's shape must hold to count as the calendar's regular week."""

_REGIME_GAP_WEEKS = 2
"""Holiday weeks in a row a forming regular week may contain, as at the turn of a year."""

_UNSET: Any = object()


@dataclass(frozen=True)
class CalendarSourceDefinition:
    """What an adapter read from its library: rules, exceptions and their range.

    The rows carry no ``calendar_uid``; the write adds it.
    """

    source: str
    source_identifier: str
    source_version: str
    timezone: str
    valid_from: dt.date | None
    valid_to: dt.date | None
    rules: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _LibrarySession:
    opens: dt.time | None
    closes: dt.time | None
    open_offset: int
    close_offset: int

    @property
    def hours(self) -> tuple[dt.time | None, dt.time | None, int, int]:
        return (self.opens, self.closes, self.open_offset, self.close_offset)


def pandas_market_calendar_timezone(source_identifier: str) -> str:
    """The timezone the library declares for one of its calendars."""

    import pandas_market_calendars as mcal

    calendar = mcal.get_calendar(source_identifier)
    return str(getattr(calendar, "tz", None) or "UTC")


def build_pandas_market_calendar_definition(
    *,
    source_identifier: str,
    valid_from: dt.date | dt.datetime | str | None = None,
    timezone: str | None = None,
    session_label: str = DEFAULT_SESSION_LABEL,
    today: dt.date | None = None,
) -> CalendarSourceDefinition:
    """Build the rules and exceptions of one pandas_market_calendars calendar.

    The range ends where the library's holiday rules end. A library calendar
    with no holidays, such as ``24/7``, has nothing to project: its definition
    is rules alone and has no last date.
    """

    import pandas_market_calendars as mcal

    market_calendar = mcal.get_calendar(source_identifier)
    calendar_timezone = timezone or str(getattr(market_calendar, "tz", None) or "UTC")
    horizon = _library_horizon(market_calendar)
    start = DEFAULT_VALID_FROM if valid_from in (None, "") else coerce_local_date(valid_from)
    if horizon is None:
        end = max(start, today or dt.date.today()) + dt.timedelta(days=_UNBOUNDED_SAMPLE_DAYS)
    else:
        end = horizon
    if end < start:
        raise ValueError(
            f"valid_from {start.isoformat()} is after {end.isoformat()}, the last date "
            f"pandas_market_calendars can answer for on {source_identifier!r}."
        )

    library = _library_sessions(market_calendar, start, end, calendar_timezone)
    rules = _rules(library, start=start, end=end, session_label=session_label)
    exceptions = _exceptions(
        library,
        rules,
        start=start,
        end=end,
        session_label=session_label,
        names=_holiday_names(market_calendar, start, end),
        source_identifier=source_identifier,
    )
    return CalendarSourceDefinition(
        source=PANDAS_MARKET_CALENDARS_SOURCE,
        source_identifier=source_identifier,
        source_version=metadata.version("pandas-market-calendars"),
        timezone=calendar_timezone,
        valid_from=start,
        valid_to=horizon,
        rules=[_rule_row(rule) for rule in rules],
        exceptions=exceptions,
    )


@dataclass(frozen=True)
class _Rule:
    session_label: str
    effective_from: dt.date
    effective_to: dt.date | None
    weekdays: str
    hours: tuple[dt.time | None, dt.time | None, int, int]

    def covers(self, local_date: dt.date) -> bool:
        if local_date < self.effective_from:
            return False
        return self.effective_to is None or local_date <= self.effective_to


def _rule_row(rule: _Rule) -> dict[str, Any]:
    opens, closes, open_offset, close_offset = rule.hours
    return {
        "session_label": rule.session_label,
        "effective_from": rule.effective_from,
        "effective_to": rule.effective_to,
        "weekdays": rule.weekdays,
        "opens_at_local": format_local_time(opens),
        "closes_at_local": format_local_time(closes),
        "open_day_offset": open_offset,
        "close_day_offset": close_offset,
        "is_primary": True,
    }


def _library_horizon(market_calendar: Any) -> dt.date | None:
    """The last date the library can answer for, or None when it has no holidays.

    A calendar mirrored from exchange_calendars that cannot compute its holidays
    past a date declares it as ``bound_max``. Otherwise the horizon is where the
    holiday rules end, which is pandas' default end of a holiday calendar.
    """

    from pandas.tseries.holiday import AbstractHolidayCalendar

    mirrored = getattr(market_calendar, "ec", None)
    bound_max = getattr(mirrored, "bound_max", None)
    if callable(bound_max):
        bound = bound_max()
        if bound is not None:
            return coerce_local_date(bound.date() if hasattr(bound, "date") else bound)

    regular = getattr(market_calendar, "regular_holidays", None)
    adhoc = getattr(market_calendar, "adhoc_holidays", None)
    has_rules = regular is not None and bool(getattr(regular, "rules", None))
    has_adhoc = adhoc is not None and len(adhoc) > 0
    if not has_rules and not has_adhoc:
        return None
    end_date = getattr(regular, "end_date", None) if has_rules else None
    if end_date is None:
        end_date = AbstractHolidayCalendar.end_date
    return coerce_local_date(end_date.date() if hasattr(end_date, "date") else end_date)


def _library_sessions(
    market_calendar: Any,
    start: dt.date,
    end: dt.date,
    timezone: str,
) -> dict[dt.date, _LibrarySession]:
    import pandas as pd

    schedule = market_calendar.schedule(start_date=start.isoformat(), end_date=end.isoformat())
    if schedule.empty:
        return {}
    local_dates = [value.date() for value in schedule.index]
    opens = _local_parts(schedule["market_open"], local_dates, timezone, pd=pd)
    closes = _local_parts(schedule["market_close"], local_dates, timezone, pd=pd)
    return {
        local_date: _LibrarySession(
            opens=open_time,
            closes=close_time,
            open_offset=open_offset,
            close_offset=close_offset,
        )
        for local_date, (open_time, open_offset), (close_time, close_offset) in zip(
            local_dates, opens, closes, strict=True
        )
    }


def _local_parts(
    series: Any,
    local_dates: list[dt.date],
    timezone: str,
    *,
    pd: Any,
) -> list[tuple[dt.time | None, int]]:
    """Each instant as a wall-clock time and its day offset from the session's date."""

    instants = pd.to_datetime(series, utc=True).dt.tz_convert(timezone)
    parts: list[tuple[dt.time | None, int]] = []
    for local_date, instant in zip(local_dates, instants, strict=True):
        if pd.isna(instant):
            parts.append((None, 0))
            continue
        parts.append(
            (
                instant.time().replace(microsecond=0),
                (instant.date() - local_date).days,
            )
        )
    return parts


def _rules(
    library: dict[dt.date, _LibrarySession],
    *,
    start: dt.date,
    end: dt.date,
    session_label: str,
) -> list[_Rule]:
    """Find the calendar's regular weeks in the library's own schedule.

    Each full week has a signature: the weekdays with a session and the week's
    most frequent hours. A signature that holds for ``_REGIME_WEEKS`` weeks in a
    row is a regular week, and a rule starts where it starts. A week with a
    holiday or an early close differs for a week or two and starts nothing.
    A stretch with no session at all, such as the years before an exchange
    opened, has no rule.
    """

    regimes: list[tuple[dt.date, tuple[str, Any] | None]] = []
    weeks: list[tuple[dt.date, tuple[str, Any] | None]] = []
    current: Any = _UNSET
    candidate: Any = _UNSET
    run = 0
    gap = 0
    run_index = 0
    week_start = start - dt.timedelta(days=start.weekday())
    while week_start <= end:
        week_end = week_start + dt.timedelta(days=6)
        if week_start >= start and week_end <= end:
            signature = _week_signature(library, week_start)
            weeks.append((week_start, signature))
            if signature == current:
                candidate, run = _UNSET, 0
            elif signature == candidate:
                run, gap = run + 1, 0
            elif candidate is _UNSET or gap >= _REGIME_GAP_WEEKS:
                candidate, run, gap, run_index = signature, 1, 0, len(weeks) - 1
            else:
                # A holiday week inside the run: it neither counts nor ends it.
                gap += 1
            if candidate is not _UNSET and run >= _REGIME_WEEKS:
                first = _regime_start(weeks, run_index, previous=current, regime=candidate)
                regimes.append((first if regimes else start, candidate))
                current, candidate, run = candidate, _UNSET, 0
        week_start += dt.timedelta(days=7)

    if not regimes:
        # A range shorter than the weeks a regular week needs: take what it has.
        signature = _range_signature(library, start, end)
        regimes = [(start, signature)] if signature is not None else []

    rules: list[_Rule] = []
    for index, (effective_from, signature) in enumerate(regimes):
        if signature is None:
            continue
        last = index + 1 == len(regimes)
        weekdays, hours = signature
        rules.append(
            _Rule(
                session_label=session_label,
                effective_from=effective_from,
                effective_to=None if last else regimes[index + 1][0] - dt.timedelta(days=1),
                weekdays=weekdays,
                hours=hours,
            )
        )
    return rules


def _regime_start(
    weeks: list[tuple[dt.date, tuple[str, Any] | None]],
    run_index: int,
    *,
    previous: Any,
    regime: tuple[str, Any] | None,
) -> dt.date:
    """Move a regular week's start back over holiday weeks that already keep its hours.

    A change of hours often falls in a week with a holiday. That week has neither
    the old shape nor the new one, but its sessions already run at the new hours.
    """

    index = run_index
    if regime is None:
        return weeks[index][0]
    while index > 0:
        signature = weeks[index - 1][1]
        if signature is None or signature == previous or signature[1] != regime[1]:
            break
        index -= 1
    return weeks[index][0]


def _week_signature(
    library: dict[dt.date, _LibrarySession],
    week_start: dt.date,
) -> tuple[str, Any] | None:
    sessions = [library.get(week_start + dt.timedelta(days=offset)) for offset in range(7)]
    held = [session for session in sessions if session is not None]
    if not held:
        return None
    weekdays = "".join("0" if session is None else "1" for session in sessions)
    return weekdays, Counter(session.hours for session in held).most_common(1)[0][0]


def _range_signature(
    library: dict[dt.date, _LibrarySession],
    start: dt.date,
    end: dt.date,
) -> tuple[str, Any] | None:
    hours: Counter[Any] = Counter()
    sessions_per_weekday = [0] * 7
    dates_per_weekday = [0] * 7
    for local_date in iter_local_dates(start, end):
        dates_per_weekday[local_date.weekday()] += 1
        session = library.get(local_date)
        if session is not None:
            sessions_per_weekday[local_date.weekday()] += 1
            hours[session.hours] += 1
    if not hours:
        return None
    weekdays = "".join(
        "1" if sessions * 2 > dates else "0"
        for sessions, dates in zip(sessions_per_weekday, dates_per_weekday, strict=True)
    )
    return weekdays, hours.most_common(1)[0][0]


def _exceptions(
    library: dict[dt.date, _LibrarySession],
    rules: list[_Rule],
    *,
    start: dt.date,
    end: dt.date,
    session_label: str,
    names: dict[dt.date, str],
    source_identifier: str,
) -> list[dict[str, Any]]:
    exceptions: list[dict[str, Any]] = []
    unrepresentable: list[dt.date] = []

    def add(local_date: dt.date, exception_type: str, **values: Any) -> None:
        exceptions.append(
            {
                "local_date": local_date,
                "session_label": (
                    WHOLE_DAY if exception_type == EXCEPTION_CLOSED else session_label
                ),
                "exception_type": exception_type,
                "opens_at_local": format_local_time(values.get("opens")),
                "closes_at_local": format_local_time(values.get("closes")),
                "name": names.get(local_date) if exception_type == EXCEPTION_CLOSED else None,
                "source": PANDAS_MARKET_CALENDARS_SOURCE,
                "metadata_json": None,
            }
        )

    for local_date in iter_local_dates(start, end):
        rule = next((item for item in reversed(rules) if item.covers(local_date)), None)
        scheduled = rule is not None and rule.weekdays[local_date.weekday()] == "1"
        actual = library.get(local_date)
        if actual is None:
            if scheduled:
                add(local_date, EXCEPTION_CLOSED)
            continue

        rule_opens, rule_closes, rule_open_offset, rule_close_offset = (
            rule.hours if rule is not None else (None, None, 0, 0)
        )
        if (actual.open_offset, actual.close_offset) != (rule_open_offset, rule_close_offset):
            unrepresentable.append(local_date)
            continue
        same_open = actual.opens == rule_opens
        same_close = actual.closes == rule_closes
        if not scheduled:
            add(
                local_date,
                EXCEPTION_OPEN,
                opens=None if same_open else actual.opens,
                closes=None if same_close else actual.closes,
            )
            continue
        if same_open and same_close:
            continue
        later_open = _later(actual.opens, rule_opens)
        earlier_close = _later(rule_closes, actual.closes)
        if (same_open or later_open) and (same_close or earlier_close):
            if later_open:
                add(local_date, EXCEPTION_LATE_OPEN, opens=actual.opens)
            if earlier_close:
                add(local_date, EXCEPTION_EARLY_CLOSE, closes=actual.closes)
            continue
        add(
            local_date,
            EXCEPTION_OPEN,
            opens=None if same_open else actual.opens,
            closes=None if same_close else actual.closes,
        )

    if unrepresentable:
        sample = ", ".join(value.isoformat() for value in unrepresentable[:5])
        raise ValueError(
            f"pandas_market_calendars calendar {source_identifier!r} has "
            f"{len(unrepresentable)} session(s) whose open or close falls on another day "
            f"than its regular week's ({sample}). An exception cannot store that."
        )
    return exceptions


def _later(first: dt.time | None, second: dt.time | None) -> bool:
    return first is not None and second is not None and first > second


def _holiday_names(market_calendar: Any, start: dt.date, end: dt.date) -> dict[dt.date, str]:
    """Names of the library's rule holidays in the range, by date.

    The library names its holiday rules, not its schedule: an ad-hoc closure has
    no name here.
    """

    import pandas as pd

    regular = getattr(market_calendar, "regular_holidays", None)
    rules = getattr(regular, "rules", None) or ()
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    names: dict[dt.date, str] = {}
    for rule in rules:
        name = str(getattr(rule, "name", "") or "").strip()
        if not name:
            continue
        for value in rule.dates(first, last):
            names.setdefault(value.date(), name)
    return names


__all__ = [
    "DEFAULT_VALID_FROM",
    "PANDAS_MARKET_CALENDARS_SOURCE",
    "CalendarSourceDefinition",
    "build_pandas_market_calendar_definition",
    "pandas_market_calendar_timezone",
]
