from __future__ import annotations

import uuid
import datetime as dt
from decimal import Decimal

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import DateTime, Index, Numeric, String, Text
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
from .assets import AssetTable
from .funds import FundTable


class OrderManagerTable(MarketsMetaTableMixin, MarketsBase):
    """Order-manager or rebalance execution batch row."""

    __metatable_identifier__ = "OrderManager"
    __metatable_description__ = (
        "Execution batch registry keyed by unique_identifier. Stores target account, "
        "target time, received/end times, status, and metadata for rebalance or "
        "order-manager workflows."
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
            markets_index_name(__metatable_identifier__, "status"),
            "status",
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
    target_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Target Time",
            "description": "UTC timestamp targeted by an execution or rebalance workflow.",
        },
    )
    order_received_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Order Received Time",
            "description": "UTC timestamp when the order-manager workflow received the order set.",
        },
    )
    execution_end: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Execution End",
            "description": "UTC timestamp when the execution batch completed.",
        },
    )
    status: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Status",
            "description": "Lifecycle or execution status value for the row.",
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


class OrderTargetQuantityTable(MarketsMetaTableMixin, MarketsBase):
    """Target quantity for one asset inside an order-manager batch."""

    __metatable_identifier__ = "OrderTargetQuantity"
    __metatable_description__ = (
        "Order-manager target quantity table keyed by order_manager_uid and "
        "asset_uid. Stores the desired quantity for one asset inside an execution "
        "batch."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "order_manager_uid",
                "asset_uid",
                unique=True,
            ),
            "order_manager_uid",
            "asset_uid",
            unique=True,
        ),
        Index(markets_index_name(__metatable_identifier__, "asset_uid"), "asset_uid"),
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
    order_manager_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderManagerTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Order Manager UID",
            "description": "Foreign key to OrderManagerTable.uid for the execution batch.",
        },
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        nullable=False,
        info={
            "label": "Quantity",
            "description": "Position, target, order, or trade quantity for the row.",
        },
    )


class OrderTable(MarketsMetaTableMixin, MarketsBase):
    """Broker or venue order emitted by a markets execution workflow."""

    __metatable_identifier__ = "Order"
    __metatable_description__ = (
        "Broker or venue order table keyed by order_time, order_remote_id, and "
        "asset_unique_identifier. Stores order intent, status, fills, related "
        "account/fund/order-manager links, and venue metadata."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "order_time",
                "order_remote_id",
                "asset_unique_identifier",
                unique=True,
            ),
            "order_time",
            "order_remote_id",
            "asset_unique_identifier",
            unique=True,
        ),
        Index(markets_index_name(__metatable_identifier__, "client_order_id"), "client_order_id"),
        Index(markets_index_name(__metatable_identifier__, "status"), "status"),
        Index(
            markets_index_name(__metatable_identifier__, "order_manager_uid"),
            "order_manager_uid",
        ),
        Index(markets_index_name(__metatable_identifier__, "asset_uid"), "asset_uid"),
        Index(markets_index_name(__metatable_identifier__, "related_fund_uid"), "related_fund_uid"),
        Index(
            markets_index_name(__metatable_identifier__, "related_account_uid"),
            "related_account_uid",
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
    order_remote_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        info={
            "label": "Order Remote ID",
            "description": "Execution venue or broker order identifier.",
        },
    )
    client_order_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        info={
            "label": "Client Order ID",
            "description": "Client-side order identifier submitted to an execution venue.",
        },
    )
    order_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        info={
            "label": "Order Type",
            "description": "Execution order type, such as market, limit, or venue-specific type.",
        },
    )
    order_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Order Time",
            "description": "UTC timestamp when the order was created or submitted.",
        },
    )
    expires_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Expires Time",
            "description": "UTC timestamp when an order expires if not filled.",
        },
    )
    order_side: Mapped[int] = mapped_column(
        nullable=False,
        info={
            "label": "Order Side",
            "description": "Side of the order as represented by the execution workflow.",
        },
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        nullable=False,
        info={
            "label": "Quantity",
            "description": "Position, target, order, or trade quantity for the row.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="not_placed",
        nullable=False,
        info={
            "label": "Status",
            "description": "Lifecycle or execution status value for the row.",
        },
    )
    filled_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        default=Decimal("0"),
        nullable=True,
        info={
            "label": "Filled Quantity",
            "description": "Quantity filled for the order.",
        },
    )
    filled_price: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        nullable=True,
        info={
            "label": "Filled Price",
            "description": "Average filled price recorded for the order.",
        },
    )
    order_manager_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderManagerTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Order Manager UID",
            "description": "Foreign key to OrderManagerTable.uid for the execution batch.",
        },
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    asset_unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Asset Unique Identifier",
            "description": "Stable AssetTable.unique_identifier value captured for provider payloads, joins, or denormalized display.",
        },
    )
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Fund UID",
            "description": "Foreign key to FundTable.uid for the related fund when applicable.",
        },
    )
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Account UID",
            "description": "Foreign key to AccountTable.uid for the related account when applicable.",
        },
    )
    time_in_force: Mapped[str] = mapped_column(
        String(20),
        default="gtc",
        nullable=False,
        info={
            "label": "Time In Force",
            "description": "Order time-in-force instruction for venue execution.",
        },
    )
    limit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        nullable=True,
        info={
            "label": "Limit Price",
            "description": "Limit price attached to the order when applicable.",
        },
    )
    comments: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Comments",
            "description": "Free-form comments recorded for execution or trade review.",
        },
    )
    venue_specific_properties: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Venue Specific Properties",
            "description": "Structured venue-specific execution properties for this order.",
        },
    )


