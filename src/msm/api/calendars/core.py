from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarTable

from ._validation import normalize_upper_token, validate_payload


class CalendarType(str, Enum):
    TRADING = "TRADING"
    SETTLEMENT = "SETTLEMENT"
    FIXING = "FIXING"
    BUSINESS = "BUSINESS"
    HOLIDAY = "HOLIDAY"
    EVENT = "EVENT"
    CUSTOM = "CUSTOM"


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
    valid_from: dt.date
    valid_to: dt.date
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


class CalendarCreate(BaseModel):
    """Payload for creating a calendar identity row."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    calendar_type: CalendarType | str
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    source: str | None = Field(default=None, max_length=128)
    source_identifier: str | None = Field(default=None, max_length=255)
    valid_from: dt.date
    valid_to: dt.date
    metadata_json: dict[str, Any] | None = None

    @field_validator("calendar_type", mode="before")
    @classmethod
    def _normalize_calendar_type(cls, value: str | CalendarType) -> str:
        if isinstance(value, CalendarType):
            return value.value
        return normalize_upper_token(str(value), field_name="calendar_type")

    @model_validator(mode="after")
    def _validate_horizon(self) -> CalendarCreate:
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
    "Calendar",
    "CalendarCreate",
    "CalendarType",
    "CalendarUpdate",
    "CalendarUpsert",
]
