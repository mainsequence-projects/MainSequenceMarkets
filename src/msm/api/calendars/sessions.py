from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarSessionTable, CalendarTable

from ._validation import ensure_utc_datetime, validate_payload


class CalendarSession(MarketsMetaTableRow):
    """Typed row for one persisted calendar session."""

    __table__: ClassVar[type[CalendarSessionTable]] = CalendarSessionTable
    __required_tables__: ClassVar[list[type[Any]]] = [CalendarTable, CalendarSessionTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "calendar_uid",
        "local_date",
        "session_label",
    )

    calendar_uid: uuid.UUID
    local_date: dt.date
    session_label: str
    opens_at: dt.datetime | None = None
    closes_at: dt.datetime | None = None
    timezone: str = "UTC"
    is_primary: bool = True
    metadata_json: dict[str, Any] | None = None

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)

    @classmethod
    def create(
        cls,
        payload: CalendarSessionCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSession:
        return super().create(validate_payload(CalendarSessionCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: CalendarSessionUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSession:
        return super().upsert(validate_payload(CalendarSessionUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarSessionUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSession:
        return super().update(uid, validate_payload(CalendarSessionUpdate, payload, kwargs))


class CalendarSessionCreate(BaseModel):
    """Payload for creating one calendar session row."""

    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str
    local_date: dt.date
    session_label: str = Field(min_length=1, max_length=64)
    opens_at: dt.datetime | str | None = None
    closes_at: dt.datetime | str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    is_primary: bool = True
    metadata_json: dict[str, Any] | None = None

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _validate_window(self) -> CalendarSessionCreate:
        if self.opens_at is not None and self.closes_at is not None:
            if self.closes_at < self.opens_at:
                raise ValueError("closes_at must be greater than or equal to opens_at.")
        return self


class CalendarSessionUpsert(CalendarSessionCreate):
    """Payload for inserting or updating a session by calendar, date, and label."""


class CalendarSessionUpdate(BaseModel):
    """Payload for updating mutable calendar session fields."""

    model_config = ConfigDict(extra="forbid")

    opens_at: dt.datetime | str | None = None
    closes_at: dt.datetime | str | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    is_primary: bool | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: dt.datetime | str | None) -> dt.datetime | None:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def _validate_window(self) -> CalendarSessionUpdate:
        if self.opens_at is not None and self.closes_at is not None:
            if self.closes_at < self.opens_at:
                raise ValueError("closes_at must be greater than or equal to opens_at.")
        return self


__all__ = [
    "CalendarSession",
    "CalendarSessionCreate",
    "CalendarSessionUpdate",
    "CalendarSessionUpsert",
]
