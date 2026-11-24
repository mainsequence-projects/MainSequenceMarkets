from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from msm.models import CalendarExceptionTable
from msm.repositories.base import MarketsRepositoryContext, with_max_rows
from msm.repositories.crud import bulk_upsert_model, search_model

CALENDAR_EXCEPTION_KEYS = (
    "calendar_uid",
    "local_date",
    "session_label",
    "exception_type",
    "source",
)

EXCEPTION_READ_PAGE = 9_000
"""Rows per read; MetaTables answers at most 10,000 rows per statement. A calendar's
exceptions to the library's horizon (2200 for NYSE, about 2,500 rows) are one read."""


def bulk_upsert_calendar_exceptions(
    context: MarketsRepositoryContext,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return bulk_upsert_model(
        context,
        model=CalendarExceptionTable,
        values=rows,
        conflict_columns=CALENDAR_EXCEPTION_KEYS,
    )


def read_calendar_exceptions(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: uuid.UUID | str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """The exceptions of one calendar in a date range, read page by page.

    An exchange has about 12 exceptions a year, so one page covers centuries.
    """

    filters: dict[str, Any] = {"calendar_uid": calendar_uid}
    if source not in (None, ""):
        filters["source"] = source
    window: dict[str, Any] = {}
    if start_date is not None:
        window["gte"] = start_date
    if end_date is not None:
        window["lte"] = end_date

    rows: list[dict[str, Any]] = []
    while True:
        result = search_model(
            with_max_rows(context, EXCEPTION_READ_PAGE),
            model=CalendarExceptionTable,
            filters=filters,
            range_filters={"local_date": window} if window else None,
            order_by=("local_date", "uid"),
            limit=EXCEPTION_READ_PAGE,
            offset=len(rows),
        )
        page = [dict(row) for row in (result.get("rows") or [])]
        rows.extend(page)
        if len(page) < EXCEPTION_READ_PAGE:
            return rows


__all__ = [
    "CALENDAR_EXCEPTION_KEYS",
    "EXCEPTION_READ_PAGE",
    "bulk_upsert_calendar_exceptions",
    "read_calendar_exceptions",
]
