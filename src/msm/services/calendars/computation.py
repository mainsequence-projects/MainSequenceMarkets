"""Compute a calendar's dates and sessions from its rules and exceptions (ADR 0055).

Nothing here reads a table or imports a source library. A calendar is a
``CalendarDefinition``: its timezone, its session rules and its exceptions.
Local times become UTC instants here, with the timezone rules of this process.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .validation import coerce_local_date, ensure_date_range, iter_local_dates

EXCEPTION_CLOSED = "CLOSED"
EXCEPTION_EARLY_CLOSE = "EARLY_CLOSE"
EXCEPTION_LATE_OPEN = "LATE_OPEN"
EXCEPTION_OPEN = "OPEN"
EXCEPTION_TYPES = (
    EXCEPTION_CLOSED,
    EXCEPTION_EARLY_CLOSE,
    EXCEPTION_LATE_OPEN,
    EXCEPTION_OPEN,
)

USER_SOURCE = "user"
"""``CalendarException.source`` of a row written through the row API or the routes."""

WHOLE_DAY = ""
"""``CalendarException.session_label`` of an exception that applies to every session."""

DEFAULT_SESSION_LABEL = "regular"


class CalendarRangeError(ValueError):
    """A date outside the range a calendar's rules and exceptions are complete for."""


def parse_local_time(value: dt.time | str | None) -> dt.time | None:
    """Read a wall-clock time written as ``HH:MM`` or ``HH:MM:SS``."""

    if value is None or value == "":
        return None
    if isinstance(value, dt.time):
        return value.replace(tzinfo=None, microsecond=0)
    text = str(value).strip()
    try:
        parsed = dt.time.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"Local time {value!r} must be written as HH:MM or HH:MM:SS.") from error
    if parsed.tzinfo is not None:
        raise ValueError(f"Local time {value!r} must not carry a timezone offset.")
    return parsed.replace(microsecond=0)


def format_local_time(value: dt.time | str | None) -> str | None:
    """Write a wall-clock time as the stored ``HH:MM:SS`` text."""

    parsed = parse_local_time(value)
    return None if parsed is None else parsed.strftime("%H:%M:%S")


def normalize_weekdays(value: str) -> str:
    """Validate a seven-character weekday mask, Monday first."""

    text = str(value).strip()
    if len(text) != 7 or set(text) - {"0", "1"}:
        raise ValueError(
            f"weekdays {value!r} must be seven characters of 0 and 1, Monday first."
        )
    return text


@dataclass(frozen=True)
class SessionRule:
    """The regular week of one session, from ``effective_from`` on."""

    session_label: str
    effective_from: dt.date
    weekdays: str
    effective_to: dt.date | None = None
    opens_at_local: dt.time | None = None
    closes_at_local: dt.time | None = None
    open_day_offset: int = 0
    close_day_offset: int = 0
    is_primary: bool = True

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> SessionRule:
        effective_to = row.get("effective_to")
        return cls(
            session_label=str(row.get("session_label") or DEFAULT_SESSION_LABEL),
            effective_from=coerce_local_date(row["effective_from"]),
            effective_to=None if effective_to in (None, "") else coerce_local_date(effective_to),
            weekdays=normalize_weekdays(row["weekdays"]),
            opens_at_local=parse_local_time(row.get("opens_at_local")),
            closes_at_local=parse_local_time(row.get("closes_at_local")),
            open_day_offset=int(row.get("open_day_offset") or 0),
            close_day_offset=int(row.get("close_day_offset") or 0),
            is_primary=bool(row.get("is_primary", True)),
        )

    def covers(self, local_date: dt.date) -> bool:
        if local_date < self.effective_from:
            return False
        return self.effective_to is None or local_date <= self.effective_to

    def runs_on(self, local_date: dt.date) -> bool:
        return self.weekdays[local_date.weekday()] == "1"


@dataclass(frozen=True)
class CalendarExceptionEntry:
    """One dated departure from the rules."""

    local_date: dt.date
    exception_type: str
    session_label: str = WHOLE_DAY
    opens_at_local: dt.time | None = None
    closes_at_local: dt.time | None = None
    name: str | None = None
    source: str = USER_SOURCE

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> CalendarExceptionEntry:
        exception_type = str(row["exception_type"]).strip().upper()
        if exception_type not in EXCEPTION_TYPES:
            raise ValueError(
                f"exception_type {row['exception_type']!r} must be one of "
                f"{', '.join(EXCEPTION_TYPES)}."
            )
        return cls(
            local_date=coerce_local_date(row["local_date"]),
            exception_type=exception_type,
            session_label=str(row.get("session_label") or WHOLE_DAY),
            opens_at_local=parse_local_time(row.get("opens_at_local")),
            closes_at_local=parse_local_time(row.get("closes_at_local")),
            name=row.get("name") or None,
            source=str(row.get("source") or USER_SOURCE),
        )


