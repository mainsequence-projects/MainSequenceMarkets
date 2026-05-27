from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
)

from .core import AssetTable


class CurrencySpotTable(MarketsMetaTableMixin, MarketsBase):
    """Currency spot pair detail row linked to a markets asset."""

    __metatable_identifier__ = "CurrencySpot"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "base_currency_uid",
                "quote_currency_uid",
                unique=True,
            ),
            "base_currency_uid",
            "quote_currency_uid",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "base_currency_uid"),
            "base_currency_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "quote_currency_uid"),
            "quote_currency_uid",
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
    base_currency_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "base_currency_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    quote_currency_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "quote_currency_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )


__all__ = ["CurrencySpotTable"]
