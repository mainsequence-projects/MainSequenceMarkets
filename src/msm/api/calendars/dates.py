from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarDateTable, CalendarTable

from ._validation import validate_payload


class CalendarDate(MarketsMetaTableRow):
    """Typed row for one persisted calendar-local date."""

    __table__: ClassVar[type[CalendarDateTable]] = CalendarDateTable
    __required_tables__: ClassVar[list[type[Any]]] = [CalendarTable, CalendarDateTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("calendar_uid", "local_date")

    calendar_uid: uuid.UUID
    local_date: dt.date
    is_business_day: bool = False
    is_holiday: bool = False
    is_weekend: bool = False
    is_early_close: bool = False
    holiday_name: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: CalendarDateCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarDate:
        return super().create(validate_payload(CalendarDateCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: CalendarDateUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarDate:
        return super().upsert(validate_payload(CalendarDateUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarDateUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarDate:
        return super().update(uid, validate_payload(CalendarDateUpdate, payload, kwargs))


class CalendarDateCreate(BaseModel):
    """Payload for creating one calendar-local date row."""

    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str
    local_date: dt.date
    is_business_day: bool = False
    is_holiday: bool = False
    is_weekend: bool = False
    is_early_close: bool = False
    holiday_name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class CalendarDateUpsert(CalendarDateCreate):
    """Payload for inserting or updating one date by calendar and local_date."""


class CalendarDateUpdate(BaseModel):
    """Payload for updating mutable calendar date facts."""

    model_config = ConfigDict(extra="forbid")

    is_business_day: bool | None = None
    is_holiday: bool | None = None
    is_weekend: bool | None = None
    is_early_close: bool | None = None
    holiday_name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "CalendarDate",
    "CalendarDateCreate",
    "CalendarDateUpdate",
    "CalendarDateUpsert",
]
