from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from apps.v1.identity import registry_write
from apps.v1.schemas.calendars import (
    Calendar,
    CalendarException,
    CalendarSessionRule,
    ComputedCalendarDate,
    ComputedCalendarSession,
)
from apps.v1.schemas.common import FrontEndDetailSummary


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
) -> dict[str, Any]:
    runtime = _get_runtime()
    response = _list_calendar_records_page(
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
    return {
        "count": int(response["count"]),
        "results": [Calendar.model_validate(row) for row in response["results"]],
    }


def get_calendar(*, uid: str) -> Calendar | None:
    runtime = _get_runtime()
    row = _get_calendar_record(runtime.context, uid=uid)
    if row is None:
        return None
    return Calendar.model_validate(row)


def get_calendar_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    summary = _get_calendar_frontend_detail_summary(runtime.context, uid=uid)
    if summary is None:
        return None
    return FrontEndDetailSummary.model_validate(summary)


@registry_write("calendar", "create")
def create_calendar(*, payload: Mapping[str, Any]) -> Calendar:
    runtime = _get_runtime()
    row = _create_calendar_record(runtime.context, **dict(payload))
    return Calendar.model_validate(row)


@registry_write("calendar", "update")
def update_calendar(*, uid: str, payload: Mapping[str, Any]) -> Calendar | None:
    runtime = _get_runtime()
    row = _update_calendar_record(runtime.context, uid=uid, **dict(payload))
    if row is None:
        return None
    return Calendar.model_validate(row)


@registry_write("calendar", "delete")
def delete_calendar(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_calendar_record(runtime.context, uid=uid))


def list_calendar_dates(
    *,
    calendar_uid: str,
    start_date: dt.date,
    end_date: dt.date,
    is_business_day: bool | None = None,
    is_holiday: bool | None = None,
    is_weekend: bool | None = None,
    is_early_close: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any] | None:
    runtime = _get_runtime()
    response = _list_calendar_date_records_page(
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
    if response is None:
        return None
    return {
        "count": int(response["count"]),
        "results": [ComputedCalendarDate.model_validate(row) for row in response["results"]],
    }


def list_calendar_sessions(
    *,
    calendar_uid: str,
    start_date: dt.date,
    end_date: dt.date,
    session_label: str | None = None,
    is_primary: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any] | None:
    runtime = _get_runtime()
    response = _list_calendar_session_records_page(
        runtime.context,
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        session_label=session_label,
        is_primary=is_primary,
        limit=limit,
        offset=offset,
    )
    if response is None:
        return None
    return {
        "count": int(response["count"]),
        "results": [ComputedCalendarSession.model_validate(row) for row in response["results"]],
    }


def list_calendar_session_rules(
    *,
    calendar_uid: str,
    session_label: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    runtime = _get_runtime()
    response = _list_calendar_session_rule_records_page(
        runtime.context,
        calendar_uid=calendar_uid,
        session_label=session_label,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [CalendarSessionRule.model_validate(row) for row in response["results"]],
    }


def get_calendar_session_rule(*, calendar_uid: str, uid: str) -> CalendarSessionRule | None:
    runtime = _get_runtime()
    row = _get_calendar_session_rule_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    if row is None:
        return None
    return CalendarSessionRule.model_validate(row)


@registry_write("calendar", "create:calendar-session-rule")
def create_calendar_session_rule(
    *,
    calendar_uid: str,
    payload: Mapping[str, Any],
) -> CalendarSessionRule:
    runtime = _get_runtime()
    row = _create_calendar_session_rule_record(
        runtime.context,
        calendar_uid=calendar_uid,
        **dict(payload),
    )
    return CalendarSessionRule.model_validate(row)


@registry_write("calendar", "update:calendar-session-rule")
def update_calendar_session_rule(
    *,
    calendar_uid: str,
    uid: str,
    payload: Mapping[str, Any],
) -> CalendarSessionRule | None:
    runtime = _get_runtime()
    row = _update_calendar_session_rule_record(
        runtime.context,
        calendar_uid=calendar_uid,
        uid=uid,
        **dict(payload),
    )
    if row is None:
        return None
    return CalendarSessionRule.model_validate(row)


@registry_write("calendar", "delete:calendar-session-rule")
def delete_calendar_session_rule(*, calendar_uid: str, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(
        _delete_calendar_session_rule_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    )


@registry_write("calendar", "bulk-upsert:calendar-session-rules")
def bulk_upsert_calendar_session_rules(
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[CalendarSessionRule]:
    runtime = _get_runtime()
    result_rows = _bulk_upsert_calendar_session_rule_records(
        runtime.context,
        calendar_uid=calendar_uid,
        rows=rows,
    )
    return [CalendarSessionRule.model_validate(row) for row in result_rows]


def list_calendar_exceptions(
    *,
    calendar_uid: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    session_label: str | None = None,
    exception_type: str | None = None,
    source: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    runtime = _get_runtime()
    response = _list_calendar_exception_records_page(
        runtime.context,
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        session_label=session_label,
        exception_type=exception_type,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [CalendarException.model_validate(row) for row in response["results"]],
    }


def get_calendar_exception(*, calendar_uid: str, uid: str) -> CalendarException | None:
    runtime = _get_runtime()
    row = _get_calendar_exception_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    if row is None:
        return None
    return CalendarException.model_validate(row)


@registry_write("calendar", "create:calendar-exception")
def create_calendar_exception(
    *,
    calendar_uid: str,
    payload: Mapping[str, Any],
) -> CalendarException:
    runtime = _get_runtime()
    row = _create_calendar_exception_record(
        runtime.context,
        calendar_uid=calendar_uid,
        **dict(payload),
    )
    return CalendarException.model_validate(row)


@registry_write("calendar", "update:calendar-exception")
def update_calendar_exception(
    *,
    calendar_uid: str,
    uid: str,
    payload: Mapping[str, Any],
) -> CalendarException | None:
    runtime = _get_runtime()
    row = _update_calendar_exception_record(
        runtime.context,
        calendar_uid=calendar_uid,
        uid=uid,
        **dict(payload),
    )
    if row is None:
        return None
    return CalendarException.model_validate(row)


@registry_write("calendar", "delete:calendar-exception")
def delete_calendar_exception(*, calendar_uid: str, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(
        _delete_calendar_exception_record(runtime.context, calendar_uid=calendar_uid, uid=uid)
    )


@registry_write("calendar", "bulk-upsert:calendar-exceptions")
def bulk_upsert_calendar_exceptions(
    *,
    calendar_uid: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[CalendarException]:
    runtime = _get_runtime()
    result_rows = _bulk_upsert_calendar_exception_records(
        runtime.context,
        calendar_uid=calendar_uid,
        rows=rows,
    )
    return [CalendarException.model_validate(row) for row in result_rows]


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Calendar",
            "CalendarSessionRule",
            "CalendarException",
        ],
        row_model_name="Calendar apps/v1",
    )


def _list_calendar_records_page(context, **kwargs):
    from msm.services import list_calendar_records_page

    return list_calendar_records_page(context, **kwargs)


def _get_calendar_record(context, **kwargs):
    from msm.services import get_calendar_record

    return get_calendar_record(context, **kwargs)


def _get_calendar_frontend_detail_summary(context, **kwargs):
    from msm.services import get_calendar_frontend_detail_summary

    return get_calendar_frontend_detail_summary(context, **kwargs)


def _create_calendar_record(context, **kwargs):
    from msm.services import create_calendar_record

    return create_calendar_record(context, **kwargs)


def _update_calendar_record(context, **kwargs):
    from msm.services import update_calendar_record

    return update_calendar_record(context, **kwargs)


def _delete_calendar_record(context, **kwargs):
    from msm.services import delete_calendar_record

    return delete_calendar_record(context, **kwargs)


def _list_calendar_date_records_page(context, **kwargs):
    from msm.services import list_calendar_date_records_page

    return list_calendar_date_records_page(context, **kwargs)


def _list_calendar_session_records_page(context, **kwargs):
    from msm.services import list_calendar_session_records_page

    return list_calendar_session_records_page(context, **kwargs)


def _list_calendar_session_rule_records_page(context, **kwargs):
    from msm.services import list_calendar_session_rule_records_page

    return list_calendar_session_rule_records_page(context, **kwargs)


def _get_calendar_session_rule_record(context, **kwargs):
    from msm.services import get_calendar_session_rule_record

    return get_calendar_session_rule_record(context, **kwargs)


def _create_calendar_session_rule_record(context, **kwargs):
    from msm.services import create_calendar_session_rule_record

    return create_calendar_session_rule_record(context, **kwargs)


def _update_calendar_session_rule_record(context, **kwargs):
    from msm.services import update_calendar_session_rule_record

    return update_calendar_session_rule_record(context, **kwargs)


def _delete_calendar_session_rule_record(context, **kwargs):
    from msm.services import delete_calendar_session_rule_record

    return delete_calendar_session_rule_record(context, **kwargs)


def _bulk_upsert_calendar_session_rule_records(context, **kwargs):
    from msm.services import bulk_upsert_calendar_session_rule_records

    return bulk_upsert_calendar_session_rule_records(context, **kwargs)


def _list_calendar_exception_records_page(context, **kwargs):
    from msm.services import list_calendar_exception_records_page

    return list_calendar_exception_records_page(context, **kwargs)


def _get_calendar_exception_record(context, **kwargs):
    from msm.services import get_calendar_exception_record

    return get_calendar_exception_record(context, **kwargs)


def _create_calendar_exception_record(context, **kwargs):
    from msm.services import create_calendar_exception_record

    return create_calendar_exception_record(context, **kwargs)


def _update_calendar_exception_record(context, **kwargs):
    from msm.services import update_calendar_exception_record

    return update_calendar_exception_record(context, **kwargs)


def _delete_calendar_exception_record(context, **kwargs):
    from msm.services import delete_calendar_exception_record

    return delete_calendar_exception_record(context, **kwargs)


def _bulk_upsert_calendar_exception_records(context, **kwargs):
    from msm.services import bulk_upsert_calendar_exception_records

    return bulk_upsert_calendar_exception_records(context, **kwargs)
