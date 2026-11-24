from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarExceptionTable, CalendarSessionRuleTable, CalendarTable

from ._validation import normalize_upper_token, validate_payload
from .computed import ComputedCalendarDate, ComputedCalendarSession

CALENDAR_DEFINITION_TABLES = [CalendarTable, CalendarSessionRuleTable, CalendarExceptionTable]
"""Tables a calendar's dates and sessions are computed from."""


class CalendarType(str, Enum):
    TRADING = "TRADING"
    SETTLEMENT = "SETTLEMENT"
    FIXING = "FIXING"
    BUSINESS = "BUSINESS"
    HOLIDAY = "HOLIDAY"
    EVENT = "EVENT"
    CUSTOM = "CUSTOM"


@dataclass
class _CalendarReads:
    """What one ``calendar_reads`` block read: rows by uid and identifier, and definitions."""

    rows: dict[str, Calendar] = field(default_factory=dict)
    uids: dict[str, str | None] = field(default_factory=dict)
    definitions: dict[str, Any] = field(default_factory=dict)

    def keep(self, calendar: Calendar) -> Calendar:
        self.rows[str(calendar.uid)] = calendar
        self.uids[calendar.unique_identifier] = str(calendar.uid)
        return calendar


_reads: ContextVar[_CalendarReads | None] = ContextVar("msm_calendar_reads", default=None)


@contextmanager
def calendar_reads() -> Iterator[None]:
    """Read each calendar's row, session rules and exceptions at most once in the block.

    For a run whose nodes look up and compute the same calendars (issue #137). Inside the
    block, ``Calendar.get_by_unique_identifier``, ``Calendar.get_by_uid`` and
    ``AssetCalendar.calendars_of`` keep the rows they read, and ``sessions``, ``dates``
    and ``is_business_day`` compute from one definition per calendar: its rules and every
    exception it has, read the first time it is needed (in one read of up to 9,000 rows).
    A calendar written inside the block is not read again. Under the ``remote`` backend
    each call is still one request. A block inside another shares its reads.
    """

    if _reads.get() is not None:
        yield
        return
    token = _reads.set(_CalendarReads())
    try:
        yield
    finally:
        _reads.reset(token)


def keep_calendar_read(calendar: Calendar | None) -> None:
    """Keep ``calendar`` for the ``calendar_reads`` block in force, if any."""

    reads = _reads.get()
    if reads is not None and calendar is not None:
        reads.keep(calendar)


