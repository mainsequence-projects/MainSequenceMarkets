from __future__ import annotations

import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)

from .accounts import AccountTable
from .portfolios import PortfolioTable


class FundTable(MarketsMetaTableMixin, MarketsBase):
    """Fund runtime model for account-bound portfolio tracking."""

    __metatable_identifier__ = "Fund"
    __metatable_description__ = (
        "Virtual fund registry keyed by uid and fund_name. Stores account linkage, "
        "portfolio construction mode, portfolio/execution DataNode pointers, and "
        "fund metadata for tracking workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "target_account_uid"),
            "target_account_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "target_portfolio_uid"),
            "target_portfolio_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    target_account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    target_portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            PortfolioTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    requires_nav_adjustment: Mapped[bool] = mapped_column(default=False, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["FundTable"]
