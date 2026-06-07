"""Execution DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import BigInteger, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin


def _execution_info(column_name: str) -> dict[str, str]:
    """Reproduce the legacy auto-generated execution label/description."""

    return {
        "label": column_name.replace("_", " ").title(),
        "description": (
            f"Execution storage field {column_name} published by the execution DataNode."
        ),
    }


class OrdersStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped execution order records keyed by order_time."""

    __metatable_identifier__ = "OrdersTS"
    __metatable_description__ = (
        "Timestamped execution-order storage keyed by order_time, "
        "order_identifier, account_identifier, and "
        "asset_identifier. Used by execution DataNodes to persist broker or "
        "venue order state over time."
    )
    __time_index_name__: ClassVar[str] = "order_time"
    __index_names__: ClassVar[list[str]] = [
        "order_time",
        "order_identifier",
        "account_identifier",
        "asset_identifier",
    ]

    order_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("order_time")
    )
    order_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("order_identifier")
    )
    account_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("account_identifier")
    )
    fund_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("fund_identifier")
    )
    order_manager_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_manager_identifier")
    )
    asset_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("asset_identifier")
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

    __metatable_identifier__ = "OrderEventsTS"
    __metatable_description__ = (
        "Timestamped order-event storage keyed by (event_time, "
        "order_identifier). Used by execution DataNodes to persist status "
        "transitions and event metadata for previously published orders."
    )
    __time_index_name__: ClassVar[str] = "event_time"
    __index_names__: ClassVar[list[str]] = ["event_time", "order_identifier"]

    event_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("event_time")
    )
    order_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("order_identifier")
    )
    order_status: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_status")
    )
    event_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("event_metadata")
    )


class TradesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped trade execution records keyed by trade_time."""

    __metatable_identifier__ = "TradesTS"
    __metatable_description__ = (
        "Timestamped trade-execution storage keyed by trade_time, "
        "trade_identifier, account_identifier, and "
        "asset_identifier. Used by execution DataNodes to persist fills, "
        "prices, commissions, and settlement facts."
    )
    __time_index_name__: ClassVar[str] = "trade_time"
    __index_names__: ClassVar[list[str]] = [
        "trade_time",
        "trade_identifier",
        "account_identifier",
        "asset_identifier",
    ]

    trade_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("trade_time")
    )
    trade_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("trade_identifier")
    )
    account_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("account_identifier")
    )
    fund_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("fund_identifier")
    )
    order_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_identifier")
    )
    asset_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("asset_identifier")
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
    commission_asset_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("commission_asset_identifier")
    )
    settlement_cost: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("settlement_cost")
    )
    settlement_asset_identifier: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("settlement_asset_identifier")
    )
    comments: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("comments")
    )
    venue_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("venue_metadata")
    )


__all__ = ["OrderEventsStorage", "OrdersStorage", "TradesStorage"]
