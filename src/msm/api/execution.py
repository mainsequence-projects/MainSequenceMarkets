from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsRow, Payload
from msm.models import (
    AccountTable,
    AssetTable,
    ExecutionErrorTable,
    FundTable,
    OrderManagerTable,
    OrderStatusEventTable,
    OrderTable,
    OrderTargetQuantityTable,
    PortfolioTable,
    TradeTable,
)

EXECUTION_REQUIRED_TABLES: list[type[Any]] = [
    AssetTable,
    AccountTable,
    PortfolioTable,
    FundTable,
    OrderManagerTable,
    OrderTargetQuantityTable,
    OrderTable,
    OrderStatusEventTable,
    TradeTable,
    ExecutionErrorTable,
]


class OrderManager(MarketsRow):
    """Typed order-manager or rebalance execution batch row."""

    __table__: ClassVar[type[OrderManagerTable]] = OrderManagerTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    target_account_uid: uuid.UUID
    target_time: dt.datetime
    order_received_time: dt.datetime | None = None
    execution_end: dt.datetime | None = None
    status: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create_batch(cls, payload: Payload = None, **kwargs: Any) -> OrderManager:
        """Create or update an order-manager batch by unique identifier."""

        return cls.upsert(payload, **kwargs)


class OrderManagerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    target_account_uid: uuid.UUID | str
    target_time: dt.datetime
    order_received_time: dt.datetime | None = None
    execution_end: dt.datetime | None = None
    status: str | None = Field(default=None, max_length=64)
    metadata_json: dict[str, Any] | None = None


class OrderManagerUpsert(OrderManagerCreate):
    """Payload for inserting or updating an order-manager batch."""


class OrderManagerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_received_time: dt.datetime | None = None
    execution_end: dt.datetime | None = None
    status: str | None = Field(default=None, max_length=64)
    metadata_json: dict[str, Any] | None = None


class OrderTargetQuantity(MarketsRow):
    """Typed target quantity row inside an order-manager batch."""

    __table__: ClassVar[type[OrderTargetQuantityTable]] = OrderTargetQuantityTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("order_manager_uid", "asset_uid")

    order_manager_uid: uuid.UUID
    asset_uid: uuid.UUID
    quantity: Decimal


class OrderTargetQuantityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_manager_uid: uuid.UUID | str
    asset_uid: uuid.UUID | str
    quantity: Decimal | int | float | str


class OrderTargetQuantityUpsert(OrderTargetQuantityCreate):
    """Payload for inserting or updating a target quantity."""


class OrderTargetQuantityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal | int | float | str | None = None


class Order(MarketsRow):
    """Typed broker or venue order row."""

    __table__: ClassVar[type[OrderTable]] = OrderTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "order_time",
        "order_remote_id",
        "asset_unique_identifier",
    )

    order_remote_id: str
    client_order_id: str
    order_type: str
    order_time: dt.datetime
    expires_time: dt.datetime | None = None
    order_side: int
    quantity: Decimal
    status: str = "not_placed"
    filled_quantity: Decimal | None = Decimal("0")
    filled_price: Decimal | None = None
    order_manager_uid: uuid.UUID | None = None
    asset_uid: uuid.UUID | None = None
    asset_unique_identifier: str
    related_fund_uid: uuid.UUID | None = None
    related_account_uid: uuid.UUID | None = None
    time_in_force: str = "gtc"
    limit_price: Decimal | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None

    @classmethod
    def record_status(
        cls,
        *,
        order_status: str,
        event_time: dt.datetime | None = None,
        order_uid: uuid.UUID | str | None = None,
        order_unique_identifier: str | None = None,
        extra_info: dict[str, Any] | None = None,
    ) -> OrderStatusEvent:
        """Append a status event for an order lifecycle."""

        return OrderStatusEvent.create(
            event_time=event_time or dt.datetime.now(dt.UTC),
            order_status=order_status,
            extra_info=extra_info,
            order_uid=order_uid,
            order_unique_identifier=order_unique_identifier,
        )


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_remote_id: str = Field(min_length=1, max_length=100)
    client_order_id: str = Field(min_length=1, max_length=100)
    order_type: str = Field(min_length=1, max_length=100)
    order_time: dt.datetime
    expires_time: dt.datetime | None = None
    order_side: int
    quantity: Decimal | int | float | str
    status: str = "not_placed"
    filled_quantity: Decimal | int | float | str | None = Decimal("0")
    filled_price: Decimal | int | float | str | None = None
    order_manager_uid: uuid.UUID | str | None = None
    asset_uid: uuid.UUID | str | None = None
    asset_unique_identifier: str = Field(min_length=1, max_length=255)
    related_fund_uid: uuid.UUID | str | None = None
    related_account_uid: uuid.UUID | str | None = None
    time_in_force: str = "gtc"
    limit_price: Decimal | int | float | str | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None


