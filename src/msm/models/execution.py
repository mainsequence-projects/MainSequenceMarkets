from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .accounts import AccountTable
from .assets.core import AssetTable


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
            None,
            "unique_identifier",
            unique=True,
        ),
        Index(
            None,
            "target_account_uid",
        ),
        Index(
            None,
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
        ForeignKey(
            f"{AccountTable.__table__.fullname}.uid",
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


class OrderTable(MarketsMetaTableMixin, MarketsBase):
    """One order: its account, asset, batch and the terms it was created with (ADR 0064).

    ``uid`` is the order's own UUID, minted by the application that creates it and
    unique across accounts. A row never changes once written: what the venue reports
    over time is ``OrdersTS``, and a replaced order is a new order that names the one it
    replaces. ``OrdersTS``, ``OrderEventsTS`` and ``TradesTS`` reference it by ``uid``; a
    trade by ``(uid, account_identifier, asset_identifier)``, so a trade under an order
    has the order's account and asset.
    """

    __metatable_identifier__ = "Order"
    __metatable_description__ = (
        "Order registry keyed by uid, the order's own UUID. Stores the account, asset, "
        "order manager and the terms an order was created with; its state over time, "
        "events and fills reference it."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        # The target of the trades' key: a trade under an order has its account and asset.
        Index(None, "uid", "account_identifier", "asset_identifier", unique=True),
        Index(None, "account_identifier"),
        Index(None, "order_manager_identifier"),
        Index(None, "replaces_order_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "The order's own UUID, minted by the application that creates it.",
        },
    )
    account_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{AccountTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Account Identifier",
            "description": "Unique identifier of the account the order is for.",
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{AssetTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Unique identifier of the asset the order trades.",
        },
    )
    order_manager_identifier: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(
            f"{OrderManagerTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"
        ),
        nullable=True,
        info={
            "label": "Order Manager Identifier",
            "description": "Unique identifier of the order-manager batch that created the order.",
        },
    )
    replaces_order_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Replaces Order UID",
            "description": "The order this one replaces, of the same account and asset.",
        },
    )
    order_side: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        info={"label": "Order Side", "description": "Side of the order: 1 buys, -1 sells."},
    )
    order_type: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={"label": "Order Type", "description": "Order type, for example market or limit."},
    )
    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Quantity", "description": "Units the order asks for."},
    )
    limit_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Limit Price", "description": "Limit price of a limit order."},
    )
    time_in_force: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={"label": "Time In Force", "description": "How long the order stays working."},
    )
    expires_time: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={"label": "Expires Time", "description": "UTC time at which the order expires."},
    )
    client_order_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Client Order ID",
            "description": "The id the application sent the venue with the order.",
        },
    )


# A replacement names an order of its own account and asset. The key has no ON DELETE
# action, so it is checked at the end of each statement: deleting an account's orders
# deletes an order and its replacement in one statement. It targets the table's own
# unique index, which PostgreSQL needs before the key, so the key is added after it.
OrderTable.__table__.append_constraint(
    ForeignKeyConstraint(
        ["replaces_order_uid", "account_identifier", "asset_identifier"],
        [
            OrderTable.__table__.c.uid,
            OrderTable.__table__.c.account_identifier,
            OrderTable.__table__.c.asset_identifier,
        ],
        use_alter=True,
    )
)


__all__ = [
    "OrderManagerTable",
    "OrderTable",
]
