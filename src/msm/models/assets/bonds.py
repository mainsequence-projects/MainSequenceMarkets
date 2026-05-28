from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
)

from ..issuers import IssuerTable
from .core import AssetTable


class BondAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Bond detail row linked to a canonical markets asset."""

    __metatable_identifier__ = "BondAssetDetails"
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
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    issuer_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IssuerTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Issuer", "issuer_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    currency_asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "currency_asset_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    issue_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


__all__ = ["BondAssetDetailsTable"]
