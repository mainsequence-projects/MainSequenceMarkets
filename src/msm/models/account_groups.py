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
    new_markets_uid,
)


class AccountModelPortfolioTable(MarketsMetaTableMixin, MarketsBase):
    """Named model portfolio grouping account groups."""

    __metatable_identifier__ = "AccountModelPortfolio"
    __metatable_description__ = (
        "Account model-portfolio registry keyed by model_portfolio_name. Groups "
        "account groups under a named portfolio policy and stores descriptive "
        "metadata for account-model workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "model_portfolio_name", unique=True),
            "model_portfolio_name",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    model_portfolio_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_portfolio_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AccountGroupTable(MarketsMetaTableMixin, MarketsBase):
    """Account grouping metadata used by market workflows."""

    __metatable_identifier__ = "AccountGroup"
    __metatable_description__ = (
        "Account group registry keyed by group_name. Links optional account model "
        "portfolios to reusable account-group metadata used by account and portfolio "
        "workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "group_name", unique=True),
            "group_name",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "account_model_portfolio_uid"),
            "account_model_portfolio_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    group_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_model_portfolio_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountModelPortfolioTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = [
    "AccountGroupTable",
    "AccountModelPortfolioTable",
]
