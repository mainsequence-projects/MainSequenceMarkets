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
    markets_table_name,
    new_markets_uid,
)

from .assets import Asset


class OpenFigiDetails(MarketsMetaTableMixin, MarketsBase):
    """OpenFIGI/provider detail row linked to a markets asset."""

    __metatable_identifier__ = "OpenFigiDetails"
    __tablename__ = markets_table_name(__metatable_identifier__)
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "asset_uid", unique=True),
            "asset_uid",
            unique=True,
        ),
        Index(markets_index_name(__metatable_identifier__, "figi"), "figi"),
        Index(markets_index_name(__metatable_identifier__, "ticker"), "ticker"),
        Index(markets_index_name(__metatable_identifier__, "isin"), "isin"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{Asset.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="CASCADE",
        ),
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


__all__ = ["OpenFigiDetails"]
