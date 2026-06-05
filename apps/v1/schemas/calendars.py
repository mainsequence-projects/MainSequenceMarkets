from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _calendar_contracts():
    prepare_apps_v1_import_namespace()
    from msm.api.calendars import (
        Calendar,
        CalendarCreate,
        CalendarDate,
        CalendarDateUpdate,
        CalendarEvent,
        CalendarEventUpdate,
        CalendarSession,
        CalendarSessionUpdate,
        CalendarUpdate,
    )

    return {
        "Calendar": Calendar,
        "CalendarCreate": CalendarCreate,
        "CalendarUpdate": CalendarUpdate,
        "CalendarDate": CalendarDate,
        "CalendarDateUpdate": CalendarDateUpdate,
        "CalendarSession": CalendarSession,
        "CalendarSessionUpdate": CalendarSessionUpdate,
        "CalendarEvent": CalendarEvent,
        "CalendarEventUpdate": CalendarEventUpdate,
    }


_CONTRACTS = _calendar_contracts()

Calendar = _CONTRACTS["Calendar"]
CalendarCreate = _CONTRACTS["CalendarCreate"]
CalendarUpdate = _CONTRACTS["CalendarUpdate"]
CalendarDate = _CONTRACTS["CalendarDate"]
CalendarDateUpdate = _CONTRACTS["CalendarDateUpdate"]
CalendarSession = _CONTRACTS["CalendarSession"]
CalendarSessionUpdate = _CONTRACTS["CalendarSessionUpdate"]
CalendarEvent = _CONTRACTS["CalendarEvent"]
CalendarEventUpdate = _CONTRACTS["CalendarEventUpdate"]


class CalendarDateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_date: dt.date
    is_business_day: bool = False
    is_holiday: bool = False
    is_weekend: bool = False
    is_early_close: bool = False
    holiday_name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class BulkUpsertCalendarDatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CalendarDateCreateRequest] = Field(
        default_factory=list,
        description="Calendar date rows to upsert under the path calendar uid.",
    )


class CalendarSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_date: dt.date
    session_label: str = Field(min_length=1, max_length=64)
    opens_at: dt.datetime | str | None = None
    closes_at: dt.datetime | str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    is_primary: bool = True
    metadata_json: dict[str, Any] | None = None


class BulkUpsertCalendarSessionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CalendarSessionCreateRequest] = Field(
        default_factory=list,
        description="Calendar session rows to upsert under the path calendar uid.",
    )


class CalendarEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_date: dt.date | None = None
    event_time: dt.datetime | str | None = None
    event_type: str = Field(min_length=1, max_length=64)
    event_label: str | None = Field(default="", max_length=255)
    target_type: str | None = Field(default="", max_length=64)
    target_uid: UUID | str | None = None
    target_identifier: str | None = Field(default="", max_length=255)
    metadata_json: dict[str, Any] | None = None


class CalendarEventUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_date: dt.date
    event_time: dt.datetime | str | None = None
    event_type: str = Field(min_length=1, max_length=64)
    event_label: str | None = Field(default="", max_length=255)
    target_type: str | None = Field(default="", max_length=64)
    target_uid: UUID | str | None = None
    target_identifier: str | None = Field(default="", max_length=255)
    metadata_json: dict[str, Any] | None = None


class BulkUpsertCalendarEventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CalendarEventUpsertRequest] = Field(
        default_factory=list,
        description="Calendar event rows to upsert under the path calendar uid.",
    )


__all__ = [
    "BulkUpsertCalendarDatesRequest",
    "BulkUpsertCalendarEventsRequest",
    "BulkUpsertCalendarSessionsRequest",
    "Calendar",
    "CalendarCreate",
    "CalendarDate",
    "CalendarDateCreateRequest",
    "CalendarDateUpdate",
    "CalendarEvent",
    "CalendarEventCreateRequest",
    "CalendarEventUpdate",
    "CalendarEventUpsertRequest",
    "CalendarSession",
    "CalendarSessionCreateRequest",
    "CalendarSessionUpdate",
    "CalendarUpdate",
]
