from __future__ import annotations

from collections.abc import Mapping, Sequence
import datetime as dt
from typing import Any

from sqlalchemy import select

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import CalendarSessionTable
from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.repositories.crud import bulk_upsert_model


def bulk_upsert_calendar_sessions(
    context: MarketsRepositoryContext,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return bulk_upsert_model(
        context,
        model=CalendarSessionTable,
        values=rows,
        conflict_columns=("calendar_uid", "local_date", "session_label"),
    )


def build_search_calendar_sessions_operation(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date,
    end_date: dt.date,
    session_label: str | None = None,
    limit: int = 10000,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(CalendarSessionTable)
        .where(CalendarSessionTable.calendar_uid == calendar_uid)
        .where(CalendarSessionTable.local_date >= start_date)
        .where(CalendarSessionTable.local_date <= end_date)
        .limit(limit)
    )
    if session_label not in (None, ""):
        statement = statement.where(CalendarSessionTable.session_label == session_label)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[CalendarSessionTable],
        access="read",
    )


def search_calendar_sessions(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_calendar_sessions_operation(context, **kwargs),
        context=context,
    )


__all__ = [
    "build_search_calendar_sessions_operation",
    "bulk_upsert_calendar_sessions",
    "search_calendar_sessions",
]
