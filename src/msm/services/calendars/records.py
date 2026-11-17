"""Calendar records behind the Markets API calendar routes (ADR 0055).

Calendars, session rules and exceptions are stored rows. Dates and sessions are
computed from them for a requested window.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import String, cast, func, or_, select

from msm.api.base import operation_result_rows
from msm.api.calendars import (
    CalendarCreate,
    CalendarExceptionCreate,
    CalendarExceptionUpdate,
    CalendarExceptionUpsert,
    CalendarSessionRuleCreate,
    CalendarSessionRuleUpdate,
    CalendarSessionRuleUpsert,
    CalendarUpdate,
)
from msm.api.calendars.exceptions import validate_exception_update
from msm.api.calendars.rules import validate_rule_update
from msm.models import CalendarExceptionTable, CalendarSessionRuleTable, CalendarTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm.repositories.calendars import (
    bulk_upsert_calendar_exceptions,
    bulk_upsert_calendar_session_rules,
)
from msm.repositories.crud import (
    create_model,
    delete_model,
    get_model_by_uid,
    update_model,
)

from .computation import (
    EXCEPTION_CLOSED,
    USER_SOURCE,
    compute_dates,
    compute_sessions,
)
from .definitions import load_calendar_definition
from .validation import coerce_local_date, ensure_date_range


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
    statement = _calendar_list_statement(
        search=search,
        unique_identifier=unique_identifier,
        unique_identifier_contains=unique_identifier_contains,
        calendar_type=calendar_type,
        source=source,
        source_identifier=source_identifier,
    )
    return _execute_limited_select(
        context,
        statement=statement,
        limit=limit,
        offset=offset,
    )


def list_calendar_records_page(
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
) -> dict[str, Any]:
    return _execute_collection_page(
        context,
        statement=_calendar_list_statement(
            search=search,
            unique_identifier=unique_identifier,
            unique_identifier_contains=unique_identifier_contains,
            calendar_type=calendar_type,
            source=source,
            source_identifier=source_identifier,
        ),
        limit=limit,
        offset=offset,
    )


def get_calendar_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=CalendarTable, uid=uid))


def get_calendar_frontend_detail_summary(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    calendar_row = get_calendar_record(context, uid=uid)
    if calendar_row is None:
        return None

    calendar_uid = str(calendar_row["uid"])
    unique_identifier = _string_or_empty(calendar_row.get("unique_identifier"))
    display_name = _string_or_empty(calendar_row.get("display_name"))
    calendar_type = _string_or_empty(calendar_row.get("calendar_type"))
    timezone = _string_or_empty(calendar_row.get("timezone")) or "UTC"
    source = _string_or_none(calendar_row.get("source"))
    source_identifier = _string_or_none(calendar_row.get("source_identifier"))
    valid_from = _date_or_none(calendar_row.get("valid_from"))
    valid_to = _date_or_none(calendar_row.get("valid_to"))
    horizon_days = _horizon_days(valid_from=valid_from, valid_to=valid_to)

    return {
        "entity": {
            "id": calendar_uid,
            "type": "calendar",
            "title": display_name or unique_identifier or calendar_uid,
        },
        "badges": [
            {
                "key": "calendar_type",
                "label": calendar_type or "Calendar",
                "tone": _calendar_type_tone(calendar_type),
            },
            {
                "key": "timezone",
                "label": timezone,
                "tone": "neutral",
            },
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": calendar_uid,
                "kind": "code",
            },
            {
                "key": "unique_identifier",
                "label": "Identifier",
                "value": unique_identifier,
                "kind": "code",
            },
            {
                "key": "source_identifier",
                "label": "Source identifier",
                "value": source_identifier,
                "kind": "code",
            },
            {
                "key": "source",
                "label": "Source",
                "value": source,
                "kind": "text",
            },
        ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display name",
                "value": display_name,
                "kind": "text",
                "icon": "calendar",
            },
            {
                "key": "valid_from",
                "label": "Valid from",
                "value": _date_display(valid_from),
                "kind": "date",
                "icon": "calendar-days",
            },
            {
                "key": "valid_to",
                "label": "Valid to",
                "value": _date_display(valid_to),
                "kind": "date",
                "icon": "calendar-days",
            },
        ],
        "stats": [
            {
                "key": "horizon_days",
                "label": "Horizon days",
                "display": str(horizon_days) if horizon_days is not None else "",
                "value": horizon_days,
                "kind": "number",
            }
        ],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "metadata_json": _mapping_or_none(calendar_row.get("metadata_json")),
            "relationships": {
                "dates_url": f"/api/v1/calendar/{calendar_uid}/dates/",
                "sessions_url": f"/api/v1/calendar/{calendar_uid}/sessions/",
                "rules_url": f"/api/v1/calendar/{calendar_uid}/rules/",
                "exceptions_url": f"/api/v1/calendar/{calendar_uid}/exceptions/",
            },
        },
    }


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


def list_calendar_date_records_page(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str,
    end_date: dt.date | str,
    is_business_day: bool | None = None,
    is_holiday: bool | None = None,
    is_weekend: bool | None = None,
    is_early_close: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any] | None:
    """The computed dates of a window, filtered and paged. None when the calendar is unknown."""

    definition = _window_definition(
        context, calendar_uid=calendar_uid, start_date=start_date, end_date=end_date
    )
    if definition is None:
        return None
    flags = {
        "is_business_day": is_business_day,
        "is_holiday": is_holiday,
        "is_weekend": is_weekend,
        "is_early_close": is_early_close,
    }
    rows = [
        {
            "calendar_uid": str(calendar_uid),
            "local_date": date.local_date,
            "is_business_day": date.is_business_day,
            "is_holiday": date.is_holiday,
            "is_weekend": date.is_weekend,
            "is_early_close": date.is_early_close,
            "holiday_name": date.holiday_name,
        }
        for date in compute_dates(definition, start_date, end_date)
        if all(
            wanted is None or getattr(date, name) == wanted for name, wanted in flags.items()
        )
    ]
    return {"count": len(rows), "results": rows[offset : offset + limit]}


def list_calendar_session_records_page(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str,
    end_date: dt.date | str,
    session_label: str | None = None,
    is_primary: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any] | None:
    """The computed sessions of a window, filtered and paged. None when the calendar is unknown."""

    definition = _window_definition(
        context, calendar_uid=calendar_uid, start_date=start_date, end_date=end_date
    )
    if definition is None:
        return None
    rows = [
        {
            "calendar_uid": str(calendar_uid),
            "local_date": session.local_date,
            "session_label": session.session_label,
            "opens_at": session.opens_at,
            "closes_at": session.closes_at,
            "timezone": session.timezone,
            "is_primary": session.is_primary,
            "is_early_close": session.is_early_close,
            "is_late_open": session.is_late_open,
        }
        for session in compute_sessions(
            definition, start_date, end_date, session_label=session_label
        )
        if is_primary is None or session.is_primary == is_primary
    ]
    return {"count": len(rows), "results": rows[offset : offset + limit]}


def read_calendar_session_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str,
    end_date: dt.date | str,
    session_label: str | None = None,
    clamp_to_range: bool = False,
) -> list[dict[str, Any]]:
    """Every computed session of a window, as rows.

    ``clamp_to_range`` reads only the part of the window the calendar is
    complete for, instead of refusing a window that reaches outside it. A
    caller that inspects stored history uses it; a caller that decides on the
    sessions must not.
    """

    calendar = get_calendar_record(context, uid=str(calendar_uid))
    if calendar is None:
        raise LookupError(f"Calendar {calendar_uid} was not found.")
    start, end = ensure_date_range(start_date, end_date)
    if clamp_to_range:
        valid_from = _date_or_none(calendar.get("valid_from"))
        valid_to = _date_or_none(calendar.get("valid_to"))
        start = start if valid_from is None else max(start, valid_from)
        end = end if valid_to is None else min(end, valid_to)
        if end < start:
            return []
    definition = load_calendar_definition(context, calendar=calendar, start_date=start, end_date=end)
    return [
        {
            "calendar_uid": str(calendar_uid),
            "local_date": session.local_date,
            "session_label": session.session_label,
            "opens_at": session.opens_at,
            "closes_at": session.closes_at,
            "timezone": session.timezone,
            "is_primary": session.is_primary,
        }
        for session in compute_sessions(definition, start, end, session_label=session_label)
    ]


def _window_definition(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str,
    end_date: dt.date | str,
) -> Any:
    calendar = get_calendar_record(context, uid=calendar_uid)
    if calendar is None:
        return None
    start, end = ensure_date_range(start_date, end_date)
    return load_calendar_definition(context, calendar=calendar, start_date=start, end_date=end)


def list_calendar_session_rule_records_page(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    session_label: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    statement = select(CalendarSessionRuleTable).where(
        CalendarSessionRuleTable.calendar_uid == calendar_uid
    )
    if session_label not in (None, ""):
        statement = statement.where(CalendarSessionRuleTable.session_label == str(session_label))
    return _execute_collection_page(
        context,
        statement=statement.order_by(
            CalendarSessionRuleTable.session_label,
            CalendarSessionRuleTable.effective_from,
            CalendarSessionRuleTable.uid,
        ),
        limit=limit,
        offset=offset,
    )


def get_calendar_session_rule_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=CalendarSessionRuleTable, uid=uid))
    if not _belongs_to_calendar(row, calendar_uid):
        return None
    return row


def create_calendar_session_rule_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    **values: Any,
) -> dict[str, Any]:
    payload = CalendarSessionRuleCreate(
        calendar_uid=calendar_uid,
        **_without_calendar_uid(values),
    ).model_dump()
    row = _first_operation_row(
        create_model(context, model=CalendarSessionRuleTable, values=payload)
    )
    if row is None:
        raise RuntimeError("Calendar session rule creation did not return a row.")
    return row


def update_calendar_session_rule_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_session_rule_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return None

    payload = CalendarSessionRuleUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing
    validate_rule_update(existing, payload)

    row = _first_operation_row(
        update_model(context, model=CalendarSessionRuleTable, uid=uid, values=payload)
    )
    return row or get_calendar_session_rule_record(context, calendar_uid=calendar_uid, uid=uid)


def delete_calendar_session_rule_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> bool:
    existing = get_calendar_session_rule_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarSessionRuleTable, uid=uid)
    return True


def bulk_upsert_calendar_session_rule_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payloads = [
        CalendarSessionRuleUpsert(
            calendar_uid=calendar_uid,
            **_without_calendar_uid(row),
        ).model_dump()
        for row in rows
    ]
    if not payloads:
        return []

    return operation_result_rows(bulk_upsert_calendar_session_rules(context, payloads))


def list_calendar_exception_records_page(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    start_date: dt.date | str | None = None,
    end_date: dt.date | str | None = None,
    session_label: str | None = None,
    exception_type: str | None = None,
    source: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    statement = select(CalendarExceptionTable).where(
        CalendarExceptionTable.calendar_uid == calendar_uid
    )
    statement = _apply_date_window(
        statement,
        model=CalendarExceptionTable,
        field_name="local_date",
        start_date=start_date,
        end_date=end_date,
    )
    for field_name, value in {
        "session_label": session_label,
        "exception_type": exception_type,
        "source": source,
    }.items():
        if value not in (None, ""):
            statement = statement.where(getattr(CalendarExceptionTable, field_name) == value)
    return _execute_collection_page(
        context,
        statement=statement.order_by(
            CalendarExceptionTable.local_date,
            CalendarExceptionTable.session_label,
            CalendarExceptionTable.exception_type,
            CalendarExceptionTable.uid,
        ),
        limit=limit,
        offset=offset,
    )


def get_calendar_exception_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=CalendarExceptionTable, uid=uid))
    if not _belongs_to_calendar(row, calendar_uid):
        return None
    return row


def create_calendar_exception_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    **values: Any,
) -> dict[str, Any]:
    """Create one exception with ``source="user"``."""

    payload = _user_exception_payload(CalendarExceptionCreate, calendar_uid, values)
    _refuse_closed_conflicts(context, calendar_uid=calendar_uid, payloads=[payload])
    row = _first_operation_row(create_model(context, model=CalendarExceptionTable, values=payload))
    if row is None:
        raise RuntimeError("Calendar exception creation did not return a row.")
    return row


def update_calendar_exception_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
    **values: Any,
) -> dict[str, Any] | None:
    existing = get_calendar_exception_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return None

    payload = CalendarExceptionUpdate(**values).model_dump(exclude_unset=True)
    if not payload:
        return existing
    validate_exception_update(existing, payload)

    row = _first_operation_row(
        update_model(context, model=CalendarExceptionTable, uid=uid, values=payload)
    )
    return row or get_calendar_exception_record(context, calendar_uid=calendar_uid, uid=uid)


def delete_calendar_exception_record(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    uid: str,
) -> bool:
    existing = get_calendar_exception_record(context, calendar_uid=calendar_uid, uid=uid)
    if existing is None:
        return False

    delete_model(context, model=CalendarExceptionTable, uid=uid)
    return True


def bulk_upsert_calendar_exception_records(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Upsert exceptions with ``source="user"``."""

    payloads = [_user_exception_payload(CalendarExceptionUpsert, calendar_uid, row) for row in rows]
    if not payloads:
        return []

    _refuse_closed_conflicts(context, calendar_uid=calendar_uid, payloads=payloads)
    return operation_result_rows(bulk_upsert_calendar_exceptions(context, payloads))


