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
        "asset_identifier). Stores serialized pricing instrument payloads and "
        "serialization metadata for canonical assets. User-facing pricing-detail "
        "writes upsert this table; writes without an explicit timestamp also "
        "update AssetCurrentPricingDetailsTable for fast runtime instrument "
        "loading."
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
        nullable=False,
        info={
            "label": "Instrument Dump",
            "description": "Provider-specific pricing instrument payload for the asset observation.",
        },
    )
    instrument_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        info={
            "label": "Instrument Type",
            "description": "Concrete pricing instrument type used to rebuild the serialized payload.",
        },
    )
    serialization_format: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        info={
            "label": "Serialization Format",
            "description": "Serialization format used for the stored pricing payload.",
        },
    )
    pricing_package_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Pricing Package Version",
            "description": "Version of the pricing package that serialized the instrument payload.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Source system, workflow, or provider that produced the observation.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )


__all__ = ["AssetPricingDetailsStorage"]