@dataclass(frozen=True)
class CalendarDefinition:
    """A calendar as stored: timezone, session rules, exceptions and its range."""

    timezone: str = "UTC"
    rules: tuple[SessionRule, ...] = ()
    exceptions: tuple[CalendarExceptionEntry, ...] = ()
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    unique_identifier: str = ""

    @classmethod
    def from_rows(
        cls,
        *,
        timezone: str = "UTC",
        rules: Iterable[Mapping[str, Any]] = (),
        exceptions: Iterable[Mapping[str, Any]] = (),
        valid_from: dt.date | dt.datetime | str | None = None,
        valid_to: dt.date | dt.datetime | str | None = None,
        unique_identifier: str = "",
    ) -> CalendarDefinition:
        return cls(
            timezone=str(timezone or "UTC"),
            rules=tuple(SessionRule.from_row(row) for row in rules),
            exceptions=tuple(CalendarExceptionEntry.from_row(row) for row in exceptions),
            valid_from=None if valid_from in (None, "") else coerce_local_date(valid_from),
            valid_to=None if valid_to in (None, "") else coerce_local_date(valid_to),
            unique_identifier=str(unique_identifier or ""),
        )


@dataclass(frozen=True)
class ComputedSession:
    """One session of one local date, with its UTC open and close."""

    local_date: dt.date
    session_label: str
    opens_at: dt.datetime | None
    closes_at: dt.datetime | None
    timezone: str
    is_primary: bool = True
    is_early_close: bool = False
    is_late_open: bool = False
    opens_at_local: dt.time | None = None
    closes_at_local: dt.time | None = None
    open_day_offset: int = 0
    close_day_offset: int = 0


@dataclass(frozen=True)
class ComputedDate:
    """The business-day facts of one local date."""

    local_date: dt.date
    is_business_day: bool
    is_holiday: bool
    is_weekend: bool
    is_early_close: bool
    holiday_name: str | None = None
    sessions: tuple[ComputedSession, ...] = field(default=(), compare=False)


def ensure_within_range(
    definition: CalendarDefinition,
    start_date: dt.date,
    end_date: dt.date,
) -> None:
    """Refuse a read outside the range the calendar is complete for.

    A null bound is not checked. Without this check every weekday past the last
    known holiday would read as a business day.
    """

    before = definition.valid_from is not None and start_date < definition.valid_from
    after = definition.valid_to is not None and end_date > definition.valid_to
    if not before and not after:
        return
    name = definition.unique_identifier or "calendar"
    first = "the beginning" if definition.valid_from is None else definition.valid_from.isoformat()
    last = "no end" if definition.valid_to is None else definition.valid_to.isoformat()
    raise CalendarRangeError(
        f"Calendar {name!r} is complete from {first} to {last}; "
        f"{start_date.isoformat()} to {end_date.isoformat()} is outside that range."
    )


def compute_sessions(
    definition: CalendarDefinition,
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
    *,
    session_label: str | None = None,
    check_range: bool = True,
) -> list[ComputedSession]:
    """Return the sessions of every local date from ``start_date`` to ``end_date``."""

    start, end = ensure_date_range(start_date, end_date)
    if check_range:
        ensure_within_range(definition, start, end)
    plan = _Plan(definition)
    sessions: list[ComputedSession] = []
    for local_date in iter_local_dates(start, end):
        for session in plan.sessions_on(local_date):
            if session_label in (None, "") or session.session_label == session_label:
                sessions.append(session)
    return sessions


def compute_dates(
    definition: CalendarDefinition,
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
    *,
    check_range: bool = True,
) -> list[ComputedDate]:
    """Return the business-day facts of every local date from ``start_date`` to ``end_date``."""

    start, end = ensure_date_range(start_date, end_date)
    if check_range:
        ensure_within_range(definition, start, end)
    plan = _Plan(definition)
    return [plan.date_facts(local_date) for local_date in iter_local_dates(start, end)]


def is_business_day(
    definition: CalendarDefinition,
    local_date: dt.date | dt.datetime | str,
    *,
    check_range: bool = True,
) -> bool:
    """Whether ``local_date`` has at least one session."""

    day = coerce_local_date(local_date)
    if check_range:
        ensure_within_range(definition, day, day)
    return bool(_Plan(definition).sessions_on(day))


