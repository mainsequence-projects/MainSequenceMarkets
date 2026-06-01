from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow, Payload
from msm.models import (
    AccountTable,
    AssetTable,
    OrderManagerTable,
)

EXECUTION_REQUIRED_TABLES: list[type[Any]] = [
    AssetTable,
    AccountTable,
    OrderManagerTable,
]


class OrderManager(MarketsMetaTableRow):
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


__all__ = [
    "OrderManager",
    "OrderManagerCreate",
    "OrderManagerUpdate",
    "OrderManagerUpsert",
]
