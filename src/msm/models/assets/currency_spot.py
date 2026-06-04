from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
)

from .core import AssetTable


class CurrencySpotAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Currency spot pair detail row linked to a markets asset."""

    __metatable_identifier__ = "CurrencySpotAssetDetails"
    __metatable_description__ = (
        "One-to-one currency spot detail table keyed by AssetTable.uid. Links a "
        "spot-pair asset to its canonical base and quote currency assets."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "base_currency_uid",
            "quote_currency_uid",
            unique=True,
        ),
        Index(
            None,
            "base_currency_uid",
        ),
        Index(
            None,
            "quote_currency_uid",
        ),
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
    base_currency_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Base Currency UID",
            "description": "AssetTable.uid for the base currency in a currency pair.",
        },
    )
    quote_currency_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Quote Currency UID",
            "description": "AssetTable.uid for the quote currency in a currency pair.",
        },
    )


__all__ = ["CurrencySpotAssetDetailsTable"]
