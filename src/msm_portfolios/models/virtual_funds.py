from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from msm.models.accounts import AccountHoldingsSetTable, AccountTable

from msm.models import PortfolioTable


class VirtualFundTable(MarketsMetaTableMixin, MarketsBase):
    """Account-owned virtual-fund allocation view targeting a portfolio."""

    __metatable_identifier__ = "VirtualFund"
    __metatable_description__ = (
        "Virtual-fund registry keyed by unique_identifier. A virtual fund is not "
        "an asset or a custody account; it is an account-owned allocation view "
        "over real account holdings that targets one PortfolioTable row."
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
            "account_uid",
        ),
        Index(
            None,
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
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Account UID",
            "description": "AccountTable.uid for the account that owns this virtual-fund view.",
        },
    )
    target_portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{PortfolioTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Target Portfolio UID",
            "description": "Foreign key to PortfolioTable.uid for the target portfolio.",
        },
    )


class VirtualFundHoldingsSetTable(MarketsMetaTableMixin, MarketsBase):
    """Allocation set that binds one virtual fund to one source account holdings set."""

    __metatable_identifier__ = "VirtualFundHoldingsSet"
    __metatable_description__ = (
        "Virtual-fund holdings-set registry. Each row identifies one allocation "
        "view for a virtual fund funded by one AccountHoldingsSetTable row."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "virtual_fund_uid",
        ),
        Index(
            None,
            "source_account_holdings_set_uid",
        ),
        Index(
            None,
            "virtual_fund_uid",
            "source_account_holdings_set_uid",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable virtual-fund holdings-set identity referenced by allocation storage.",
        },
    )
    virtual_fund_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund UID",
            "description": "VirtualFundTable.uid for the virtual fund receiving the allocation view.",
        },
    )
    source_account_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountHoldingsSetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Source Account Holdings Set UID",
            "description": "AccountHoldingsSetTable.uid for the real account holdings source.",
        },
    )
    time_index: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for this virtual-fund allocation set.",
        },
    )


__all__ = ["VirtualFundHoldingsSetTable", "VirtualFundTable"]
