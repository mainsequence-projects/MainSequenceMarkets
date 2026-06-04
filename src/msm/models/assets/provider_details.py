from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
)

from .core import AssetTable


class OpenFigiAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """OpenFIGI/provider detail row linked to a markets asset."""

    __metatable_identifier__ = "OpenFigiAssetDetails"
    __metatable_description__ = (
        "One-to-one OpenFIGI/provider detail table keyed by AssetTable.uid. Stores "
        "FIGI, ticker, ISIN, exchange, security classification, metadata text, and "
        "raw provider payload for a canonical asset."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "figi"),
        Index(None, "ticker"),
        Index(None, "isin"),
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    figi: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        info={
            "label": "FIGI",
            "description": "Primary OpenFIGI identifier for the asset.",
        },
    )
    composite: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        info={
            "label": "Composite",
            "description": "OpenFIGI composite FIGI for the asset when supplied by the provider.",
        },
    )
    share_class: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        info={
            "label": "Share Class",
            "description": "OpenFIGI share-class FIGI for the asset when supplied by the provider.",
        },
    )
    isin: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        info={
            "label": "ISIN",
            "description": "International Securities Identification Number supplied by a provider.",
        },
    )
    ticker: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        info={
            "label": "Ticker",
            "description": "Provider ticker or display symbol for the asset.",
        },
    )
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Name",
            "description": "Canonical human-readable name for this registry row.",
        },
    )
    exchange_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        info={
            "label": "Exchange Code",
            "description": "Exchange or market code reported by the external provider.",
        },
    )
    security_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        info={
            "label": "Security Type",
            "description": "Provider security type classification for the asset.",
        },
    )
    security_type_2: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        info={
            "label": "Security Type 2",
            "description": "Secondary provider security type classification.",
        },
    )
    security_market_sector: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        info={
            "label": "Security Market Sector",
            "description": "Provider market sector classification for the security.",
        },
    )
    security_description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Security Description",
            "description": "Provider security description for the asset.",
        },
    )
    unique_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Unique ID",
            "description": "Provider unique identifier for the security.",
        },
    )
    unique_id_fut_opt: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Unique Id Fut Opt",
            "description": "Provider unique identifier for related futures or options metadata.",
        },
    )
    metadata_text: Mapped[str | None] = mapped_column(
        "metadata",
        Text,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )
    raw_payload: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Raw Payload",
            "description": "Raw provider payload retained for audit and troubleshooting.",
        },
    )


__all__ = ["OpenFigiAssetDetailsTable"]
