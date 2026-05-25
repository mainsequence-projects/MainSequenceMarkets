from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)


class SignalMetadata(MarketsMetaTableMixin, MarketsBase):
    """Metadata row for a canonical portfolios signal."""

    __metatable_identifier__ = "SignalMetadata"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "signal_uid", unique=True),
            "signal_uid",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    signal_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    signal_description: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["SignalMetadata"]
