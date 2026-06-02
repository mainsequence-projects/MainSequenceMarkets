from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import OrderManagerTable

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
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


def execute_execution_operation(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_markets_operation(operation, context=context)


__all__ = [
    "build_create_order_manager_operation",
    "build_delete_order_manager_operation",
    "build_search_order_managers_operation",
    "build_update_order_manager_operation",
    "execute_execution_operation",
]
