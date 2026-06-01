from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarTable


class Calendar(MarketsMetaTableRow):
    """Typed named market calendar row."""

    __table__: ClassVar[type[CalendarTable]] = CalendarTable
    __required_tables__: ClassVar[list[type[CalendarTable]]] = [CalendarTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("name",)

    name: str
    calendar_dates: dict[str, Any] | list[Any] | None = None
    metadata_json: dict[str, Any] | None = None


class CalendarCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    calendar_dates: dict[str, Any] | list[Any] | None = None
    metadata_json: dict[str, Any] | None = None


class CalendarUpsert(CalendarCreate):
    """Payload for inserting or updating a calendar row."""


class CalendarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_dates: dict[str, Any] | list[Any] | None = None
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "Calendar",
    "CalendarCreate",
    "CalendarUpdate",
    "CalendarUpsert",
]
