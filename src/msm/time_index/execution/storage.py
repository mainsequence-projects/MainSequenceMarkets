"""Execution time-index-table output contracts."""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.accounts import AccountTable
from msm.models.assets.core import AssetTable
from msm.models.execution import OrderTable


def _execution_info(column_name: str) -> dict[str, str]:
    """Reproduce the legacy auto-generated execution label/description."""

    return {
        "label": column_name.replace("_", " ").title(),
        "description": (
            f"Execution storage field {column_name} published by the execution TimeIndexTableUpdater."
        ),
    }


class OrdersStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """An order's state over time, keyed by ``(order_time, order_uid)`` (ADR 0064).

    The order itself, with its account, asset, batch and terms, is its ``Order`` row.
    These rows hold what the venue reports.
    """

    __metatable_identifier__ = "OrdersTS"
    __metatable_description__ = (
        "Timestamped order-state storage keyed by order_time and order_uid. Used to "
        "persist what a broker or venue reports about an order over time; the order "
        "itself is its Order row."
    )
    # The unique index leads with order_time; this one serves one order's rows and the
    # foreign key into the order (ADR 0064).
    __table_args__ = (Index(None, "order_uid", "order_time"),)
    __time_index_name__: ClassVar[str] = "order_time"
    __index_names__: ClassVar[list[str]] = ["order_time", "order_uid"]

    order_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("order_time")
    )
    order_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{OrderTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info=_execution_info("order_uid"),
    )
    order_remote_id: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_remote_id")
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
    comments: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("comments")
    )
    venue_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("venue_metadata")
    )


class OrderEventsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped order status events keyed by ``(event_time, order_uid)``."""

    __metatable_identifier__ = "OrderEventsTS"
    __metatable_description__ = (
        "Timestamped order-event storage keyed by (event_time, order_uid). Used to "
        "persist status transitions and event metadata of an order."
    )
    # The unique index leads with event_time; this one serves one order's events and the
    # foreign key into the order.
    __table_args__ = (Index(None, "order_uid", "event_time"),)
    __time_index_name__: ClassVar[str] = "event_time"
    __index_names__: ClassVar[list[str]] = ["event_time", "order_uid"]

    event_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("event_time")
    )
    order_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{OrderTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info=_execution_info("order_uid"),
    )
    order_status: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("order_status")
    )
    event_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("event_metadata")
    )


class TradesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped trade execution records keyed by ``(trade_time, trade_identifier)``.

    A trade of an order names it by ``order_uid``; the key over ``(order_uid,
    account_identifier, asset_identifier)`` makes its account and asset the order's. A
    trade without an order has a null ``order_uid``, which the key does not check.
    """

    __metatable_identifier__ = "TradesTS"
    __metatable_description__ = (
        "Timestamped trade-execution storage keyed by trade_time and trade_identifier. "
        "Used to persist fills, prices, commissions, and settlement facts; a fill of an "
        "order names it by order_uid."
    )
    # The unique index leads with trade_time; these serve one account's trades and the
    # foreign keys that reference the account and the order.
    __table_args__ = (
        Index(None, "account_identifier", "trade_time"),
        Index(None, "order_uid"),
        ForeignKeyConstraint(
            ["order_uid", "account_identifier", "asset_identifier"],
            [
                f"{OrderTable.__table__.fullname}.uid",
                f"{OrderTable.__table__.fullname}.account_identifier",
                f"{OrderTable.__table__.fullname}.asset_identifier",
            ],
            ondelete="RESTRICT",
        ),
    )
    __time_index_name__: ClassVar[str] = "trade_time"
    __index_names__: ClassVar[list[str]] = ["trade_time", "trade_identifier"]

    trade_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info=_execution_info("trade_time")
    )
    trade_identifier: Mapped[str] = mapped_column(
        String, nullable=False, info=_execution_info("trade_identifier")
    )
    account_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AccountTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info=_execution_info("account_identifier"),
    )
    order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, info=_execution_info("order_uid")
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info=_execution_info("asset_identifier"),
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
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info=_execution_info("commission_asset_identifier"),
    )
    settlement_cost: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=_execution_info("settlement_cost")
    )
    settlement_asset_identifier: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info=_execution_info("settlement_asset_identifier"),
    )
    comments: Mapped[str | None] = mapped_column(
        String, nullable=True, info=_execution_info("comments")
    )
    venue_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, info=_execution_info("venue_metadata")
    )


__all__ = ["OrderEventsStorage", "OrdersStorage", "TradesStorage"]
