from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarExceptionTable, CalendarTable
from msm.services.calendars.computation import (
    EXCEPTION_CLOSED,
    EXCEPTION_EARLY_CLOSE,
    EXCEPTION_LATE_OPEN,
    EXCEPTION_OPEN,
    USER_SOURCE,
    WHOLE_DAY,
    format_local_time,
)

from ._validation import normalize_blankable_token, normalize_upper_token, validate_payload


class CalendarExceptionType(str, Enum):
    CLOSED = EXCEPTION_CLOSED
    EARLY_CLOSE = EXCEPTION_EARLY_CLOSE
    LATE_OPEN = EXCEPTION_LATE_OPEN
    OPEN = EXCEPTION_OPEN


class CalendarException(MarketsMetaTableRow):
    """One dated departure from a calendar's session rules (ADR 0055).

    A row written here has ``source="user"``. A date that has any ``user`` row is
    computed from its ``user`` rows alone, and an adapter never changes them.
    """

    __table__: ClassVar[type[CalendarExceptionTable]] = CalendarExceptionTable
    __required_tables__: ClassVar[list[type[Any]]] = [CalendarTable, CalendarExceptionTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "calendar_uid",
        "local_date",
        "session_label",
        "exception_type",
        "source",
    )

    calendar_uid: uuid.UUID
    local_date: dt.date
    session_label: str = WHOLE_DAY
    exception_type: str
    opens_at_local: str | None = None
    closes_at_local: str | None = None
    name: str | None = None
    source: str = USER_SOURCE
    metadata_json: dict[str, Any] | None = None

    @field_validator("session_label", mode="before")
    @classmethod
    def _normalize_session_label(cls, value: str | None) -> str:
        return normalize_blankable_token(value)

    @classmethod
    def create(
        cls,
        payload: CalendarExceptionCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarException:
        from msm.services.calendars import create_calendar_exception_record

        validated = validate_payload(CalendarExceptionCreate, payload, kwargs)
        return cls.model_validate(
            create_calendar_exception_record(cls._active_context(), **validated.model_dump())
        )

    @classmethod
    def upsert(
        cls,
        payload: CalendarExceptionUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarException:
        validated = validate_payload(CalendarExceptionUpsert, payload, kwargs)
        return cls.upsert_many([validated])[0]

    @classmethod
    def upsert_many(
        cls,
        payloads: Sequence[BaseModel | Mapping[str, Any]],
    ) -> list[CalendarException]:
        """Upsert user exceptions; rows of one call may belong to several calendars."""

        from msm.services.calendars import bulk_upsert_calendar_exception_records

        validated = [validate_payload(CalendarExceptionUpsert, payload, {}) for payload in payloads]
        by_calendar: dict[str, list[dict[str, Any]]] = {}
        for item in validated:
            by_calendar.setdefault(str(item.calendar_uid), []).append(item.model_dump())
        rows: list[CalendarException] = []
        for calendar_uid, items in by_calendar.items():
            rows.extend(
                cls.model_validate(row)
                for row in bulk_upsert_calendar_exception_records(
                    cls._active_context(), calendar_uid=calendar_uid, rows=items
                )
            )
        return rows

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarExceptionUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarException:
        validated = validate_payload(CalendarExceptionUpdate, payload, kwargs)
        stored = cls.get_by_uid(uid)
        if stored is None:
            raise LookupError(f"CalendarException {uid} was not found.")
        validate_exception_update(stored.model_dump(), validated.model_dump(exclude_unset=True))
        return super().update(uid, validated)


    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Delete one exception.

        Nothing references an exception, so the row is deleted with no other check.
        Deleting a user's exception restores what the remaining rows say for its date.
        """

        return super().delete(uid)


class _ExceptionValues(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    @field_validator("opens_at_local", "closes_at_local", mode="before", check_fields=False)
    @classmethod
    def _normalize_local_time(cls, value: dt.time | str | None) -> str | None:
        return format_local_time(value)


class CalendarExceptionCreate(_ExceptionValues):
    """Payload for creating one calendar exception. The row's source is ``user``."""

    calendar_uid: uuid.UUID | str
    local_date: dt.date
    session_label: str = Field(default=WHOLE_DAY, max_length=64)
    exception_type: CalendarExceptionType | str
    opens_at_local: str | None = None
    closes_at_local: str | None = None
    name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("session_label", mode="before")
    @classmethod
    def _normalize_session_label(cls, value: str | None) -> str:
        return normalize_blankable_token(value)

    @field_validator("exception_type", mode="before")
    @classmethod
    def _normalize_exception_type(cls, value: str | CalendarExceptionType) -> str:
        if isinstance(value, CalendarExceptionType):
            return value.value
        normalized = normalize_upper_token(str(value), field_name="exception_type")
        return CalendarExceptionType(normalized).value

    @model_validator(mode="after")
    def _validate_times(self) -> CalendarExceptionCreate:
        if self.exception_type == EXCEPTION_CLOSED:
            if self.opens_at_local is not None or self.closes_at_local is not None:
                raise ValueError("A CLOSED exception has no open or close time.")
        elif self.exception_type == EXCEPTION_EARLY_CLOSE:
            if self.closes_at_local is None or self.opens_at_local is not None:
                raise ValueError("An EARLY_CLOSE exception sets closes_at_local only.")
        elif self.exception_type == EXCEPTION_LATE_OPEN:
            if self.opens_at_local is None or self.closes_at_local is not None:
                raise ValueError("A LATE_OPEN exception sets opens_at_local only.")
        return self


class CalendarExceptionUpsert(CalendarExceptionCreate):
    """Payload for inserting or updating a user exception by calendar, date, session and type."""


class CalendarExceptionUpdate(_ExceptionValues):
    """Payload for updating mutable calendar exception fields."""

    opens_at_local: str | None = None
    closes_at_local: str | None = None
    name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


_EXCEPTION_VALUE_FIELDS = (
    "calendar_uid",
    "local_date",
    "session_label",
    "exception_type",
    "opens_at_local",
    "closes_at_local",
    "name",
    "metadata_json",
)


def validate_exception_update(stored: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
    """Check an update as a new exception is checked: the stored row with the changes applied.

    Without it an update could put a close time on a ``CLOSED`` exception, or take
    the close time off an ``EARLY_CLOSE`` one.
    """

    merged = {**stored, **changes}
    CalendarExceptionCreate(**{key: merged.get(key) for key in _EXCEPTION_VALUE_FIELDS})


__all__ = [
    "CalendarException",
    "CalendarExceptionCreate",
    "CalendarExceptionType",
    "CalendarExceptionUpdate",
    "CalendarExceptionUpsert",
    "validate_exception_update",
]
