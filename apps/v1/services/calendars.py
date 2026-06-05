from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from apps.v1.schemas.calendars import Calendar, CalendarDate, CalendarEvent, CalendarSession


def list_calendars(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    unique_identifier: str | None = None,
    unique_identifier_contains: str | None = None,
    calendar_type: str | None = None,
    source: str | None = None,
    source_identifier: str | None = None,
) -> list[Calendar]:
    runtime = _get_runtime()
    rows = _list_calendar_records(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
        unique_identifier=unique_identifier,
        unique_identifier_contains=unique_identifier_contains,
        calendar_type=calendar_type,
        source=source,
        source_identifier=source_identifier,
    )
    return [Calendar.model_validate(row) for row in rows]


def get_calendar(*, uid: str) -> Calendar | None:
    runtime = _get_runtime()
    row = _get_calendar_record(runtime.context, uid=uid)
    if row is None:
        return None
    return Calendar.model_validate(row)


def create_calendar(*, payload: Mapping[str, Any]) -> Calendar:
    runtime = _get_runtime()
    row = _create_calendar_record(runtime.context, **dict(payload))
    return Calendar.model_validate(row)


def update_calendar(*, uid: str, payload: Mapping[str, Any]) -> Calendar | None:
    runtime = _get_runtime()
    row = _update_calendar_record(runtime.context, uid=uid, **dict(payload))
    if row is None:
        return None
    return Calendar.model_validate(row)


def delete_calendar(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_calendar_record(runtime.context, uid=uid))


