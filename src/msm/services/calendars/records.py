from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select

from msm.api.base import operation_result_rows
from msm.api.calendars import (
    CalendarCreate,
    CalendarDateCreate,
    CalendarDateUpdate,
    CalendarDateUpsert,
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventUpsert,
    CalendarSessionCreate,
    CalendarSessionUpdate,
    CalendarSessionUpsert,
    CalendarUpdate,
)
from msm.models import (
    CalendarDateTable,
    CalendarEventTable,
    CalendarSessionTable,
    CalendarTable,
)
from msm.repositories import MarketsRepositoryContext
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm.repositories.calendars import (
    bulk_upsert_calendar_dates,
    bulk_upsert_calendar_events,
    bulk_upsert_calendar_sessions,
)
from msm.repositories.crud import (
    create_model,
    delete_model,
    get_model_by_uid,
    search_model,
    update_model,
)

from .validation import coerce_local_date


def list_calendar_records(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    unique_identifier: str | None = None,
    unique_identifier_contains: str | None = None,
    calendar_type: str | None = None,
    source: str | None = None,
    source_identifier: str | None = None,
) -> list[dict[str, Any]]:
    filters = _calendar_filters(
        unique_identifier=unique_identifier,
        calendar_type=calendar_type,
        source=source,
        source_identifier=source_identifier,
    )
    contains_filters = {}
    if unique_identifier_contains not in (None, ""):
        contains_filters["unique_identifier"] = str(unique_identifier_contains)

    rows = operation_result_rows(
        search_model(
            context,
            model=CalendarTable,
            filters=filters,
            contains_filters=contains_filters,
            limit=_scan_limit(offset=offset, limit=limit),
        )
    )
    rows.sort(
        key=lambda row: (
            str(row.get("unique_identifier", "")).lower(),
            str(row.get("uid", "")),
        )
    )

    normalized_search = search.strip().lower()
    if normalized_search:
        rows = [
            row
            for row in rows
            if _matches_search(
                values=(
                    row.get("uid"),
                    row.get("unique_identifier"),
                    row.get("display_name"),
                    row.get("calendar_type"),
                    row.get("source"),
                    row.get("source_identifier"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return rows[offset : offset + limit]


def get_calendar_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=CalendarTable, uid=uid))


def create_calendar_record(
    context: MarketsRepositoryContext,
    **values: Any,
) -> dict[str, Any]:
    payload = CalendarCreate(**values).model_dump()
    row = _first_operation_row(create_model(context, model=CalendarTable, values=payload))
    if row is None:
        raise RuntimeError("Calendar creation did not return a calendar row.")
    return row


def update_calendar_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_record(context, uid=uid)
    if existing is None:
        return None

    payload = CalendarUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing

    row = _first_operation_row(update_model(context, model=CalendarTable, uid=uid, values=payload))
    return row or get_calendar_record(context, uid=uid)


def delete_calendar_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    existing = get_calendar_record(context, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarTable, uid=uid)
    return True


def list_calendar_date_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str | None = None,
    end_date: dt.date | str | None = None,
    is_business_day: bool | None = None,
    is_holiday: bool | None = None,
    is_weekend: bool | None = None,
    is_early_close: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    statement = select(CalendarDateTable).where(CalendarDateTable.calendar_uid == calendar_uid)
    statement = _apply_date_window(
        statement,
        model=CalendarDateTable,
        field_name="local_date",
        start_date=start_date,
        end_date=end_date,
    )
    for field_name, value in {
        "is_business_day": is_business_day,
        "is_holiday": is_holiday,
        "is_weekend": is_weekend,
        "is_early_close": is_early_close,
    }.items():
        if value is not None:
            statement = statement.where(getattr(CalendarDateTable, field_name) == value)
    statement = statement.order_by(CalendarDateTable.local_date, CalendarDateTable.uid)
    return _execute_limited_select(
        context,
        statement=statement,
        model=CalendarDateTable,
        limit=limit,
        offset=offset,
    )


def get_calendar_date_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=CalendarDateTable, uid=uid))
    if not _belongs_to_calendar(row, calendar_uid):
        return None
    return row


