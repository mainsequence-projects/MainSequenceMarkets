from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarEventTable, CalendarTable

from ._validation import (
    ensure_utc_datetime,
    normalize_blankable_token,
    normalize_upper_token,
    validate_payload,
)


class CalendarEvent(MarketsMetaTableRow):
    """Typed row for one persisted calendar-level event."""

    __table__: ClassVar[type[CalendarEventTable]] = CalendarEventTable
    __required_tables__: ClassVar[list[type[Any]]] = [CalendarTable, CalendarEventTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "calendar_uid",
        "event_date",
        "event_type",
        "event_label",
        "target_type",
        "target_identifier",
    )

    calendar_uid: uuid.UUID
    event_date: dt.date | None = None
    event_time: dt.datetime | None = None
    event_type: str
    event_label: str = ""
    target_type: str = ""
    target_uid: uuid.UUID | None = None
    target_identifier: str = ""
    metadata_json: dict[str, Any] | None = None

    @field_validator("event_type", mode="before")
    @classmethod
    def _normalize_event_type(cls, value: str) -> str:
        return normalize_upper_token(str(value), field_name="event_type")

    @field_validator("event_label", "target_type", "target_identifier", mode="before")
    @classmethod
    def _normalize_blankable(cls, value: str | None) -> str:
        return normalize_blankable_token(value)

    @field_validator("event_time", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)

    @classmethod
    def create(
        cls,
        payload: CalendarEventCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarEvent:
        return super().create(validate_payload(CalendarEventCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: CalendarEventUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarEvent:
        return super().upsert(validate_payload(CalendarEventUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarEventUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarEvent:
        return super().update(uid, validate_payload(CalendarEventUpdate, payload, kwargs))


class CalendarEventCreate(BaseModel):
    """Payload for creating one calendar-level event row."""

    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str
    event_date: dt.date | None = None
    event_time: dt.datetime | str | None = None
    event_type: str = Field(min_length=1, max_length=64)
    event_label: str | None = Field(default="", max_length=255)
    target_type: str | None = Field(default="", max_length=64)
    target_uid: uuid.UUID | str | None = None
    target_identifier: str | None = Field(default="", max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("event_type", mode="before")
    @classmethod
    def _normalize_event_type(cls, value: str) -> str:
        return normalize_upper_token(str(value), field_name="event_type")

    @field_validator("event_label", "target_type", "target_identifier", mode="before")
    @classmethod
    def _normalize_blankable(cls, value: str | None) -> str:
        return normalize_blankable_token(value)

    @field_validator("event_time", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)


class CalendarEventUpsert(CalendarEventCreate):
    """Payload for inserting or updating an event by calendar and event key."""

    @model_validator(mode="after")
    def _require_event_date_for_upsert(self) -> CalendarEventUpsert:
        if self.event_date is None:
            raise ValueError("event_date is required for CalendarEvent.upsert(...).")
        return self


class CalendarEventUpdate(BaseModel):
    """Payload for updating mutable calendar event fields."""

    model_config = ConfigDict(extra="forbid")

    event_time: dt.datetime | str | None = None
    target_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("event_time", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)


__all__ = [
    "CalendarEvent",
    "CalendarEventCreate",
    "CalendarEventUpdate",
    "CalendarEventUpsert",
]
