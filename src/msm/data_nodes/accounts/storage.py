"""Account DataNode storage contracts."""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.data_nodes.accounts.constants import (
    TARGET_POSITION_TARGET_TYPES,
    TARGET_POSITION_TARGET_TYPE_SQL,
    TARGET_TYPE_ASSET,
    TARGET_TYPE_PORTFOLIO,
)
from msm.models.accounts import AccountHoldingsSetTable, AccountTable, PositionSetTable
from msm.models.assets.core import AssetTable
from msm.models.portfolios import PortfolioTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION


class AccountHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Account historical holdings keyed by account UID and held asset."""

    __metatable_identifier__ = "AccountHoldingsTS"
    __metatable_description__ = (
        "Timestamped account holdings storage keyed by (time_index, account_uid, "
        "asset_identifier). Each row is one asset position in an account holdings "
        "set. quantity is a positive magnitude and direction stores the long/short "
        "side."
    )
    __table_args__ = (
        CheckConstraint("direction IN (1, -1)", name="ck_account_holdings_direction"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "account_uid",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp for the account holdings snapshot. Rows with the same "
                "account_uid and time_index belong to the same account observation."
            ),
        },
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Account UID",
            "description": (
                "Stable Account UID that owns the holdings row. This dimension scopes "
                "holdings history to one account."
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
            "description": "Asset unique identifier for the held instrument at this account timestamp.",
        },
    )
    holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountHoldingsSetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Holdings Set UID",
            "description": "AccountHoldingsSetTable.uid shared by rows in one account snapshot.",
        },
    )
    is_trade_snapshot: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info={
            "label": "Is Trade Snapshot",
            "description": "Whether the holdings row belongs to an execution or trade snapshot.",
        },
    )
    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Quantity",
            "description": "Positive position magnitude held for this asset in the account snapshot.",
        },
    )
    direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Direction",
            "description": "Position side: 1 for long, -1 for short.",
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


class TargetPositionsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Account target allocation rows keyed by position set and target object."""

    __metatable_identifier__ = "TargetPositionsTS"
    __metatable_description__ = (
        "Timestamped account target-allocation storage keyed by "
        "(time_index, position_set_uid, target_type, target_uid). Each row is "
        "one target exposure in a PositionSetTable snapshot and references "
        "exactly one concrete target: either a direct AssetTable row or a "
        "core PortfolioTable row."
    )
    __table_args__ = (
        CheckConstraint(
            f"target_type IN ({TARGET_POSITION_TARGET_TYPE_SQL})",
            name="ck_target_positions_target_type",
        ),
        CheckConstraint(
            "("
            f"target_type = '{TARGET_TYPE_ASSET}' AND asset_uid IS NOT NULL "
            "AND portfolio_uid IS NULL AND target_uid = asset_uid"
            ") OR ("
            f"target_type = '{TARGET_TYPE_PORTFOLIO}' AND portfolio_uid IS NOT NULL "
            "AND asset_uid IS NULL AND target_uid = portfolio_uid"
            ")",
            name="ck_target_positions_target_reference",
        ),
        CheckConstraint(
            "("
            "CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END"
            ") + ("
            "CASE WHEN constant_notional_exposure IS NOT NULL THEN 1 ELSE 0 END"
            ") + ("
            "CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END"
            ") = 1",
            name="ck_target_positions_single_exposure",
        ),
        Index(None, "asset_uid"),
        Index(None, "portfolio_uid"),
        Index(None, "position_set_uid", "target_type", "target_uid"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "position_set_uid",
        "target_type",
        "target_uid",
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the target-allocation exposure snapshot.",
        },
    )
    position_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{PositionSetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Position Set UID",
            "description": (
                "PositionSetTable.uid for the account target-allocation snapshot "
                "that owns this exposure row."
            ),
        },
    )
    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Target Type",
            "description": "Target object kind for this exposure row: asset or portfolio.",
        },
    )
    target_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        info={
            "label": "Target UID",
            "description": (
                "Canonical non-null target identity. Matches asset_uid for asset "
                "rows and portfolio_uid for portfolio rows."
            ),
        },
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": (
                "AssetTable.uid when target_type is asset. Null for portfolio target rows."
            ),
        },
    )
    portfolio_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{PortfolioTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info={
            "label": "Portfolio UID",
            "description": (
                "PortfolioTable.uid when target_type is portfolio. Null for "
                "direct asset target rows."
            ),
        },
    )
    weight_notional_exposure: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Weight Notional Exposure",
            "description": "Target exposure as a notional portfolio weight when this exposure mode is used.",
        },
    )
    constant_notional_exposure: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Constant Notional Exposure",
            "description": "Target exposure as an absolute notional amount when this exposure mode is used.",
        },
    )
    single_asset_quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Single Asset Quantity",
            "description": "Target exposure as a direct quantity when this exposure mode is used.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSONB payload for target-allocation source, notes, or downstream routing hints.",
        },
    )

    @validates("target_type")
    def validate_target_type(self, _key: str, value: str) -> str:
        target_type = str(value)
        if target_type not in TARGET_POSITION_TARGET_TYPES:
            allowed = ", ".join(TARGET_POSITION_TARGET_TYPES)
            raise ValueError(f"target_type must be one of: {allowed}.")
        return target_type


__all__ = ["AccountHoldingsStorage", "TargetPositionsStorage"]
