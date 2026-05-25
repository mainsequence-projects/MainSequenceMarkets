from __future__ import annotations

import uuid

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    markets_table_name,
    new_markets_uid,
)


class Calendar(MarketsMetaTableMixin, MarketsBase):
    """Named market calendar used by portfolio and execution workflows."""

    __metatable_identifier__ = "Calendar"
    __tablename__ = markets_table_name(__metatable_identifier__)
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "name", unique=True),
            "name",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    calendar_dates: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["Calendar"]
