from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm.services.calendars.computation import format_local_time, normalize_weekdays


def _calendar_contracts():
    from msm.api.calendars import (
        Calendar,
        CalendarCreate,
        CalendarException,
        CalendarExceptionType,
        CalendarExceptionUpdate,
        CalendarSessionRule,
        CalendarSessionRuleUpdate,
        CalendarUpdate,
        ComputedCalendarDate,
        ComputedCalendarSession,
    )

    return {
        "Calendar": Calendar,
        "CalendarCreate": CalendarCreate,
        "CalendarUpdate": CalendarUpdate,
        "CalendarSessionRule": CalendarSessionRule,
        "CalendarSessionRuleUpdate": CalendarSessionRuleUpdate,
        "CalendarException": CalendarException,
        "CalendarExceptionType": CalendarExceptionType,
        "CalendarExceptionUpdate": CalendarExceptionUpdate,
        "ComputedCalendarDate": ComputedCalendarDate,
        "ComputedCalendarSession": ComputedCalendarSession,
    }


_CONTRACTS = _calendar_contracts()

Calendar = _CONTRACTS["Calendar"]
CalendarCreate = _CONTRACTS["CalendarCreate"]
CalendarUpdate = _CONTRACTS["CalendarUpdate"]
CalendarSessionRule = _CONTRACTS["CalendarSessionRule"]
CalendarSessionRuleUpdate = _CONTRACTS["CalendarSessionRuleUpdate"]
CalendarException = _CONTRACTS["CalendarException"]
CalendarExceptionType = _CONTRACTS["CalendarExceptionType"]
CalendarExceptionUpdate = _CONTRACTS["CalendarExceptionUpdate"]


class ComputedCalendarDate(_CONTRACTS["ComputedCalendarDate"]):
    """The business-day facts of one local date of a calendar.

    It is computed from the calendar's session rules and exceptions. Nothing is
    stored per date, so it has no uid.
    """

    calendar_uid: UUID


class ComputedCalendarSession(_CONTRACTS["ComputedCalendarSession"]):
    """One session of one local date of a calendar, with its UTC open and close.

    It is computed from the calendar's session rules and exceptions. Nothing is
    stored per session, so it has no uid.
    """

    calendar_uid: UUID


class _LocalTimes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("opens_at_local", "closes_at_local", mode="before", check_fields=False)
    @classmethod
    def _normalize_local_time(cls, value: Any) -> Any:
        return format_local_time(value)


class CalendarSessionRuleCreateRequest(_LocalTimes):
    session_label: str = Field(default="regular", min_length=1, max_length=64)
    effective_from: dt.date = Field(description="First local date the rule applies to.")
    effective_to: dt.date | None = Field(
        default=None,
        description="Last local date the rule applies to. Null while the rule is current.",
    )
    weekdays: str = Field(
        description="Seven characters of 0 and 1, Monday first. `1111100` is Monday to Friday.",
    )
    opens_at_local: str | None = Field(
        default=None,
        description=(
            "Wall-clock open in the calendar's timezone, as `HH:MM` or `HH:MM:SS`. "
            "Null for a date-only calendar."
        ),
    )
    closes_at_local: str | None = Field(
        default=None,
        description=(
            "Wall-clock close in the calendar's timezone, as `HH:MM` or `HH:MM:SS`. "
            "Null for a date-only calendar."
        ),
    )
    open_day_offset: int = Field(
        default=0,
        ge=-1,
        le=1,
        description=(
            "Days from the session's local date to its open. `-1` opens the evening before."
        ),
    )
    close_day_offset: int = Field(
        default=0,
        ge=-1,
        le=1,
        description=(
            "Days from the session's local date to its close. `1` closes at the next midnight."
        ),
    )
    is_primary: bool = True

    @field_validator("weekdays", mode="before")
    @classmethod
    def _normalize_weekdays(cls, value: Any) -> Any:
        return normalize_weekdays(value)


class BulkUpsertCalendarSessionRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CalendarSessionRuleCreateRequest] = Field(
        default_factory=list,
        description="Session rule rows to upsert under the path calendar uid.",
    )


class CalendarExceptionCreateRequest(_LocalTimes):
    """One dated departure from the session rules. The stored row has `source="user"`."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    local_date: dt.date = Field(description="The calendar-local date the exception applies to.")
    session_label: str = Field(
        default="",
        max_length=64,
        description="The session the exception changes. Empty for the whole day.",
    )
    exception_type: CalendarExceptionType  # type: ignore[valid-type]
    opens_at_local: str | None = Field(
        default=None,
        description="Wall-clock open that replaces the rule's, as `HH:MM` or `HH:MM:SS`.",
    )
    closes_at_local: str | None = Field(
        default=None,
        description="Wall-clock close that replaces the rule's, as `HH:MM` or `HH:MM:SS`.",
    )
    name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("exception_type", mode="before")
    @classmethod
    def _normalize_exception_type(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class BulkUpsertCalendarExceptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CalendarExceptionCreateRequest] = Field(
        default_factory=list,
        description="Calendar exception rows to upsert under the path calendar uid.",
    )


__all__ = [
    "BulkUpsertCalendarExceptionsRequest",
    "BulkUpsertCalendarSessionRulesRequest",
    "Calendar",
    "CalendarCreate",
    "CalendarException",
    "CalendarExceptionCreateRequest",
    "CalendarExceptionType",
    "CalendarExceptionUpdate",
    "CalendarSessionRule",
    "CalendarSessionRuleCreateRequest",
    "CalendarSessionRuleUpdate",
    "CalendarUpdate",
    "ComputedCalendarDate",
    "ComputedCalendarSession",
]
