from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
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
            None,
            "issuer_uid",
        ),
        Index(
            None,
            "currency_asset_uid",
        ),
        Index(
            None,
            "status",
        ),
        Index(
            None,
            "maturity_date",
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
    issuer_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IssuerTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Issuer UID",
            "description": "Foreign key to IssuerTable.uid for the instrument issuer.",
        },
    )
    currency_asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Currency Asset UID",
            "description": "AssetTable.uid for the currency in which this instrument is denominated.",
        },
    )
    issue_date: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Issue Date",
            "description": "Date on which the bond or debt instrument was issued.",
        },
    )
    maturity_date: Mapped[dt.date | None] = mapped_column(
        Date,
        nullable=True,
        info={
            "label": "Maturity Date",
            "description": "Date on which the bond or debt instrument matures.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Status",
            "description": "Lifecycle or execution status value for the row.",
        },
    )


__all__ = ["BondAssetDetailsTable"]
