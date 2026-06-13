from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)
from msm.models.portfolios.core import PortfolioTable


class PortfolioGroupTable(MarketsMetaTableMixin, MarketsBase):
    """Reusable many-to-many portfolio classification group."""

    __metatable_identifier__ = "PortfolioGroup"
    __metatable_description__ = (
        "Portfolio group registry keyed by unique_identifier. Defines reusable "
        "many-to-many classifications for portfolios such as strategy sleeves, "
        "client views, research cohorts, or operational reporting buckets."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "unique_identifier",
            unique=True,
        ),
        Index(
            None,
            "display_name",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable portfolio group identity referenced by membership rows.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable group identifier used for idempotent upserts and lookup.",
        },
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Display Name",
            "description": "Human-readable name for this portfolio group.",
        },
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Description",
            "description": "Free-form description of the group membership intent.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Optional JSON metadata for group provenance or labels.",
        },
    )


class PortfolioGroupMembershipTable(MarketsMetaTableMixin, MarketsBase):
    """Many-to-many membership row between portfolio groups and portfolios."""

    __metatable_identifier__ = "PortfolioGroupMembership"
    __metatable_description__ = (
        "Many-to-many portfolio group membership table. Each row links one "
        "PortfolioGroupTable row to one PortfolioTable row, with cascade cleanup "
        "of membership rows when either side is deleted."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "portfolio_group_uid",
            "portfolio_uid",
            unique=True,
        ),
        Index(
            None,
            "portfolio_group_uid",
        ),
        Index(
            None,
            "portfolio_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable portfolio group membership row identity.",
        },
    )
    portfolio_group_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{PortfolioGroupTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Portfolio Group UID",
            "description": "Foreign key to the owning PortfolioGroupTable.uid row.",
        },
    )
    portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{PortfolioTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Portfolio UID",
            "description": "Foreign key to the assigned PortfolioTable.uid row.",
        },
    )


__all__ = [
    "PortfolioGroupMembershipTable",
    "PortfolioGroupTable",
]
