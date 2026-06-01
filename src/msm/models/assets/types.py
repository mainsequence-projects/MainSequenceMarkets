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


class AssetTypeTable(MarketsMetaTableMixin, MarketsBase):
    """Registered asset type used to classify assets without widening AssetTable."""

    __metatable_identifier__ = "AssetType"
    __metatable_description__ = (
        "Asset type registry keyed by asset_type. Documents and validates allowed "
        "Asset.asset_type values without widening AssetTable with type-specific "
        "columns."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "asset_type", unique=True),
            "asset_type",
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
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    asset_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Asset Type",
            "description": "Canonical asset type code used to classify rows in AssetTable.",
        },
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
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


__all__ = ["AssetTypeTable"]
