from __future__ import annotations

import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
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
        Index(markets_index_name(__metatable_identifier__, "figi"), "figi"),
        Index(markets_index_name(__metatable_identifier__, "ticker"), "ticker"),
        Index(markets_index_name(__metatable_identifier__, "isin"), "isin"),
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
    )
    figi: Mapped[str | None] = mapped_column(String(12), nullable=True)
    composite: Mapped[str | None] = mapped_column(String(12), nullable=True)
    share_class: Mapped[str | None] = mapped_column(String(12), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exchange_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    security_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    security_type_2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    security_market_sector: Mapped[str | None] = mapped_column(String(50), nullable=True)
    security_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unique_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unique_id_fut_opt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_text: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["OpenFigiAssetDetailsTable"]
