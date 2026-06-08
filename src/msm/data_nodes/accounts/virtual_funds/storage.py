"""Virtual-fund DataNode storage contracts."""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.accounts import AccountHoldingsSetTable
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm.models.accounts.virtual_funds import VirtualFundHoldingsSetTable, VirtualFundTable


class VirtualFundHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Virtual-fund allocations keyed by virtual fund UID and held asset."""

    __metatable_identifier__ = "VirtualFundHoldingsTS"
    __metatable_description__ = (
        "Timestamped virtual-fund allocation storage keyed by (time_index, "
        "virtual_fund_uid, asset_identifier). Each row is a positive allocated "
        "quantity from a source account holdings set, with direction storing the "
        "long/short side."
    )
    __table_args__ = (
        CheckConstraint("direction IN (1, -1)", name="ck_virtual_fund_holdings_direction"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "virtual_fund_uid",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp for the virtual-fund allocation snapshot. Rows with "
                "the same virtual_fund_uid and time_index belong to one allocation view."
            ),
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
            "description": (
                "Stable VirtualFundTable.uid that owns the allocation row. This "
                "dimension scopes allocation history to one virtual fund."
            ),
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the allocated instrument.",
        },
    )
    virtual_fund_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundHoldingsSetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund Holdings Set UID",
            "description": "VirtualFundHoldingsSetTable.uid shared by rows in one allocation set.",
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
            "description": "AccountHoldingsSetTable.uid that bounds this allocation row.",
        },
    )
    allocated_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Allocated Quantity",
            "description": "Positive source-account holdings magnitude allocated to this virtual fund.",
        },
    )
    allocation_strategy: Mapped[str] = mapped_column(
        String(64),
        default="explicit",
        nullable=False,
        info={
            "label": "Allocation Strategy",
            "description": (
                "First-class strategy used to produce this virtual-fund allocation row. "
                "Low-level explicit publications use 'explicit'; planner-applied rows "
                "use the allocation policy mode, such as 'proportional_attribution' "
                "or 'strict_feasible'."
            ),
        },
    )
    direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Direction",
            "description": "Allocation side: 1 for long, -1 for short.",
        },
    )
    target_trade_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Target Trade Time",
            "description": (
                "Requested or expected execution time as a timezone-aware UTC datetime when provided."
            ),
        },
    )
    extra_details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Extra Details",
            "description": "JSONB payload for provider-specific holdings attributes.",
        },
    )


__all__ = ["VirtualFundHoldingsStorage"]