class _Plan:
    """A definition indexed for date-by-date computation."""

    def __init__(self, definition: CalendarDefinition) -> None:
        self.definition = definition
        self.timezone = definition.timezone
        rules_by_label: dict[str, list[SessionRule]] = defaultdict(list)
        for rule in definition.rules:
            rules_by_label[rule.session_label].append(rule)
        # The latest rule that covers a date is the one in force.
        self.rules_by_label = {
            label: sorted(rules, key=lambda rule: rule.effective_from, reverse=True)
            for label, rules in rules_by_label.items()
        }
        exceptions_by_date: dict[dt.date, list[CalendarExceptionEntry]] = defaultdict(list)
        for entry in definition.exceptions:
            exceptions_by_date[entry.local_date].append(entry)
        # A date that has any user row is computed from its user rows alone.
        self.exceptions_by_date = {
            local_date: (
                [entry for entry in entries if entry.source == USER_SOURCE]
                if any(entry.source == USER_SOURCE for entry in entries)
                else entries
            )
            for local_date, entries in exceptions_by_date.items()
        }
        labels = sorted(
            self.rules_by_label,
            key=lambda label: (
                not any(rule.is_primary for rule in self.rules_by_label[label]),
                label,
            ),
        )
        for entry in definition.exceptions:
            if entry.session_label != WHOLE_DAY and entry.session_label not in labels:
                labels.append(entry.session_label)
        self.labels = labels or [DEFAULT_SESSION_LABEL]

    def rule_for(self, label: str, local_date: dt.date) -> SessionRule | None:
        for rule in self.rules_by_label.get(label, ()):
            if rule.covers(local_date):
                return rule
        return None

    def sessions_on(self, local_date: dt.date) -> list[ComputedSession]:
        entries = self.exceptions_by_date.get(local_date, ())
        sessions: list[ComputedSession] = []
        for label in self.labels:
            session = self._session(label, local_date, entries)
            if session is not None:
                sessions.append(session)
        return sessions

    def _session(
        self,
        label: str,
        local_date: dt.date,
        entries: Iterable[CalendarExceptionEntry],
    ) -> ComputedSession | None:
        rule = self.rule_for(label, local_date)
        mine = [entry for entry in entries if entry.session_label in (WHOLE_DAY, label)]
        if any(entry.exception_type == EXCEPTION_CLOSED for entry in mine):
            return None
        scheduled = rule is not None and rule.runs_on(local_date)
        opened = [entry for entry in mine if entry.exception_type == EXCEPTION_OPEN]
        if not scheduled and not opened:
            return None

        regular_open = rule.opens_at_local if rule is not None else None
        regular_close = rule.closes_at_local if rule is not None else None
        opens, closes = regular_open, regular_close
        for entry in opened:
            opens = entry.opens_at_local or opens
            closes = entry.closes_at_local or closes
        for entry in mine:
            if entry.exception_type == EXCEPTION_LATE_OPEN and entry.opens_at_local:
                opens = entry.opens_at_local
            elif entry.exception_type == EXCEPTION_EARLY_CLOSE and entry.closes_at_local:
                closes = entry.closes_at_local

        open_offset = rule.open_day_offset if rule is not None else 0
        close_offset = rule.close_day_offset if rule is not None else 0
        return ComputedSession(
            local_date=local_date,
            session_label=label,
            opens_at=_utc_instant(local_date, opens, open_offset, self.timezone),
            closes_at=_utc_instant(local_date, closes, close_offset, self.timezone),
            timezone=self.timezone,
            is_primary=rule.is_primary if rule is not None else True,
            is_early_close=_is_earlier(closes, regular_close),
            is_late_open=_is_earlier(regular_open, opens),
            opens_at_local=opens,
            closes_at_local=closes,
            open_day_offset=open_offset,
            close_day_offset=close_offset,
        )

    def date_facts(self, local_date: dt.date) -> ComputedDate:
        sessions = tuple(self.sessions_on(local_date))
        covering = [
            rule
            for label in self.rules_by_label
            if (rule := self.rule_for(label, local_date)) is not None
        ]
        scheduled = any(rule.runs_on(local_date) for rule in covering)
        # A weekend is a weekday no rule runs on. A date no rule covers, such as one
        # before an exchange opened, is neither a weekend nor a holiday.
        is_weekend = bool(covering) and not scheduled
        is_business_day = bool(sessions)
        entries = self.exceptions_by_date.get(local_date, ())
        named = sorted(
            (entry for entry in entries if entry.name),
            key=lambda entry: entry.exception_type != EXCEPTION_CLOSED,
        )
        return ComputedDate(
            local_date=local_date,
            is_business_day=is_business_day,
            is_holiday=scheduled and not is_business_day,
            is_weekend=is_weekend,
            is_early_close=any(
                session.is_early_close for session in sessions if session.is_primary
            ),
            holiday_name=named[0].name if named else None,
            sessions=sessions,
        )


def _is_earlier(first: dt.time | None, second: dt.time | None) -> bool:
    return first is not None and second is not None and first < second


@lru_cache(maxsize=256)
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def _utc_instant(
    local_date: dt.date,
    local_time: dt.time | None,
    day_offset: int,
    timezone: str,
) -> dt.datetime | None:
    if local_time is None:
        return None
    local = dt.datetime.combine(
        local_date + dt.timedelta(days=day_offset),
        local_time,
        tzinfo=_zone(timezone),
    )
    return local.astimezone(dt.UTC)


__all__ = [
    "DEFAULT_SESSION_LABEL",
    "EXCEPTION_CLOSED",
    "EXCEPTION_EARLY_CLOSE",
    "EXCEPTION_LATE_OPEN",
    "EXCEPTION_OPEN",
    "EXCEPTION_TYPES",
    "USER_SOURCE",
    "WHOLE_DAY",
    "CalendarDefinition",
    "CalendarExceptionEntry",
    "CalendarRangeError",
    "ComputedDate",
    "ComputedSession",
    "SessionRule",
    "compute_dates",
    "compute_sessions",
    "ensure_within_range",
    "format_local_time",
    "is_business_day",
    "normalize_weekdays",
    "parse_local_time",
]
