from __future__ import annotations

import datetime as dt
import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
)
from msm.models.assets import AssetTable


class AssetCurrentPricingDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Current priceable instrument details linked to a canonical markets asset."""

    __metatable_identifier__ = "AssetCurrentPricingDetails"
    __metatable_description__ = (
        "Current asset pricing-detail table keyed by AssetTable.uid. Stores the "
        "active serialized priceable instrument payload, instrument type, pricing "
        "date, format, package version, source, and metadata for one canonical "
        "asset."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "instrument_type"),
            "instrument_type",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "pricing_details_date"),
            "pricing_details_date",
        ),
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
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
    instrument_dump: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        info={
            "label": "Instrument Dump",
            "description": "Serialized priceable instrument payload stored for current pricing details.",
        },
    )
    pricing_details_date: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Pricing Details Date",
            "description": "UTC timestamp for the current pricing-detail payload.",
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
            "description": "Source system, workflow, or provider that produced the row.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )


__all__ = ["AssetCurrentPricingDetailsTable"]
