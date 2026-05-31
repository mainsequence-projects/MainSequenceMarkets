from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
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
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    instrument_type: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_dump: Mapped[dict] = mapped_column(JSON, nullable=False)
    pricing_details_date: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    serialization_format: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing_package_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


__all__ = ["AssetCurrentPricingDetailsTable"]