def list_calendar_dates(
    *,
    calendar_uid: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    is_business_day: bool | None = None,
    is_holiday: bool | None = None,
    is_weekend: bool | None = None,
    is_early_close: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[CalendarDate]:
    runtime = _get_runtime()
    rows = _list_calendar_date_records(
        runtime.context,
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        is_business_day=is_business_day,
        is_holiday=is_holiday,
        is_weekend=is_weekend,
        is_early_close=is_early_close,
        limit=limit,
        offset=offset,
    )
    return [CalendarDate.model_validate(row) for row in rows]


def get_calendar_date(*, calendar_uid: str, uid: str) -> CalendarDate | None:
    runtime = _get_runtime()
    row = _get_calendar_date_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    if row is None:
        return None
    return CalendarDate.model_validate(row)


def create_calendar_date(*, calendar_uid: str, payload: Mapping[str, Any]) -> CalendarDate:
    runtime = _get_runtime()
    row = _create_calendar_date_record(runtime.context, calendar_uid=calendar_uid, **dict(payload))
    return CalendarDate.model_validate(row)


def update_calendar_date(
    *,
    calendar_uid: str,
    uid: str,
    payload: Mapping[str, Any],
) -> CalendarDate | None:
    runtime = _get_runtime()
    row = _update_calendar_date_record(
        runtime.context,
        calendar_uid=calendar_uid,
        uid=uid,
        **dict(payload),
    )
    if row is None:
        return None
    return CalendarDate.model_validate(row)


def delete_calendar_date(*, calendar_uid: str, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_calendar_date_record(runtime.context, calendar_uid=calendar_uid, uid=uid))


def bulk_upsert_calendar_dates(
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[CalendarDate]:
    runtime = _get_runtime()
    result_rows = _bulk_upsert_calendar_date_records(
        runtime.context,
        calendar_uid=calendar_uid,
        rows=rows,
    )
    return [CalendarDate.model_validate(row) for row in result_rows]


def list_calendar_sessions(
    *,
    calendar_uid: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    session_label: str | None = None,
    is_primary: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[CalendarSession]:
    runtime = _get_runtime()
    rows = _list_calendar_session_records(
        runtime.context,
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        session_label=session_label,
        is_primary=is_primary,
        limit=limit,
        offset=offset,
    )
    return [CalendarSession.model_validate(row) for row in rows]


def get_calendar_session(*, calendar_uid: str, uid: str) -> CalendarSession | None:
    runtime = _get_runtime()
    row = _get_calendar_session_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    if row is None:
        return None
    return CalendarSession.model_validate(row)


def create_calendar_session(*, calendar_uid: str, payload: Mapping[str, Any]) -> CalendarSession:
    runtime = _get_runtime()
    row = _create_calendar_session_record(
        runtime.context,
        calendar_uid=calendar_uid,
        **dict(payload),
    )
    return CalendarSession.model_validate(row)


def update_calendar_session(
    *,
    calendar_uid: str,
    uid: str,
    payload: Mapping[str, Any],
) -> CalendarSession | None:
    runtime = _get_runtime()
    row = _update_calendar_session_record(
        runtime.context,
        calendar_uid=calendar_uid,
        uid=uid,
        **dict(payload),
    )
    if row is None:
        return None
    return CalendarSession.model_validate(row)


def delete_calendar_session(*, calendar_uid: str, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(
        _delete_calendar_session_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    )


def bulk_upsert_calendar_sessions(
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[CalendarSession]:
    runtime = _get_runtime()
    result_rows = _bulk_upsert_calendar_session_records(
        runtime.context,
        calendar_uid=calendar_uid,
        rows=rows,
    )
    return [CalendarSession.model_validate(row) for row in result_rows]


def list_calendar_events(
    *,
    calendar_uid: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    event_type: str | None = None,
    event_label: str | None = None,
    target_type: str | None = None,
    target_uid: str | None = None,
    target_identifier: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[CalendarEvent]:
    runtime = _get_runtime()
    rows = _list_calendar_event_records(
        runtime.context,
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        event_type=event_type,
        event_label=event_label,
        target_type=target_type,
        target_uid=target_uid,
        target_identifier=target_identifier,
        limit=limit,
        offset=offset,
    )
    return [CalendarEvent.model_validate(row) for row in rows]


def get_calendar_event(*, calendar_uid: str, uid: str) -> CalendarEvent | None:
    runtime = _get_runtime()
    row = _get_calendar_event_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    if row is None:
        return None
    return CalendarEvent.model_validate(row)


def create_calendar_event(*, calendar_uid: str, payload: Mapping[str, Any]) -> CalendarEvent:
    runtime = _get_runtime()
    row = _create_calendar_event_record(
        runtime.context,
        calendar_uid=calendar_uid,
        **dict(payload),
    )
    return CalendarEvent.model_validate(row)


def update_calendar_event(
    *,
    calendar_uid: str,
    uid: str,
    payload: Mapping[str, Any],
) -> CalendarEvent | None:
    runtime = _get_runtime()
    row = _update_calendar_event_record(
        runtime.context,
        calendar_uid=calendar_uid,
        uid=uid,
        **dict(payload),
    )
    if row is None:
        return None
    return CalendarEvent.model_validate(row)


def delete_calendar_event(*, calendar_uid: str, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_calendar_event_record(runtime.context, calendar_uid=calendar_uid, uid=uid))


def bulk_upsert_calendar_events(
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[CalendarEvent]:
    runtime = _get_runtime()
    result_rows = _bulk_upsert_calendar_event_records(
        runtime.context,
        calendar_uid=calendar_uid,
        rows=rows,
    )
    return [CalendarEvent.model_validate(row) for row in result_rows]


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Calendar",
            "CalendarDate",
            "CalendarSession",
            "CalendarEvent",
        ],
        row_model_name="Calendar apps/v1",
    )


def _list_calendar_records(context, **kwargs):
    from msm.services import list_calendar_records

    return list_calendar_records(context, **kwargs)


def _get_calendar_record(context, **kwargs):
    from msm.services import get_calendar_record

    return get_calendar_record(context, **kwargs)


def _create_calendar_record(context, **kwargs):
    from msm.services import create_calendar_record

    return create_calendar_record(context, **kwargs)


def _update_calendar_record(context, **kwargs):
    from msm.services import update_calendar_record

    return update_calendar_record(context, **kwargs)


def _delete_calendar_record(context, **kwargs):
    from msm.services import delete_calendar_record

    return delete_calendar_record(context, **kwargs)


def _list_calendar_date_records(context, **kwargs):
    from msm.services import list_calendar_date_records

    return list_calendar_date_records(context, **kwargs)


def _get_calendar_date_record(context, **kwargs):
    from msm.services import get_calendar_date_record

    return get_calendar_date_record(context, **kwargs)


def _create_calendar_date_record(context, **kwargs):
    from msm.services import create_calendar_date_record

    return create_calendar_date_record(context, **kwargs)


def _update_calendar_date_record(context, **kwargs):
    from msm.services import update_calendar_date_record

    return update_calendar_date_record(context, **kwargs)


def _delete_calendar_date_record(context, **kwargs):
    from msm.services import delete_calendar_date_record

    return delete_calendar_date_record(context, **kwargs)


def _bulk_upsert_calendar_date_records(context, **kwargs):
    from msm.services import bulk_upsert_calendar_date_records

    return bulk_upsert_calendar_date_records(context, **kwargs)


def _list_calendar_session_records(context, **kwargs):
    from msm.services import list_calendar_session_records

    return list_calendar_session_records(context, **kwargs)


def _get_calendar_session_record(context, **kwargs):
    from msm.services import get_calendar_session_record

    return get_calendar_session_record(context, **kwargs)


def _create_calendar_session_record(context, **kwargs):
    from msm.services import create_calendar_session_record

    return create_calendar_session_record(context, **kwargs)


def _update_calendar_session_record(context, **kwargs):
    from msm.services import update_calendar_session_record

    return update_calendar_session_record(context, **kwargs)


def _delete_calendar_session_record(context, **kwargs):
    from msm.services import delete_calendar_session_record

    return delete_calendar_session_record(context, **kwargs)


def _bulk_upsert_calendar_session_records(context, **kwargs):
    from msm.services import bulk_upsert_calendar_session_records

    return bulk_upsert_calendar_session_records(context, **kwargs)


def _list_calendar_event_records(context, **kwargs):
    from msm.services import list_calendar_event_records

    return list_calendar_event_records(context, **kwargs)


def _get_calendar_event_record(context, **kwargs):
    from msm.services import get_calendar_event_record

    return get_calendar_event_record(context, **kwargs)


def _create_calendar_event_record(context, **kwargs):
    from msm.services import create_calendar_event_record

    return create_calendar_event_record(context, **kwargs)


def _update_calendar_event_record(context, **kwargs):
    from msm.services import update_calendar_event_record

    return update_calendar_event_record(context, **kwargs)


def _delete_calendar_event_record(context, **kwargs):
    from msm.services import delete_calendar_event_record

    return delete_calendar_event_record(context, **kwargs)


def _bulk_upsert_calendar_event_records(context, **kwargs):
    from msm.services import bulk_upsert_calendar_event_records

    return bulk_upsert_calendar_event_records(context, **kwargs)
