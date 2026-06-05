from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .core import CalendarTable


class CalendarEventTable(MarketsMetaTableMixin, MarketsBase):
    """Calendar-level event or convention fact."""

    __metatable_identifier__ = "CalendarEvent"
    __metatable_description__ = (
        "Calendar event table keyed by calendar, event date, event type, label, "
        "and optional target identity. Stores calendar-level expiry, settlement, "
        "roll, fixing, early-close, and convention events that are not tied to a "
        "single instrument position."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "calendar_uid",
            "event_date",
            "event_type",
            "event_label",
            "target_type",
            "target_identifier",
            unique=True,
        ),
        Index(None, "calendar_uid", "event_date"),
        Index(None, "event_type"),
        Index(None, "target_type", "target_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this calendar-event row.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CalendarTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the calendar or market convention that owns this event.",
        },
    )
    event_date: Mapped[dt.date | None] = mapped_column(
        Date,
        nullable=True,
        info={
            "label": "Event Date",
            "description": "Calendar-local date for this event when the event has a date component.",
        },
    )
    event_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Event Time",
            "description": "UTC timestamp for this event when the event has an intraday instant.",
        },
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Event Type",
            "description": "Stable event type such as EXPIRY, LAST_TRADE, FIXING, SETTLEMENT, ROLL, EARLY_CLOSE, or HOLIDAY.",
        },
    )
    event_label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        info={
            "label": "Event Label",
            "description": "Optional label that disambiguates same-type calendar events on the same date.",
        },
    )
    target_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        info={
            "label": "Target Type",
            "description": "Optional target kind such as asset, index, product_family, future_contract, or empty for global events.",
        },
    )
    target_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Target UID",
            "description": "Optional UUID of the target object when the event is scoped to a platform row.",
        },
    )
    target_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        info={
            "label": "Target Identifier",
            "description": "Optional stable target business identifier used when target_uid is unavailable or unnecessary.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured provider, product-family, or convention metadata for this calendar event.",
        },
    )


__all__ = ["CalendarEventTable"]
