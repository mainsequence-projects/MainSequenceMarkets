from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import CalendarTable
from msm.repositories.base import MarketsRepositoryContext, execute_markets_operation
from msm.repositories.crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_calendar_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    display_name: str,
    calendar_type: str,
    valid_from: dt.date,
    valid_to: dt.date,
    timezone: str = "UTC",
    source: str | None = None,
    source_identifier: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=CalendarTable,
        values={
            "unique_identifier": unique_identifier,
            "display_name": display_name,
            "calendar_type": calendar_type,
            "timezone": timezone,
            "source": source,
            "source_identifier": source_identifier,
            "valid_from": valid_from,
            "valid_to": valid_to,
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
    unique_identifier: str | None = None,
    unique_identifier_contains: str | None = None,
    calendar_type: str | None = None,
    source: str | None = None,
    source_identifier: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if unique_identifier not in (None, ""):
        filters["unique_identifier"] = unique_identifier
    if calendar_type not in (None, ""):
        filters["calendar_type"] = calendar_type
    if source not in (None, ""):
        filters["source"] = source
    if source_identifier not in (None, ""):
        filters["source_identifier"] = source_identifier
    return build_search_model_operation(
        context,
        model=CalendarTable,
        filters=filters,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
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
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=CalendarTable,
        uid=uid,
        values=values,
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
