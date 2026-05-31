from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)

from .core import AssetTable


class AssetCategoryTable(MarketsMetaTableMixin, MarketsBase):
    """Client-owned category used to group assets in the markets catalog."""

    __metatable_identifier__ = "AssetCategory"
    __metatable_description__ = (
        "Asset category registry keyed by unique_identifier. Stores client-owned "
        "category names, descriptions, and metadata used to group canonical assets."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "display_name"),
            "display_name",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AssetCategoryMembershipTable(MarketsMetaTableMixin, MarketsBase):
    """Many-to-many membership row between assets and asset categories."""

    __metatable_identifier__ = "AssetCategoryMembership"
    __metatable_description__ = (
        "Asset category membership table keyed by category_uid and asset_uid. Stores "
        "the many-to-many relationship between AssetCategory rows and canonical "
        "Asset rows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "category_uid",
                "asset_uid",
                unique=True,
            ),
            "category_uid",
            "asset_uid",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "asset_uid"),
            "asset_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    category_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetCategoryTable.__table__.fullname}.uid",
            name=markets_fk_name(
                __metatable_identifier__,
                "AssetCategory",
                "category_uid",
            ),
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="CASCADE",
        ),
        nullable=False,
    )


__all__ = [
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
]
