from __future__ import annotations

import uuid

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)


class AssetTable(MarketsMetaTableMixin, MarketsBase):
    """Relational asset catalog row owned by markets MetaTables."""

    __metatable_identifier__ = "Asset"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "asset_type"),
            "asset_type",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str | None] = mapped_column(String(64), nullable=True)


Asset = AssetTable

__all__ = ["Asset", "AssetTable"]
