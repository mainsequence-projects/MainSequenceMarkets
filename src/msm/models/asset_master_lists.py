from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)


class AssetMasterListTable(MarketsMetaTableMixin, MarketsBase):
    """Control-plane table selecting the canonical asset reference MetaTable."""

    __metatable_identifier__ = "AssetMasterList"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "reference_meta_table_uid"),
            "reference_meta_table_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "is_default"),
            "is_default",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reference_meta_table_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    validation_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["AssetMasterListTable"]
