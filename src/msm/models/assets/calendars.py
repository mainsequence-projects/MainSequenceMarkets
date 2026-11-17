from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
)
from msm.models.calendars import CalendarTable

from .core import AssetTable


class AssetCalendarTable(MarketsMetaTableMixin, MarketsBase):
    """The stored calendar whose sessions say when an asset has price bars."""

    __metatable_identifier__ = "AssetCalendar"
    __metatable_description__ = (
        "One-to-one trading calendar link keyed by AssetTable.uid. Names the stored "
        "Calendar whose sessions decide which price bars the asset has. An asset "
        "without a row has no trading calendar, and its price updates are refused."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "calendar_uid"),
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the linked asset.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{CalendarTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": (
                "CalendarTable.uid of the stored calendar whose sessions decide which "
                "price bars the asset has."
            ),
        },
    )


__all__ = ["AssetCalendarTable"]