def create_calendar_date_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    **values: Any,
) -> dict[str, Any]:
    payload = CalendarDateCreate(
        calendar_uid=calendar_uid,
        **_without_calendar_uid(values),
    ).model_dump()
    row = _first_operation_row(create_model(context, model=CalendarDateTable, values=payload))
    if row is None:
        raise RuntimeError("Calendar date creation did not return a calendar date row.")
    return row


def update_calendar_date_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_date_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return None

    payload = CalendarDateUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing

    row = _first_operation_row(
        update_model(context, model=CalendarDateTable, uid=uid, values=payload)
    )
    return row or get_calendar_date_record(context, calendar_uid=calendar_uid, uid=uid)


def delete_calendar_date_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> bool:
    existing = get_calendar_date_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarDateTable, uid=uid)
    return True


def bulk_upsert_calendar_date_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = [
        CalendarDateUpsert(
            calendar_uid=calendar_uid,
            **_without_calendar_uid(row),
        ).model_dump()
        for row in rows
    ]
    if not payloads:
        return []

    return operation_result_rows(bulk_upsert_calendar_dates(context, payloads))


def list_calendar_session_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str | None = None,
    end_date: dt.date | str | None = None,
    session_label: str | None = None,
    is_primary: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    statement = select(CalendarSessionTable).where(
        CalendarSessionTable.calendar_uid == calendar_uid
    )
    statement = _apply_date_window(
        statement,
        model=CalendarSessionTable,
        field_name="local_date",
        start_date=start_date,
        end_date=end_date,
    )
    if session_label not in (None, ""):
        statement = statement.where(CalendarSessionTable.session_label == str(session_label))
    if is_primary is not None:
        statement = statement.where(CalendarSessionTable.is_primary == is_primary)
    statement = statement.order_by(
        CalendarSessionTable.local_date,
        CalendarSessionTable.session_label,
        CalendarSessionTable.uid,
    )
    return _execute_limited_select(
        context,
        statement=statement,
        model=CalendarSessionTable,
        limit=limit,
        offset=offset,
    )


def get_calendar_session_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=CalendarSessionTable, uid=uid))
    if not _belongs_to_calendar(row, calendar_uid):
        return None
    return row


def create_calendar_session_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    **values: Any,
) -> dict[str, Any]:
    payload = CalendarSessionCreate(
        calendar_uid=calendar_uid,
        **_without_calendar_uid(values),
    ).model_dump()
    row = _first_operation_row(create_model(context, model=CalendarSessionTable, values=payload))
    if row is None:
        raise RuntimeError("Calendar session creation did not return a calendar session row.")
    return row


def update_calendar_session_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_session_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return None

    payload = CalendarSessionUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing

    row = _first_operation_row(
        update_model(context, model=CalendarSessionTable, uid=uid, values=payload)
    )
    return row or get_calendar_session_record(context, calendar_uid=calendar_uid, uid=uid)


def delete_calendar_session_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> bool:
    existing = get_calendar_session_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarSessionTable, uid=uid)
    return True


def bulk_upsert_calendar_session_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = [
        CalendarSessionUpsert(
            calendar_uid=calendar_uid,
            **_without_calendar_uid(row),
        ).model_dump()
        for row in rows
    ]
    if not payloads:
        return []

    return operation_result_rows(bulk_upsert_calendar_sessions(context, payloads))


def list_calendar_event_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str | None = None,
    end_date: dt.date | str | None = None,
    event_type: str | None = None,
    event_label: str | None = None,
    target_type: str | None = None,
    target_uid: str | None = None,
    target_identifier: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    statement = select(CalendarEventTable).where(CalendarEventTable.calendar_uid == calendar_uid)
    statement = _apply_date_window(
        statement,
        model=CalendarEventTable,
        field_name="event_date",
        start_date=start_date,
        end_date=end_date,
    )
    for field_name, value in {
        "event_type": event_type,
        "event_label": event_label,
        "target_type": target_type,
        "target_uid": target_uid,
        "target_identifier": target_identifier,
    }.items():
        if value not in (None, ""):
            statement = statement.where(getattr(CalendarEventTable, field_name) == value)
    statement = statement.order_by(
        CalendarEventTable.event_date,
        CalendarEventTable.event_type,
        CalendarEventTable.event_label,
        CalendarEventTable.uid,
    )
    return _execute_limited_select(
        context,
        statement=statement,
        model=CalendarEventTable,
        limit=limit,
        offset=offset,
    )