class Calendar(MarketsMetaTableRow):
    """Typed calendar identity row."""

    __table__: ClassVar[type[CalendarTable]] = CalendarTable
    __required_tables__: ClassVar[list[type[CalendarTable]]] = [CalendarTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    calendar_type: str
    timezone: str = "UTC"
    source: str | None = None
    source_identifier: str | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("calendar_type", mode="before")
    @classmethod
    def _normalize_calendar_type(cls, value: str | CalendarType) -> str:
        if isinstance(value, CalendarType):
            return value.value
        return normalize_upper_token(str(value), field_name="calendar_type")

    @classmethod
    def create(
        cls,
        payload: CalendarCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Calendar:
        return super().create(validate_payload(CalendarCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: CalendarUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Calendar:
        return super().upsert(validate_payload(CalendarUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Calendar:
        return super().update(uid, validate_payload(CalendarUpdate, payload, kwargs))

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> Calendar | None:
        """Return one calendar by UID; inside ``calendar_reads`` each is read once."""

        reads = _reads.get()
        if reads is not None and str(uid) in reads.rows:
            return reads.rows[str(uid)]
        calendar = super().get_by_uid(uid)
        keep_calendar_read(calendar)
        return calendar

    @classmethod
    def get_by_unique_identifier(cls, unique_identifier: str) -> Calendar | None:
        """Return one calendar by ``unique_identifier``; inside ``calendar_reads`` once."""

        reads = _reads.get()
        if reads is not None and unique_identifier in reads.uids:
            uid = reads.uids[unique_identifier]
            return None if uid is None else reads.rows[uid]
        calendar = super().get_by_unique_identifier(unique_identifier)
        if reads is not None and calendar is None:
            reads.uids[unique_identifier] = None
        keep_calendar_read(calendar)
        return calendar

    @classmethod
    def create_from_pandas_calendar(
        cls,
        source_identifier: str,
        unique_identifier: str | None = None,
        *,
        display_name: str | None = None,
        calendar_type: CalendarType | str | None = None,
        timezone: str | None = None,
        session_label: str | None = None,
        valid_from: dt.date | dt.datetime | str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> Calendar:
        """Create a calendar from pandas-market-calendars, or write an existing one again.

        ``source_identifier`` is the library's calendar and ``unique_identifier``
        the name of the stored one, which defaults to the library's name:
        ``create_from_pandas_calendar("NYSE", "CustomNYSE")`` stores NYSE as
        ``CustomNYSE``. Several stored calendars can come from one library calendar.

        The header, the session rules and the exceptions are written in one
        transaction, to the last date the library can answer for, so nothing has
        to be extended as time passes. ``valid_from`` defaults to 1990-01-01.

        Calling it again on a stored calendar writes what the installed library
        knows now: the library's own exceptions are replaced and every ``user``
        exception is kept (ADR 0055).
        """

        from msm.bootstrap import resolve_runtime
        from msm.services.calendars import sync_pandas_market_calendar

        runtime = resolve_runtime(models=CALENDAR_DEFINITION_TABLES, row_model_name=cls.__name__)
        if isinstance(calendar_type, CalendarType):
            calendar_type = calendar_type.value
        result = sync_pandas_market_calendar(
            runtime.context,
            source_identifier=source_identifier,
            unique_identifier=unique_identifier,
            display_name=display_name,
            calendar_type=calendar_type,
            timezone=timezone,
            session_label=session_label,
            valid_from=valid_from,
            metadata_json=metadata_json,
        )
        return cls.model_validate(result.calendar)

    @classmethod
    def sessions(
        cls,
        calendar_uid: uuid.UUID | str,
        start_date: dt.date,
        end_date: dt.date,
        *,
        session_label: str | None = None,
    ) -> list[ComputedCalendarSession]:
        """The sessions of every local date from ``start_date`` to ``end_date``.

        Computed from the calendar's rules and exceptions. A date outside the
        calendar's ``valid_from``..``valid_to`` raises ``CalendarRangeError``.
        """

        from msm.services.calendars import compute_sessions

        definition = cls._definition(calendar_uid, start_date, end_date)
        return [
            ComputedCalendarSession.from_computed(session)
            for session in compute_sessions(
                definition, start_date, end_date, session_label=session_label
            )
        ]

    @classmethod
    def dates(
        cls,
        calendar_uid: uuid.UUID | str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[ComputedCalendarDate]:
        """The business-day facts of every local date from ``start_date`` to ``end_date``."""

        from msm.services.calendars import compute_dates

        definition = cls._definition(calendar_uid, start_date, end_date)
        return [
            ComputedCalendarDate.from_computed(date)
            for date in compute_dates(definition, start_date, end_date)
        ]

    @classmethod
    def is_business_day(cls, calendar_uid: uuid.UUID | str, local_date: dt.date) -> bool:
        """Whether ``local_date`` has at least one session on this calendar."""

        from msm.services.calendars import is_business_day

        return is_business_day(cls._definition(calendar_uid, local_date, local_date), local_date)

    @classmethod
    def _definition(
        cls,
        calendar_uid: uuid.UUID | str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> Any:
        """The calendar's rules and exceptions from ``start_date`` to ``end_date``.

        Inside ``calendar_reads`` it is the calendar's whole definition, read once.
        """

        from msm.bootstrap import resolve_runtime
        from msm.services.calendars import (
            coerce_local_date,
            get_calendar_record,
            load_calendar_definition,
        )

        runtime = resolve_runtime(models=CALENDAR_DEFINITION_TABLES, row_model_name=cls.__name__)
        reads = _reads.get()
        if reads is None:
            calendar = get_calendar_record(runtime.context, uid=str(calendar_uid))
            if calendar is None:
                raise LookupError(f"Calendar {calendar_uid} was not found.")
            return load_calendar_definition(
                runtime.context,
                calendar=calendar,
                start_date=coerce_local_date(start_date),
                end_date=coerce_local_date(end_date),
            )
        key = str(calendar_uid)
        if key not in reads.definitions:
            row = cls.get_by_uid(key)
            if row is None:
                raise LookupError(f"Calendar {calendar_uid} was not found.")
            reads.definitions[key] = load_calendar_definition(
                runtime.context, calendar={**row.model_dump(), "uid": key}
            )
        return reads.definitions[key]


class CalendarCreate(BaseModel):
    """Payload for creating a calendar identity row."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    calendar_type: CalendarType | str
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    source: str | None = Field(default=None, max_length=128)
    source_identifier: str | None = Field(default=None, max_length=255)
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("calendar_type", mode="before")
    @classmethod
    def _normalize_calendar_type(cls, value: str | CalendarType) -> str:
        if isinstance(value, CalendarType):
            return value.value
        return normalize_upper_token(str(value), field_name="calendar_type")

    @model_validator(mode="after")
    def _validate_horizon(self) -> CalendarCreate:
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must be greater than or equal to valid_from.")
        return self


class CalendarUpsert(CalendarCreate):
    """Payload for inserting or updating a calendar by unique identifier."""


class CalendarUpdate(BaseModel):
    """Payload for updating mutable calendar identity fields."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    calendar_type: CalendarType | str | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    source: str | None = Field(default=None, max_length=128)
    source_identifier: str | None = Field(default=None, max_length=255)
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("calendar_type", mode="before")
    @classmethod
    def _normalize_calendar_type(cls, value: str | CalendarType | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, CalendarType):
            return value.value
        return normalize_upper_token(str(value), field_name="calendar_type")

    @model_validator(mode="after")
    def _validate_horizon(self) -> CalendarUpdate:
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must be greater than or equal to valid_from.")
        return self


__all__ = [
    "CALENDAR_DEFINITION_TABLES",
    "Calendar",
    "calendar_reads",
    "keep_calendar_read",
    "CalendarCreate",
    "CalendarType",
    "CalendarUpdate",
    "CalendarUpsert",
]
