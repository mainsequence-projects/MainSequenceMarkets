from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
)

from .assets import AssetTable
from .indices import IndexTable


class FutureAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Future contract detail row linked to a canonical markets asset."""

    __metatable_identifier__ = "FutureAssetDetails"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "underlying_index_uid"),
            "underlying_index_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "settlement_asset"),
            "settlement_asset",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "margin_asset"),
            "margin_asset",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "expires_at"),
            "expires_at",
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
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    underlying_index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Index", "underlying_index_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    quote_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_asset: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "settlement_asset"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    margin_asset: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "margin_asset"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    settlement_model: Mapped[str] = mapped_column(String(32), nullable=False)
    settlement_method: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    contract_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    settles_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_payload: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )


__all__ = ["FutureAssetDetailsTable"]