class OrderUpsert(OrderCreate):
    """Payload for inserting or updating a broker or venue order."""


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_time: dt.datetime | None = None
    status: str | None = Field(default=None, max_length=50)
    filled_quantity: Decimal | int | float | str | None = None
    filled_price: Decimal | int | float | str | None = None
    order_manager_uid: uuid.UUID | str | None = None
    asset_uid: uuid.UUID | str | None = None
    related_fund_uid: uuid.UUID | str | None = None
    related_account_uid: uuid.UUID | str | None = None
    time_in_force: str | None = Field(default=None, max_length=20)
    limit_price: Decimal | int | float | str | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None


class OrderStatusEvent(MarketsRow):
    """Typed append-only order status event row."""

    __table__: ClassVar[type[OrderStatusEventTable]] = OrderStatusEventTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES

    event_time: dt.datetime
    order_status: str
    extra_info: dict[str, Any] | None = None
    order_uid: uuid.UUID | None = None
    order_unique_identifier: str | None = None

    @classmethod
    def record(cls, payload: Payload = None, **kwargs: Any) -> OrderStatusEvent:
        """Append one order-status event."""

        return cls.create(payload, **kwargs)


class OrderStatusEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_time: dt.datetime
    order_status: str = Field(min_length=1, max_length=50)
    extra_info: dict[str, Any] | None = None
    order_uid: uuid.UUID | str | None = None
    order_unique_identifier: str | None = Field(default=None, max_length=255)


class Trade(MarketsRow):
    """Typed executed trade row."""

    __table__: ClassVar[type[TradeTable]] = TradeTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "trade_time",
        "asset_unique_identifier",
        "related_account_uid",
    )

    trade_time: dt.datetime
    trade_side: int
    asset_uid: uuid.UUID | None = None
    asset_unique_identifier: str
    quantity: Decimal
    price: Decimal
    related_fund_uid: uuid.UUID | None = None
    related_account_uid: uuid.UUID | None = None
    related_order_uid: uuid.UUID | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None
    commission: Decimal | None = None
    commission_asset_unique_identifier: str | None = None
    settlement_cost: Decimal | None = None
    settlement_asset_unique_identifier: str | None = None


class TradeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_time: dt.datetime
    trade_side: int
    asset_uid: uuid.UUID | str | None = None
    asset_unique_identifier: str = Field(min_length=1, max_length=255)
    quantity: Decimal | int | float | str
    price: Decimal | int | float | str
    related_fund_uid: uuid.UUID | str | None = None
    related_account_uid: uuid.UUID | str | None = None
    related_order_uid: uuid.UUID | str | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None
    commission: Decimal | int | float | str | None = None
    commission_asset_unique_identifier: str | None = Field(default=None, max_length=255)
    settlement_cost: Decimal | int | float | str | None = None
    settlement_asset_unique_identifier: str | None = Field(default=None, max_length=255)


class TradeUpsert(TradeCreate):
    """Payload for inserting or updating a trade row."""


class TradeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    related_fund_uid: uuid.UUID | str | None = None
    related_account_uid: uuid.UUID | str | None = None
    related_order_uid: uuid.UUID | str | None = None
    comments: str | None = None
    venue_specific_properties: dict[str, Any] | None = None
    commission: Decimal | int | float | str | None = None
    commission_asset_unique_identifier: str | None = Field(default=None, max_length=255)
    settlement_cost: Decimal | int | float | str | None = None
    settlement_asset_unique_identifier: str | None = Field(default=None, max_length=255)


class ExecutionError(MarketsRow):
    """Typed execution error row."""

    __table__: ClassVar[type[ExecutionErrorTable]] = ExecutionErrorTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES

    error_code: str
    error_traceback: str
    error_message: str
    related_account_uid: uuid.UUID | None = None
    related_fund_uid: uuid.UUID | None = None
    time_recorded: dt.datetime
    metadata_json: dict[str, Any] | None = None


class ExecutionErrorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(min_length=1, max_length=50)
    error_traceback: str
    error_message: str
    related_account_uid: uuid.UUID | str | None = None
    related_fund_uid: uuid.UUID | str | None = None
    time_recorded: dt.datetime
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "ExecutionError",
    "ExecutionErrorCreate",
    "Order",
    "OrderCreate",
    "OrderManager",
    "OrderManagerCreate",
    "OrderManagerUpdate",
    "OrderManagerUpsert",
    "OrderStatusEvent",
    "OrderStatusEventCreate",
    "OrderTargetQuantity",
    "OrderTargetQuantityCreate",
    "OrderTargetQuantityUpdate",
    "OrderTargetQuantityUpsert",
    "OrderUpdate",
    "OrderUpsert",
    "Trade",
    "TradeCreate",
    "TradeUpdate",
    "TradeUpsert",
]
