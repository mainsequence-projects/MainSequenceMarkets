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


class AccountModelPortfolio(MarketsMetaTableMixin, MarketsBase):
    """Named model portfolio grouping account groups."""

    __metatable_identifier__ = "AccountModelPortfolio"
    __tablename__ = markets_table_name(__metatable_identifier__)
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


class AccountGroup(MarketsMetaTableMixin, MarketsBase):
    """Account grouping metadata used by market workflows."""

    __metatable_identifier__ = "AccountGroup"
    __tablename__ = markets_table_name(__metatable_identifier__)
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
        ForeignKey(
            f"{AccountModelPortfolio.__table__.fullname}.uid",
            name=markets_fk_name(
                __metatable_identifier__,
                "AccountModelPortfolio",
                "account_model_portfolio_uid",
            ),
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["AccountGroup", "AccountModelPortfolio"]
