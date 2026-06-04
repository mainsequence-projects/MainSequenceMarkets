from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .accounts import AccountTable


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


__all__ = [
    "OrderManagerTable",
]