def get_calendar_event_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=CalendarEventTable, uid=uid))
    if not _belongs_to_calendar(row, calendar_uid):
        return None
    return row


def create_calendar_event_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    **values: Any,
) -> dict[str, Any]:
    payload = CalendarEventCreate(
        calendar_uid=calendar_uid,
        **_without_calendar_uid(values),
    ).model_dump()
    row = _first_operation_row(create_model(context, model=CalendarEventTable, values=payload))
    if row is None:
        raise RuntimeError("Calendar event creation did not return a calendar event row.")
    return row


def update_calendar_event_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_event_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return None

    payload = CalendarEventUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing

    row = _first_operation_row(
        update_model(context, model=CalendarEventTable, uid=uid, values=payload)
    )
    return row or get_calendar_event_record(context, calendar_uid=calendar_uid, uid=uid)


def delete_calendar_event_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> bool:
    existing = get_calendar_event_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarEventTable, uid=uid)
    return True


def bulk_upsert_calendar_event_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = [
        CalendarEventUpsert(
            calendar_uid=calendar_uid,
            **_without_calendar_uid(row),
        ).model_dump()
        for row in rows
    ]
    if not payloads:
        return []

    return operation_result_rows(bulk_upsert_calendar_events(context, payloads))


def _calendar_filters(
    *,
    unique_identifier: str | None,
    calendar_type: str | None,
    source: str | None,
    source_identifier: str | None,
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for key, value in {
        "unique_identifier": unique_identifier,
        "calendar_type": calendar_type,
        "source": source,
        "source_identifier": source_identifier,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return filters


def _apply_date_window(
    statement: Any,
    *,
    model: Any,
    field_name: str,
    start_date: dt.date | str | None,
    end_date: dt.date | str | None,
) -> Any:
    date_field = getattr(model, field_name)
    if start_date is not None:
        statement = statement.where(date_field >= coerce_local_date(start_date))
    if end_date is not None:
        statement = statement.where(date_field <= coerce_local_date(end_date))
    return statement


def _execute_limited_select(
    context: MarketsRepositoryContext,
    *,
    statement: Any,
    model: Any,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    limited_statement = statement.offset(offset).limit(limit)
    operation = compile_markets_statement(
        limited_statement,
        context=context,
        operation="select",
        models=[model],
        access="read",
    )
    return operation_result_rows(execute_markets_operation(operation, context=context))


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


def _scan_limit(*, offset: int, limit: int) -> int:
    return max(limit, offset + limit)


def _matches_search(
    *,
    values: Sequence[Any],
    normalized_search: str,
) -> bool:
    return any(normalized_search in str(value or "").lower() for value in values)


def _belongs_to_calendar(row: Mapping[str, Any] | None, calendar_uid: str) -> bool:
    if row is None:
        return False
    return str(row.get("calendar_uid")) == str(calendar_uid)


def _without_calendar_uid(values: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(values)
    payload.pop("calendar_uid", None)
    return payload


__all__ = [
    "bulk_upsert_calendar_date_records",
    "bulk_upsert_calendar_event_records",
    "bulk_upsert_calendar_session_records",
    "create_calendar_date_record",
    "create_calendar_event_record",
    "create_calendar_record",
    "create_calendar_session_record",
    "delete_calendar_date_record",
    "delete_calendar_event_record",
    "delete_calendar_record",
    "delete_calendar_session_record",
    "get_calendar_date_record",
    "get_calendar_event_record",
    "get_calendar_record",
    "get_calendar_session_record",
    "list_calendar_date_records",
    "list_calendar_event_records",
    "list_calendar_records",
    "list_calendar_session_records",
    "update_calendar_date_record",
    "update_calendar_event_record",
    "update_calendar_record",
    "update_calendar_session_record",
]