class OrderStatusEventTable(MarketsMetaTableMixin, MarketsBase):
    """Status transition event observed for an order."""

    __metatable_identifier__ = "OrderStatusEvent"
    __metatable_description__ = (
        "Order status event table keyed by event_time and "
        "order_uid/order_unique_identifier. Stores the observed status transition "
        "stream for broker or venue orders."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(markets_index_name(__metatable_identifier__, "event_time"), "event_time"),
        Index(markets_index_name(__metatable_identifier__, "order_status"), "order_status"),
        Index(markets_index_name(__metatable_identifier__, "order_uid"), "order_uid"),
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
    event_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Event Time",
            "description": "UTC timestamp when the order status event was observed.",
        },
    )
    order_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        info={
            "label": "Order Status",
            "description": "Order status value reported for this event.",
        },
    )
    extra_info: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Extra Info",
            "description": "Structured provider or workflow details attached to the event row.",
        },
    )
    order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Order UID",
            "description": "Foreign key to OrderTable.uid for the order that produced this status event.",
        },
    )
    order_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Order Unique Identifier",
            "description": "Stable external identifier for the order associated with this event.",
        },
    )


class TradeTable(MarketsMetaTableMixin, MarketsBase):
    """Executed trade produced by a broker or venue."""

    __metatable_identifier__ = "Trade"
    __metatable_description__ = (
        "Executed trade table keyed by trade_time, asset_unique_identifier, and "
        "related account or fund. Stores fills, prices, commissions, settlement "
        "fields, and links back to order/account/fund records."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "trade_time",
                "asset_unique_identifier",
                "related_account_uid",
                unique=True,
            ),
            "trade_time",
            "asset_unique_identifier",
            "related_account_uid",
            unique=True,
        ),
        Index(markets_index_name(__metatable_identifier__, "asset_uid"), "asset_uid"),
        Index(
            markets_index_name(__metatable_identifier__, "asset_unique_identifier"),
            "asset_unique_identifier",
        ),
        Index(markets_index_name(__metatable_identifier__, "related_fund_uid"), "related_fund_uid"),
        Index(
            markets_index_name(__metatable_identifier__, "related_account_uid"),
            "related_account_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "related_order_uid"), "related_order_uid"
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
    trade_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Trade Time",
            "description": "UTC timestamp when the trade was executed.",
        },
    )
    trade_side: Mapped[int] = mapped_column(
        nullable=False,
        info={
            "label": "Trade Side",
            "description": "Side of the executed trade as represented by the execution workflow.",
        },
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    asset_unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Asset Unique Identifier",
            "description": "Stable AssetTable.unique_identifier value captured for provider payloads, joins, or denormalized display.",
        },
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        nullable=False,
        info={
            "label": "Quantity",
            "description": "Position, target, order, or trade quantity for the row.",
        },
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        nullable=False,
        info={
            "label": "Price",
            "description": "Execution price recorded for a trade.",
        },
    )
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Fund UID",
            "description": "Foreign key to FundTable.uid for the related fund when applicable.",
        },
    )
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Account UID",
            "description": "Foreign key to AccountTable.uid for the related account when applicable.",
        },
    )
    related_order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Order UID",
            "description": "Foreign key to OrderTable.uid for the related order when applicable.",
        },
    )
    comments: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Comments",
            "description": "Free-form comments recorded for execution or trade review.",
        },
    )
    venue_specific_properties: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Venue Specific Properties",
            "description": "Structured venue-specific execution properties for this trade.",
        },
    )
    commission: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        nullable=True,
        info={
            "label": "Commission",
            "description": "Commission amount charged for the executed trade.",
        },
    )
    commission_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Commission Asset Unique Identifier",
            "description": "Asset unique identifier for the currency or asset in which commission is charged.",
        },
    )
    settlement_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        nullable=True,
        info={
            "label": "Settlement Cost",
            "description": "Settlement cost amount recorded for the trade.",
        },
    )
    settlement_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Settlement Asset Unique Identifier",
            "description": "Asset unique identifier for trade settlement costs.",
        },
    )


class ExecutionErrorTable(MarketsMetaTableMixin, MarketsBase):
    """Execution error captured by an order or broker integration."""

    __metatable_identifier__ = "ExecutionError"
    __metatable_description__ = (
        "Execution error table keyed by error_code and time_recorded. Stores broker "
        "or execution workflow failures with related account, fund, and diagnostic "
        "metadata."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(markets_index_name(__metatable_identifier__, "error_code"), "error_code"),
        Index(
            markets_index_name(__metatable_identifier__, "related_account_uid"),
            "related_account_uid",
        ),
        Index(markets_index_name(__metatable_identifier__, "related_fund_uid"), "related_fund_uid"),
        Index(markets_index_name(__metatable_identifier__, "time_recorded"), "time_recorded"),
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
    error_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        info={
            "label": "Error Code",
            "description": "Execution error code assigned by the workflow or execution venue.",
        },
    )
    error_traceback: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        info={
            "label": "Error Traceback",
            "description": "Captured traceback or diagnostic text for an execution error.",
        },
    )
    error_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        info={
            "label": "Error Message",
            "description": "Human-readable execution error message for diagnostics.",
        },
    )
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Account UID",
            "description": "Foreign key to AccountTable.uid for the related account when applicable.",
        },
    )
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Related Fund UID",
            "description": "Foreign key to FundTable.uid for the related fund when applicable.",
        },
    )
    time_recorded: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Recorded",
            "description": "UTC timestamp when the error or observation was recorded.",
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


__all__ = [
    "ExecutionErrorTable",
    "OrderManagerTable",
    "OrderStatusEventTable",
    "OrderTable",
    "OrderTargetQuantityTable",
    "TradeTable",
]
