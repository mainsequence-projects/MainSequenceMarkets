from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
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
            None,
            "unique_identifier",
            unique=True,
        ),
        Index(
            None,
            "display_name",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable business identifier used for idempotent upserts, lookup, and joins.",
        },
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Display Name",
            "description": "Human-readable display name for UI, logs, and operator workflows.",
        },
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Description",
            "description": "Human-readable description of the registry row and its intended use.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


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
            None,
            "category_uid",
            "asset_uid",
            unique=True,
        ),
        Index(
            None,
            "asset_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    category_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetCategoryTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Category UID",
            "description": "Foreign key to the AssetCategoryTable.uid for this membership row.",
        },
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )


__all__ = [
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
]
