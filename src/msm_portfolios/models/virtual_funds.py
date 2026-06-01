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

from msm.models.accounts import AccountTable

from msm_portfolios.models.portfolios import PortfolioTable


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
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable business identifier used for idempotent upserts, lookup, and joins.",
        },
    )
    target_account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Target Account UID",
            "description": "Foreign key to AccountTable.uid for the account targeted by the workflow.",
        },
    )
    target_portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            PortfolioTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Target Portfolio UID",
            "description": "Foreign key to PortfolioTable.uid for the target portfolio.",
        },
    )
    requires_nav_adjustment: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        info={
            "label": "Requires NAV Adjustment",
            "description": "Whether the fund workflow requires NAV adjustment handling.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


__all__ = ["FundTable"]
