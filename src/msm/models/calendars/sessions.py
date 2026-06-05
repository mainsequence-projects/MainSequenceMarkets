from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .core import CalendarTable


class CalendarSessionTable(MarketsMetaTableMixin, MarketsBase):
    """One intraday or market-session window for a persisted calendar date."""

    __metatable_identifier__ = "CalendarSession"
    __metatable_description__ = (
        "Calendar session table keyed by calendar_uid, local_date, and "
        "session_label. Stores optional UTC open and close windows used by "
        "trading, execution, intraday portfolio, fixing, and settlement workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "calendar_uid", "local_date", "session_label", unique=True),
        Index(None, "local_date"),
        Index(None, "calendar_uid", "is_primary"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this calendar-session row.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CalendarTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the calendar that owns this session.",
        },
    )
    local_date: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Local Date",
            "description": "Calendar-local date on which this session occurs.",
        },
    )
    session_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Session Label",
            "description": "Stable session key such as regular, pre_market, post_market, pit, electronic, or fixing_window.",
        },
    )
    opens_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Opens At",
            "description": "UTC timestamp when this session opens, when the source provides one.",
        },
    )
    closes_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Closes At",
            "description": "UTC timestamp when this session closes, when the source provides one.",
        },
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        info={
            "label": "Timezone",
            "description": "IANA timezone used to interpret the session's local date.",
        },
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        info={
            "label": "Is Primary",
            "description": "True when this is the primary session for the calendar-local date.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured provider, venue, or workflow metadata for this session window.",
        },
    )


__all__ = ["CalendarSessionTable"]