_CONFLICT_CHECK_DATES = 100
"""Dates per read of the stored user exceptions; a governed read returns at most 1,000 rows."""


def _user_exception_payload(
    payload_model: type[CalendarExceptionCreate],
    calendar_uid: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    payload = payload_model(calendar_uid=calendar_uid, **_without_calendar_uid(values))
    return {**payload.model_dump(), "source": USER_SOURCE}


def _refuse_closed_conflicts(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: str,
    payloads: Sequence[Mapping[str, Any]],
) -> None:
    """Refuse a CLOSED row next to another user row for the same date and session.

    The stored user rows of the written dates and the rows being written are
    checked together.
    """

    dates = sorted({payload["local_date"] for payload in payloads})
    stored: list[dict[str, Any]] = []
    for index in range(0, len(dates), _CONFLICT_CHECK_DATES):
        statement = (
            select(
                CalendarExceptionTable.local_date,
                CalendarExceptionTable.session_label,
                CalendarExceptionTable.exception_type,
            )
            .where(CalendarExceptionTable.calendar_uid == calendar_uid)
            .where(CalendarExceptionTable.source == USER_SOURCE)
            .where(
                CalendarExceptionTable.local_date.in_(dates[index : index + _CONFLICT_CHECK_DATES])
            )
        )
        # A date and session holds at most four user rows, one per exception type.
        stored.extend(
            _execute_limited_select(context, statement=statement, limit=1000, offset=0)
        )
    types_by_session: dict[tuple[str, str], set[str]] = {}
    for row in [*stored, *payloads]:
        key = (coerce_local_date(row["local_date"]).isoformat(), str(row["session_label"] or ""))
        types_by_session.setdefault(key, set()).add(str(row["exception_type"]))
    for (local_date, session_label), types in sorted(types_by_session.items()):
        if EXCEPTION_CLOSED in types and len(types) > 1:
            session = f"session {session_label!r}" if session_label else "the whole day"
            raise ValueError(
                f"{local_date} would have a CLOSED exception next to "
                f"{', '.join(sorted(types - {EXCEPTION_CLOSED}))} for {session}. "
                "A closed session cannot also open or close at another time."
            )


def _calendar_list_statement(
    *,
    search: str = "",
    unique_identifier: str | None,
    unique_identifier_contains: str | None,
    calendar_type: str | None,
    source: str | None,
    source_identifier: str | None,
) -> Any:
    statement = select(CalendarTable)
    for key, value in {
        "unique_identifier": unique_identifier,
        "calendar_type": calendar_type,
        "source": source,
        "source_identifier": source_identifier,
    }.items():
        if value not in (None, ""):
            statement = statement.where(getattr(CalendarTable, key) == value)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            func.lower(CalendarTable.unique_identifier).like(
                f"%{str(unique_identifier_contains).strip().lower()}%"
            )
        )
    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(CalendarTable.uid, String)).like(needle),
                func.lower(CalendarTable.unique_identifier).like(needle),
                func.lower(CalendarTable.display_name).like(needle),
                func.lower(CalendarTable.calendar_type).like(needle),
                func.lower(func.coalesce(CalendarTable.source, "")).like(needle),
                func.lower(func.coalesce(CalendarTable.source_identifier, "")).like(needle),
            )
        )
    return statement.order_by(
        func.lower(CalendarTable.unique_identifier),
        CalendarTable.uid,
    )


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
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    limited_statement = statement.offset(offset).limit(limit)
    operation = compile_markets_statement(
        limited_statement,
        context=context,
        operation="select",
    )
    return operation_result_rows(execute_markets_operation(operation, context=context))


