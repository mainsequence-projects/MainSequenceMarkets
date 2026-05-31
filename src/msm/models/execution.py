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
    markets_fk_name,
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
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    target_account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Account", "target_account_uid"),
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    target_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    order_received_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execution_end: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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
    )
    order_manager_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderManagerTable,
            column="uid",
            name=markets_fk_name(
                __metatable_identifier__,
                "OrderManager",
                "order_manager_uid",
            ),
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)


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
    )
    order_remote_id: Mapped[str] = mapped_column(String(100), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    order_type: Mapped[str] = mapped_column(String(100), nullable=False)
    order_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_side: Mapped[int] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="not_placed", nullable=False)
    filled_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18),
        default=Decimal("0"),
        nullable=True,
    )
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    order_manager_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderManagerTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "OrderManager", "order_manager_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    asset_unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Fund", "related_fund_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Account", "related_account_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    time_in_force: Mapped[str] = mapped_column(String(20), default="gtc", nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_specific_properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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
    )
    event_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    order_status: Mapped[str] = mapped_column(String(50), nullable=False)
    extra_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Order", "order_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    order_unique_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)


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
    )
    trade_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trade_side: Mapped[int] = mapped_column(nullable=False)
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    asset_unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Fund", "related_fund_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Account", "related_account_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    related_order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            OrderTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Order", "related_order_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_specific_properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    commission: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    commission_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    settlement_cost: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    settlement_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
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
    )
    error_code: Mapped[str] = mapped_column(String(50), nullable=False)
    error_traceback: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    related_account_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Account", "related_account_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    related_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Fund", "related_fund_uid"),
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    time_recorded: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = [
    "ExecutionErrorTable",
    "OrderManagerTable",
    "OrderStatusEventTable",
    "OrderTable",
    "OrderTargetQuantityTable",
    "TradeTable",
]
