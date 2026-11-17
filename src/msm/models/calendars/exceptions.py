from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .core import CalendarTable


class CalendarExceptionTable(MarketsMetaTableMixin, MarketsBase):
    """One dated departure from a calendar's session rules (ADR 0055)."""

    __metatable_identifier__ = "CalendarException"
    __metatable_description__ = (
        "Calendar exception table keyed by calendar_uid, local_date, "
        "session_label, exception_type and source. Each row is one dated "
        "departure from the calendar's session rules: a closed day, an early "
        "close, a late open, or a session on a date the rules have none. "
        "source records who wrote the row: an adapter's name or user."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "calendar_uid",
            "local_date",
            "session_label",
            "exception_type",
            "source",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this calendar exception row.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CalendarTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the calendar that owns this exception.",
        },
    )
    local_date: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Local Date",
            "description": "Calendar-local date this exception applies to.",
        },
    )
    session_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        info={
            "label": "Session Label",
            "description": "Session the exception changes; empty for the whole day.",
        },
    )
    exception_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Exception Type",
            "description": "CLOSED, EARLY_CLOSE, LATE_OPEN, or OPEN.",
        },
    )
    opens_at_local: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        info={
            "label": "Opens At (Local)",
            "description": "Wall-clock open time HH:MM:SS that replaces the rule's; null where the rule's holds.",
        },
    )
    closes_at_local: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        info={
            "label": "Closes At (Local)",
            "description": "Wall-clock close time HH:MM:SS that replaces the rule's; null where the rule's holds.",
        },
    )
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Name",
            "description": "Optional name of the exception, such as Thanksgiving Day.",
        },
    )
    source: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="user",
        info={
            "label": "Source",
            "description": "Who wrote the row: an adapter's name such as pandas_market_calendars, or user.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata for this exception.",
        },
    )


__all__ = ["CalendarExceptionTable"]
