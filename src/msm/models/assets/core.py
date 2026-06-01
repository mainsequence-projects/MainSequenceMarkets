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
    __metatable_description__ = (
        "Canonical asset identity table keyed by uid and unique_identifier. Holds "
        "only shared asset identity and asset_type so type-specific properties live "
        "in one-to-one asset detail tables or DataNode storage."
    )
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
    asset_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Asset Type",
            "description": "Canonical asset type code used to classify rows in AssetTable.",
        },
    )


__all__ = ["AssetTable"]
