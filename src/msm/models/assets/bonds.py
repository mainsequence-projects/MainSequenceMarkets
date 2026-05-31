from __future__ import annotations

import datetime as dt
import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
)

from ..issuers import IssuerTable
from .core import AssetTable


class BondAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Bond detail row linked to a canonical markets asset."""

    __metatable_identifier__ = "BondAssetDetails"
    __metatable_description__ = (
        "One-to-one bond detail table keyed by AssetTable.uid. Stores issuer, "
        "currency, coupon, maturity, status, and bond identifiers for assets whose "
        "AssetType is bond."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "issuer_uid"),
            "issuer_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "currency_asset_uid"),
            "currency_asset_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "status"),
            "status",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "maturity_date"),
            "maturity_date",
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
    )
    issuer_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            IssuerTable,
            column="uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    currency_asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    issue_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


__all__ = ["BondAssetDetailsTable"]
