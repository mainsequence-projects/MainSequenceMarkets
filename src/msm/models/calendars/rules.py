from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .core import CalendarTable


class CalendarSessionRuleTable(MarketsMetaTableMixin, MarketsBase):
    """The regular week of one session of a calendar, from a date on (ADR 0055)."""

    __metatable_identifier__ = "CalendarSessionRule"
    __metatable_description__ = (
        "Calendar session rule table keyed by calendar_uid, session_label and "
        "effective_from. Each row is the regular week of one session from a "
        "date on: the weekdays it runs and its local open and close times. "
        "Dates and sessions are computed from these rules and the calendar's "
        "exceptions; no row is stored per date."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "calendar_uid", "session_label", "effective_from", unique=True),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this session rule row.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CalendarTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the calendar that owns this rule.",
        },
    )
    session_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="regular",
        info={
            "label": "Session Label",
            "description": "Session this rule describes, such as regular, pre_market, or fixing_window.",
        },
    )
    effective_from: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Effective From",
            "description": "First calendar-local date this rule applies to.",
        },
    )
    effective_to: Mapped[dt.date | None] = mapped_column(
        Date,
        nullable=True,
        info={
            "label": "Effective To",
            "description": "Last calendar-local date this rule applies to; null while the rule is current.",
        },
    )
    weekdays: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        info={
            "label": "Weekdays",
            "description": "Seven characters, Monday first: 1 where the session runs, 0 where it does not.",
        },
    )
    opens_at_local: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        info={
            "label": "Opens At (Local)",
            "description": "Wall-clock open time HH:MM:SS in the calendar's timezone; null for a date-only calendar.",
        },
    )
    closes_at_local: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        info={
            "label": "Closes At (Local)",
            "description": "Wall-clock close time HH:MM:SS in the calendar's timezone; null for a date-only calendar.",
        },
    )
    open_day_offset: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        info={
            "label": "Open Day Offset",
            "description": "Days from the session's local date to its open: -1 opens the evening before.",
        },
    )
    close_day_offset: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        info={
            "label": "Close Day Offset",
            "description": "Days from the session's local date to its close: 1 closes at the next midnight.",
        },
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        info={
            "label": "Is Primary",
            "description": "True when this is the calendar's main session for a date.",
        },
    )


__all__ = ["CalendarSessionRuleTable"]
