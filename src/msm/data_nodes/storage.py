"""Storage-first ``PlatformTimeIndexMetaData`` declarations for msm core/execution.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and identity foreign keys of one core/execution table.
The DataNode validators derive their column dtype maps from these declarations;
catalog registration follows in Stage 5.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, ClassVar

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import BigInteger, Boolean, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.accounts import AccountTable, PositionSetTable
from msm.models.assets.core import AssetTable


def _execution_info(column_name: str) -> dict[str, str]:
    """Reproduce the legacy auto-generated execution label/description."""

    return {
        "label": column_name.replace("_", " ").title(),
        "description": (
            f"Execution storage field {column_name} published by the execution DataNode."
        ),
    }


class AssetSnapshotsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped asset display snapshots keyed by asset unique identifier."""

    __markets_base_identifier__: ClassVar[str] = "AssetSnapshotsTS"
    __metatable_description__ = (
        "Timestamped asset display-fact storage keyed by (time_index, "
        "unique_identifier). Used by the AssetSnapshot DataNode to publish "
        "historical asset names, tickers, exchange codes, and share-class grouping "
        "without widening AssetTable."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "AssetSnapshotsTS",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the asset fact row."},
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        MetaTableForeignKey(
            AssetTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Asset unique identifier from the Asset MetaTable.",
        },
    )
    name: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Name",
            "description": "Security name as recorded by the asset data provider.",
        },
    )
    ticker: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={"label": "Ticker", "description": "Ticker or display symbol for the asset row."},
    )
    exchange_code: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Exchange Code",
            "description": "Exchange or market code for the asset row.",
        },
    )
    asset_ticker_group_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Asset Ticker Group ID",
            "description": "Highest aggregation level for share-class grouping.",
        },
    )


class AccountHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Account historical holdings keyed by account UID and held asset."""

    __markets_base_identifier__: ClassVar[str] = "AccountHoldingsTS"
    __metatable_description__ = (
        "Timestamped account holdings storage keyed by (time_index, account_uid, "
        "unique_identifier). Each row is one asset position in an account holdings "
        "observation, with optional trade-snapshot and provider metadata fields."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "AccountHoldingsTS",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "account_uid", "unique_identifier"]

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
        MetaTableForeignKey(
            AccountTable,
            column="uid",
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
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        MetaTableForeignKey(
            AssetTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Asset unique identifier for the held instrument at this account timestamp.",
        },
    )
    holdings_set_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Holdings Set UID",
            "description": "Stable UUID shared by rows written together as one account holdings set.",
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
            "description": "Position quantity held for this asset in the account snapshot.",
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
    """Reusable target position exposure rows keyed by position set UID."""

    __markets_base_identifier__: ClassVar[str] = "TargetPositionsTS"
    __metatable_description__ = (
        "Reusable target-position storage keyed by (time_index, position_set_uid, "
        "unique_identifier). Each row stores one target exposure instruction that "
        "belongs to a PositionSetTable row for an account target portfolio."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "TargetPositionsTS",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "position_set_uid", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "Stamped time index for the reusable target position row set.",
        },
    )
    position_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            PositionSetTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Position Set UID",
            "description": (
                "PositionSetTable.uid shared by rows in one concrete target-position set."
            ),
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String,
        MetaTableForeignKey(
            AssetTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "AssetTable.unique_identifier for the target exposure row.",
        },
    )
    weight_notional_exposure: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Weight Notional Exposure",
            "description": "Desired exposure expressed as an account weight.",
        },
    )
    constant_notional_exposure: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Constant Notional Exposure",
            "description": "Desired constant notional exposure in account currency.",
        },
    )
    single_asset_quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Single Asset Quantity",
            "description": "Desired direct single-asset quantity exposure.",
        },
    )


class OrdersStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped execution order records keyed by order_time."""

    __markets_base_identifier__: ClassVar[str] = "OrdersTS"
    __metatable_description__ = (
        "Timestamped execution-order storage keyed by order_time, "
        "order_unique_identifier, account_unique_identifier, and "
        "asset_unique_identifier. Used by execution DataNodes to persist broker or "
        "venue order state over time."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "OrdersTS",
    }
    __time_index_name__: ClassVar[str] = "order_time"
    __index_names__: ClassVar[list[str]] = [
        "order_time",
        "order_unique_identifier",
        "account_unique_identifier",
        "asset_unique_identifier",
    ]

    order_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("order_time")
    )
    order_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("order_unique_identifier")
    )
    account_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("account_unique_identifier")
    )
    fund_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("fund_unique_identifier")
    )
    order_manager_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_manager_unique_identifier")
    )
    asset_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("asset_unique_identifier")
    )
    order_remote_id: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_remote_id")
    )
    client_order_id: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("client_order_id")
    )
    order_type: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_type")
    )
    order_side: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, info=_execution_info("order_side")
    )
    quantity: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("quantity")
    )
    status: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("status")
    )
    filled_quantity: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("filled_quantity")
    )
    filled_price: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("filled_price")
    )
    expires_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, info=_execution_info("expires_time")
    )
    limit_price: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("limit_price")
    )
    time_in_force: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("time_in_force")
    )
    comments: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("comments")
    )
    venue_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("venue_metadata")
    )


class OrderEventsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped order status events keyed by event_time."""

    __markets_base_identifier__: ClassVar[str] = "OrderEventsTS"
    __metatable_description__ = (
        "Timestamped order-event storage keyed by (event_time, "
        "order_unique_identifier). Used by execution DataNodes to persist status "
        "transitions and event metadata for previously published orders."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "OrderEventsTS",
    }
    __time_index_name__: ClassVar[str] = "event_time"
    __index_names__: ClassVar[list[str]] = ["event_time", "order_unique_identifier"]

    event_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("event_time")
    )
    order_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("order_unique_identifier")
    )
    order_status: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_status")
    )
    event_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("event_metadata")
    )


class TradesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped trade execution records keyed by trade_time."""

    __markets_base_identifier__: ClassVar[str] = "TradesTS"
    __metatable_description__ = (
        "Timestamped trade-execution storage keyed by trade_time, "
        "trade_unique_identifier, account_unique_identifier, and "
        "asset_unique_identifier. Used by execution DataNodes to persist fills, "
        "prices, commissions, and settlement facts."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "TradesTS",
    }
    __time_index_name__: ClassVar[str] = "trade_time"
    __index_names__: ClassVar[list[str]] = [
        "trade_time",
        "trade_unique_identifier",
        "account_unique_identifier",
        "asset_unique_identifier",
    ]

    trade_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("trade_time")
    )
    trade_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("trade_unique_identifier")
    )
    account_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("account_unique_identifier")
    )
    fund_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("fund_unique_identifier")
    )
    order_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_unique_identifier")
    )
    asset_unique_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("asset_unique_identifier")
    )
    trade_side: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, info=_execution_info("trade_side")
    )
    quantity: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("quantity")
    )
    price: Mapped[float | None] = mapped_column(Float, nullable=True, info=_execution_info("price"))
    commission: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("commission")
    )
    commission_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("commission_asset_unique_identifier")
    )
    settlement_cost: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("settlement_cost")
    )
    settlement_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("settlement_asset_unique_identifier")
    )
    comments: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("comments")
    )
    venue_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("venue_metadata")
    )


__all__ = [
    "AccountHoldingsStorage",
    "AssetSnapshotsStorage",
    "OrderEventsStorage",
    "OrdersStorage",
    "TargetPositionsStorage",
    "TradesStorage",
]