def _execute_collection_page(
    context: MarketsRepositoryContext,
    *,
    statement: Any,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    count_statement = select(func.count().label("count")).select_from(statement.subquery())
    count_rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                count_statement,
                context=context,
                operation="select",
            ),
            context=context,
        )
    )
    return {
        "count": int(count_rows[0]["count"]) if count_rows else 0,
        "results": _execute_limited_select(
            context,
            statement=statement,
            limit=limit,
            offset=offset,
        ),
    }


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


def _scan_limit(*, offset: int, limit: int) -> int:
    return max(limit, offset + limit)


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _date_or_none(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _date_display(value: dt.date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _horizon_days(
    *,
    valid_from: dt.date | None,
    valid_to: dt.date | None,
) -> int | None:
    if valid_from is None or valid_to is None:
        return None
    return (valid_to - valid_from).days + 1


def _calendar_type_tone(calendar_type: str) -> str:
    if calendar_type in {"TRADING", "BUSINESS", "SETTLEMENT"}:
        return "success"
    if calendar_type in {"FIXING", "EVENT"}:
        return "info"
    if calendar_type == "HOLIDAY":
        return "warning"
    return "neutral"


def _matches_search(
    *,
    values: Sequence[Any],
    normalized_search: str,
) -> bool:
    return any(normalized_search in str(value or "").lower() for value in values)


def _belongs_to_calendar(row: Mapping[str, Any] | None, calendar_uid: str) -> bool:
    """Whether a rule or exception row is the given calendar's.

    The uids are compared as UUIDs: SQLite returns 32 hex characters and a caller
    may write the same uid with dashes or in upper case.
    """

    if row is None:
        return False
    try:
        return uuid.UUID(str(row.get("calendar_uid"))) == uuid.UUID(str(calendar_uid))
    except ValueError:
        return False


def _without_calendar_uid(values: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(values)
    payload.pop("calendar_uid", None)
    return payload


__all__ = [
    "bulk_upsert_calendar_exception_records",
    "bulk_upsert_calendar_session_rule_records",
    "create_calendar_exception_record",
    "create_calendar_record",
    "create_calendar_session_rule_record",
    "delete_calendar_exception_record",
    "delete_calendar_record",
    "delete_calendar_session_rule_record",
    "get_calendar_exception_record",
    "get_calendar_frontend_detail_summary",
    "get_calendar_record",
    "get_calendar_session_rule_record",
    "list_calendar_date_records_page",
    "list_calendar_exception_records_page",
    "list_calendar_records",
    "list_calendar_records_page",
    "list_calendar_session_records_page",
    "list_calendar_session_rule_records_page",
    "read_calendar_session_records",
    "update_calendar_exception_record",
    "update_calendar_record",
    "update_calendar_session_rule_record",
]
