"""Asset pricing-detail DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION


class AssetPricingDetailsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped provider pricing metadata keyed by asset unique identifier."""

    __metatable_identifier__ = "AssetPricingDetailsTS"
    __metatable_description__ = (
        "Timestamped asset pricing-detail storage keyed by (time_index, "
        "asset_identifier). Stores serialized pricing instrument payloads for "
        "canonical assets before current-pricing rows are promoted."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the asset fact row."},
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier from the Asset MetaTable.",
        },
    )
    instrument_dump: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Instrument Dump",
            "description": "Provider-specific pricing instrument payload for the asset observation.",
        },
    )


__all__ = ["AssetPricingDetailsStorage"]
