from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import (
    ExecutionErrorTable,
    OrderTable,
    OrderManagerTable,
    OrderStatusEventTable,
    OrderTargetQuantityTable,
    TradeTable,
)

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    target_account_uid: uuid.UUID | str,
    target_time: dt.datetime,
    order_received_time: dt.datetime | None = None,
    execution_end: dt.datetime | None = None,
    status: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=OrderManagerTable,
        values={
            "unique_identifier": unique_identifier,
            "target_account_uid": target_account_uid,
            "target_time": target_time,
            "order_received_time": order_received_time,
            "execution_end": execution_end,
            "status": status,
            "metadata_json": metadata_json,
        },
    )


def build_search_order_managers_operation(
    context: MarketsRepositoryContext,
    *,
    target_account_uid: uuid.UUID | str | None = None,
    status: str | None = None,
    unique_identifier_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if target_account_uid is not None:
        filters["target_account_uid"] = target_account_uid
    if status not in (None, ""):
        filters["status"] = status
    return build_search_model_operation(
        context,
        model=OrderManagerTable,
        filters=filters,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
        limit=limit,
    )


def build_update_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(context, model=OrderManagerTable, uid=uid, values=values)


def build_delete_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=OrderManagerTable, uid=uid)


def build_create_order_target_quantity_operation(
    context: MarketsRepositoryContext,
    *,
    order_manager_uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str,
    quantity: Decimal | int | float | str,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=OrderTargetQuantityTable,
        values={
            "order_manager_uid": order_manager_uid,
            "asset_uid": asset_uid,
            "quantity": quantity,
        },
    )


def build_search_order_target_quantities_operation(
    context: MarketsRepositoryContext,
    *,
    order_manager_uid: uuid.UUID | str | None = None,
    asset_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if order_manager_uid is not None:
        filters["order_manager_uid"] = order_manager_uid
    if asset_uid is not None:
        filters["asset_uid"] = asset_uid
    return build_search_model_operation(
        context,
        model=OrderTargetQuantityTable,
        filters=filters,
        limit=limit,
    )


def build_create_order_operation(
    context: MarketsRepositoryContext,
    *,
    order_remote_id: str,
    client_order_id: str,
    order_type: str,
    order_time: dt.datetime,
    order_side: int,
    quantity: Decimal | int | float | str,
    asset_unique_identifier: str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    payload = dict(values)
    payload.update(
        {
            "order_remote_id": order_remote_id,
            "client_order_id": client_order_id,
            "order_type": order_type,
            "order_time": order_time,
            "order_side": order_side,
            "quantity": quantity,
            "asset_unique_identifier": asset_unique_identifier,
        }
    )
    return build_create_model_operation(context, model=OrderTable, values=payload)


def build_search_orders_operation(
    context: MarketsRepositoryContext,
    *,
    order_manager_uid: uuid.UUID | str | None = None,
    asset_uid: uuid.UUID | str | None = None,
    related_account_uid: uuid.UUID | str | None = None,
    status: str | None = None,
    asset_unique_identifier: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "order_manager_uid": order_manager_uid,
        "asset_uid": asset_uid,
        "related_account_uid": related_account_uid,
        "status": status,
        "asset_unique_identifier": asset_unique_identifier,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(context, model=OrderTable, filters=filters, limit=limit)


def build_update_order_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(context, model=OrderTable, uid=uid, values=values)


def build_create_order_status_event_operation(
    context: MarketsRepositoryContext,
    *,
    event_time: dt.datetime,
    order_status: str,
    extra_info: dict[str, Any] | None = None,
    order_uid: uuid.UUID | str | None = None,
    order_unique_identifier: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=OrderStatusEventTable,
        values={
            "event_time": event_time,
            "order_status": order_status,
            "extra_info": extra_info,
            "order_uid": order_uid,
            "order_unique_identifier": order_unique_identifier,
        },
    )


def build_search_order_status_events_operation(
    context: MarketsRepositoryContext,
    *,
    order_uid: uuid.UUID | str | None = None,
    order_status: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if order_uid is not None:
        filters["order_uid"] = order_uid
    if order_status not in (None, ""):
        filters["order_status"] = order_status
    return build_search_model_operation(
        context,
        model=OrderStatusEventTable,
        filters=filters,
        limit=limit,
    )


def build_create_trade_operation(
    context: MarketsRepositoryContext,
    *,
    trade_time: dt.datetime,
    trade_side: int,
    asset_unique_identifier: str,
    quantity: Decimal | int | float | str,
    price: Decimal | int | float | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    payload = dict(values)
    payload.update(
        {
            "trade_time": trade_time,
            "trade_side": trade_side,
            "asset_unique_identifier": asset_unique_identifier,
            "quantity": quantity,
            "price": price,
        }
    )
    return build_create_model_operation(context, model=TradeTable, values=payload)


def build_search_trades_operation(
    context: MarketsRepositoryContext,
    *,
    asset_uid: uuid.UUID | str | None = None,
    asset_unique_identifier: str | None = None,
    related_account_uid: uuid.UUID | str | None = None,
    related_order_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "asset_uid": asset_uid,
        "asset_unique_identifier": asset_unique_identifier,
        "related_account_uid": related_account_uid,
        "related_order_uid": related_order_uid,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(context, model=TradeTable, filters=filters, limit=limit)


def build_create_execution_error_operation(
    context: MarketsRepositoryContext,
    *,
    error_code: str,
    error_traceback: str,
    error_message: str,
    time_recorded: dt.datetime,
    related_account_uid: uuid.UUID | str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=ExecutionErrorTable,
        values={
            "error_code": error_code,
            "error_traceback": error_traceback,
            "error_message": error_message,
            "time_recorded": time_recorded,
            "related_account_uid": related_account_uid,
            "metadata_json": metadata_json,
        },
    )


def build_search_execution_errors_operation(
    context: MarketsRepositoryContext,
    *,
    error_code: str | None = None,
    related_account_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "error_code": error_code,
        "related_account_uid": related_account_uid,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(
        context,
        model=ExecutionErrorTable,
        filters=filters,
        limit=limit,
    )


def execute_execution_operation(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_markets_operation(operation, context=context)


def build_get_execution_model_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    model: type,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=model, uid=uid)


__all__ = [
    "build_create_execution_error_operation",
    "build_create_order_manager_operation",
    "build_create_order_operation",
    "build_create_order_status_event_operation",
    "build_create_order_target_quantity_operation",
    "build_create_trade_operation",
    "build_delete_order_manager_operation",
    "build_get_execution_model_by_uid_operation",
    "build_search_execution_errors_operation",
    "build_search_order_managers_operation",
    "build_search_order_status_events_operation",
    "build_search_order_target_quantities_operation",
    "build_search_orders_operation",
    "build_search_trades_operation",
    "build_update_order_manager_operation",
    "build_update_order_operation",
    "execute_execution_operation",
]
