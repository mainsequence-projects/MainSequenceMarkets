from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarSessionRuleTable, CalendarTable
from msm.services.calendars.computation import (
    DEFAULT_SESSION_LABEL,
    format_local_time,
    normalize_weekdays,
)

from ._validation import validate_payload


class CalendarSessionRule(MarketsMetaTableRow):
    """The regular week of one session of a calendar, from a date on (ADR 0055)."""

    __table__: ClassVar[type[CalendarSessionRuleTable]] = CalendarSessionRuleTable
    __required_tables__: ClassVar[list[type[Any]]] = [CalendarTable, CalendarSessionRuleTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "calendar_uid",
        "session_label",
        "effective_from",
    )

    calendar_uid: uuid.UUID
    session_label: str = DEFAULT_SESSION_LABEL
    effective_from: dt.date
    effective_to: dt.date | None = None
    weekdays: str
    opens_at_local: str | None = None
    closes_at_local: str | None = None
    open_day_offset: int = 0
    close_day_offset: int = 0
    is_primary: bool = True

    @classmethod
    def create(
        cls,
        payload: CalendarSessionRuleCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSessionRule:
        return super().create(validate_payload(CalendarSessionRuleCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: CalendarSessionRuleUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSessionRule:
        return super().upsert(validate_payload(CalendarSessionRuleUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CalendarSessionRuleUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CalendarSessionRule:
        validated = validate_payload(CalendarSessionRuleUpdate, payload, kwargs)
        stored = cls.get_by_uid(uid)
        if stored is None:
            raise LookupError(f"CalendarSessionRule {uid} was not found.")
        validate_rule_update(stored.model_dump(), validated.model_dump(exclude_unset=True))
        return super().update(uid, validated)


    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Delete one session rule. Nothing references a rule, so no other check is needed."""

        return super().delete(uid)


class _RuleValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("weekdays", mode="before", check_fields=False)
    @classmethod
    def _normalize_weekdays(cls, value: str | None) -> str | None:
        return None if value is None else normalize_weekdays(value)

    @field_validator("opens_at_local", "closes_at_local", mode="before", check_fields=False)
    @classmethod
    def _normalize_local_time(cls, value: dt.time | str | None) -> str | None:
        return format_local_time(value)


class CalendarSessionRuleCreate(_RuleValues):
    """Payload for creating one session rule."""

    calendar_uid: uuid.UUID | str
    session_label: str = Field(default=DEFAULT_SESSION_LABEL, min_length=1, max_length=64)
    effective_from: dt.date
    effective_to: dt.date | None = None
    weekdays: str
    opens_at_local: str | None = None
    closes_at_local: str | None = None
    open_day_offset: int = Field(default=0, ge=-1, le=1)
    close_day_offset: int = Field(default=0, ge=-1, le=1)
    is_primary: bool = True

    @model_validator(mode="after")
    def _validate_window(self) -> CalendarSessionRuleCreate:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be greater than or equal to effective_from.")
        return self


class CalendarSessionRuleUpsert(CalendarSessionRuleCreate):
    """Payload for inserting or updating a rule by calendar, session and first date."""


class CalendarSessionRuleUpdate(_RuleValues):
    """Payload for updating mutable session rule fields."""

    effective_to: dt.date | None = None
    weekdays: str | None = None
    opens_at_local: str | None = None
    closes_at_local: str | None = None
    open_day_offset: int | None = Field(default=None, ge=-1, le=1)
    close_day_offset: int | None = Field(default=None, ge=-1, le=1)
    is_primary: bool | None = None


_RULE_VALUE_FIELDS = (
    "calendar_uid",
    "session_label",
    "effective_from",
    "effective_to",
    "weekdays",
    "opens_at_local",
    "closes_at_local",
    "open_day_offset",
    "close_day_offset",
    "is_primary",
)


def validate_rule_update(stored: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
    """Check an update as a new rule is checked: the stored row with the changes applied."""

    merged = {**stored, **changes}
    CalendarSessionRuleCreate(**{key: merged.get(key) for key in _RULE_VALUE_FIELDS})


__all__ = [
    "CalendarSessionRule",
    "CalendarSessionRuleCreate",
    "CalendarSessionRuleUpdate",
    "CalendarSessionRuleUpsert",
    "validate_rule_update",
]
