from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .core import CalendarTable


class CalendarDateTable(MarketsMetaTableMixin, MarketsBase):
    """One local-date calendar fact for a persisted calendar."""

    __metatable_identifier__ = "CalendarDate"
    __metatable_description__ = (
        "Calendar date table keyed by calendar_uid and local_date. Stores one "
        "daily business-day, holiday, weekend, and early-close fact per "
        "calendar date for deterministic joins and reproducible schedules."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "calendar_uid", "local_date", unique=True),
        Index(None, "local_date"),
        Index(None, "calendar_uid", "is_business_day"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this calendar-date row.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CalendarTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the calendar that owns this local-date fact.",
        },
    )
    local_date: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Local Date",
            "description": "Calendar-local date represented by this daily calendar fact.",
        },
    )
    is_business_day: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        info={
            "label": "Is Business Day",
            "description": "True when this local date is an active business day for the calendar.",
        },
    )
    is_holiday: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        info={
            "label": "Is Holiday",
            "description": "True when this local date is a named or provider-derived holiday.",
        },
    )
    is_weekend: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        info={
            "label": "Is Weekend",
            "description": "True when this local date falls on a weekend in the calendar locale.",
        },
    )
    is_early_close: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        info={
            "label": "Is Early Close",
            "description": "True when the calendar has a shortened primary session on this local date.",
        },
    )
    holiday_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Holiday Name",
            "description": "Optional provider or user-facing name for the holiday on this date.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured provider, market, or override metadata for this calendar-date fact.",
        },
    )


__all__ = ["CalendarDateTable"]
