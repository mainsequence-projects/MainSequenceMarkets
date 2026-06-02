from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import CalendarTable

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_calendar_operation(
    context: MarketsRepositoryContext,
    *,
    name: str,
    calendar_dates: dict | list | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=CalendarTable,
        values={
            "name": name,
            "calendar_dates": calendar_dates,
            "metadata_json": metadata_json,
        },
    )


def create_calendar(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_calendar_operation(context, **kwargs),
        context=context,
    )


def build_get_calendar_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=CalendarTable, uid=uid)


def get_calendar_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_calendar_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_search_calendars_operation(
    context: MarketsRepositoryContext,
    *,
    name: str | None = None,
    name_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if name not in (None, ""):
        filters["name"] = name
    return build_search_model_operation(
        context,
        model=CalendarTable,
        filters=filters,
        contains_filters={"name": name_contains or ""},
        limit=limit,
    )


def search_calendars(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_calendars_operation(context, **kwargs),
        context=context,
    )


def build_update_calendar_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    calendar_dates: dict | list | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=CalendarTable,
        uid=uid,
        values={
            "calendar_dates": calendar_dates,
            "metadata_json": metadata_json,
        },
    )


def update_calendar(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_calendar_operation(context, **kwargs),
        context=context,
    )


def build_delete_calendar_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=CalendarTable, uid=uid)


def delete_calendar(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_calendar_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_calendar_operation",
    "build_delete_calendar_operation",
    "build_get_calendar_by_uid_operation",
    "build_search_calendars_operation",
    "build_update_calendar_operation",
    "create_calendar",
    "delete_calendar",
    "get_calendar_by_uid",
    "search_calendars",
    "update_calendar",
]
