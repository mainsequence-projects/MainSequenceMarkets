from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from msm.api.base import MarketsMetaTableRow, Payload, _payload_values, operation_result_rows
from msm.models import (
    AccountTable,
    AssetTable,
    OrderManagerTable,
    OrderTable,
)

EXECUTION_REQUIRED_TABLES: list[type[Any]] = [
    AssetTable,
    AccountTable,
    OrderManagerTable,
    OrderTable,
]

_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")


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
    def create_batch(
        cls,
        payload: Payload = None,
        *,
        orders: Sequence[OrderCreate | Mapping[str, Any]] = (),
        **kwargs: Any,
    ) -> OrderBatch:
        """Create or update a batch by unique identifier, and create its ``orders``, in one
        transaction (ADR 0064).

        Each order is an ``OrderCreate``: its ``uid`` is the order's own UUID, minted by
        the caller and unique across accounts. Its ``order_manager_identifier`` is the
        batch's. An order is written once: one that exists already is left as it is, so
        sending a batch again writes no order twice.

        Every order that may be written is (issue 128): one that fails validation, or
        that the database refuses (an unknown account or asset, a replaced order of
        another account), is listed in ``failed`` and the others are written.
        """

        manager = OrderManagerUpsert.model_validate(_payload_values(payload, kwargs))
        manager_values = manager.model_dump(exclude_unset=True)
        manager_values["target_account_uid"] = uuid.UUID(str(manager.target_account_uid))
        accepted: list[OrderCreate] = []
        failed: list[OrderRefusal] = []
        seen: set[uuid.UUID] = set()
        for position, entry in enumerate(orders):
            try:
                order = OrderCreate.model_validate(
                    entry.model_dump(exclude_unset=True) if isinstance(entry, BaseModel) else entry
                )
            except ValidationError as exc:
                failed.append(OrderRefusal(uid=_entry_uid(entry), position=position, detail=str(exc)))
                continue
            if order.order_manager_identifier not in (None, manager.unique_identifier):
                failed.append(
                    OrderRefusal(
                        uid=order.uid,
                        position=position,
                        detail=(
                            f"order_manager_identifier {order.order_manager_identifier!r} is not "
                            f"the batch's {manager.unique_identifier!r}."
                        ),
                    )
                )
                continue
            if order.uid in seen:
                failed.append(
                    OrderRefusal(uid=order.uid, position=position, detail="Its uid repeats in the call.")
                )
                continue
            seen.add(order.uid)
            accepted.append(order)

        manager_row, written, refused = _write_batch(cls._active_context(), manager_values, accepted)
        failed.extend(refused)
        return OrderBatch(
            order_manager=cls.model_validate(manager_row),
            orders=[
                Order.model_validate(_order_values(order, manager.unique_identifier))
                for order in written
            ],
            failed=failed,
        )


class Order(MarketsMetaTableRow):
    """One order: its account, asset, batch and the terms it was created with (ADR 0064).

    Orders are created with their batch, ``OrderManager.create_batch``, and never change.
    What happens to an order afterwards is written with ``write_execution``.
    """

    __table__: ClassVar[type[OrderTable]] = OrderTable
    __required_tables__: ClassVar[list[type[Any]]] = EXECUTION_REQUIRED_TABLES
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("uid",)
    __delete_refusal__: ClassVar[str | None] = (
        "An order is deleted with its account's history (ADR 0050), never on its own."
    )

    account_identifier: str
    asset_identifier: str
    order_manager_identifier: str | None = None
    replaces_order_uid: uuid.UUID | None = None
    order_side: int | None = None
    order_type: str | None = None
    quantity: float | None = None
    limit_price: float | None = None
    time_in_force: str | None = None
    expires_time: dt.datetime | None = None
    client_order_id: str | None = None


class OrderCreate(BaseModel):
    """An order of a batch, as ``OrderManager.create_batch`` takes it."""

    model_config = ConfigDict(extra="forbid")

    uid: uuid.UUID
    account_identifier: str = Field(min_length=1, max_length=255)
    asset_identifier: str = Field(min_length=1, max_length=255)
    order_manager_identifier: str | None = Field(default=None, max_length=255)
    replaces_order_uid: uuid.UUID | None = None
    order_side: int | None = None
    order_type: str | None = None
    quantity: float | None = None
    limit_price: float | None = None
    time_in_force: str | None = None
    expires_time: dt.datetime | None = None
    client_order_id: str | None = None


class OrderRefusal(BaseModel):
    """An order ``create_batch`` did not write, and why."""

    uid: uuid.UUID | None = None
    position: int | None = None
    detail: str


class OrderBatch(BaseModel):
    """What ``OrderManager.create_batch`` wrote: the batch, its orders, and the refused ones."""

    order_manager: OrderManager
    orders: list[Order] = Field(default_factory=list)
    failed: list[OrderRefusal] = Field(default_factory=list)


def _entry_uid(entry: Any) -> uuid.UUID | None:
    value = entry.get("uid") if isinstance(entry, Mapping) else getattr(entry, "uid", None)
    try:
        return uuid.UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def _order_values(order: OrderCreate, manager_identifier: str) -> dict[str, Any]:
    return {**order.model_dump(), "order_manager_identifier": manager_identifier}


def _write_batch(
    context: Any, manager: Mapping[str, Any], orders: Sequence[OrderCreate]
) -> tuple[dict[str, Any], list[OrderCreate], list[OrderRefusal]]:
    """Write the batch with ``orders`` in one transaction; when the database refuses it,
    nothing was written, and the batch is written alone, then each order with it."""

    from msm.repositories.execution import write_order_batch

    identifier = str(manager["unique_identifier"])

    def write(batch_orders: Sequence[OrderCreate]) -> dict[str, Any]:
        result = write_order_batch(
            context,
            order_manager=manager,
            orders=[_order_values(order, identifier) for order in batch_orders],
        )
        return operation_result_rows(result)[0]

    try:
        return write(orders), list(orders), []
    except Exception as exc:
        if not orders or not _is_refusal(exc):
            raise
        if len(orders) == 1:
            return write([]), [], [OrderRefusal(uid=orders[0].uid, detail=str(exc))]
    manager_row = write([])
    written: list[OrderCreate] = []
    refused: list[OrderRefusal] = []
    for order in orders:
        try:
            manager_row = write([order])
        except Exception as exc:
            if not _is_refusal(exc):
                raise
            refused.append(OrderRefusal(uid=order.uid, detail=str(exc)))
            continue
        written.append(order)
    return manager_row, written, refused


def _is_refusal(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


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
    "Order",
    "OrderBatch",
    "OrderCreate",
    "OrderManager",
    "OrderManagerCreate",
    "OrderManagerUpdate",
    "OrderManagerUpsert",
    "OrderRefusal",
]
