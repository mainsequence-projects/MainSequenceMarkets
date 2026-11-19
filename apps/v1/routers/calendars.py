from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, status

from apps.v1.schemas.calendars import (
    BulkUpsertCalendarExceptionsRequest,
    BulkUpsertCalendarSessionRulesRequest,
    Calendar,
    CalendarCreate,
    CalendarException,
    CalendarExceptionCreateRequest,
    CalendarExceptionType,
    CalendarExceptionUpdate,
    CalendarSessionRule,
    CalendarSessionRuleCreateRequest,
    CalendarSessionRuleUpdate,
    CalendarUpdate,
    ComputedCalendarDate,
    ComputedCalendarSession,
)
from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.services.calendars import (
    bulk_upsert_calendar_exceptions,
    bulk_upsert_calendar_session_rules,
    create_calendar,
    create_calendar_exception,
    create_calendar_session_rule,
    delete_calendar,
    delete_calendar_exception,
    delete_calendar_session_rule,
    get_calendar,
    get_calendar_exception,
    get_calendar_session_rule,
    get_calendar_summary,
    list_calendar_dates,
    list_calendar_exceptions,
    list_calendar_session_rules,
    list_calendar_sessions,
    list_calendars,
    update_calendar,
    update_calendar_exception,
    update_calendar_session_rule,
)
from msm.api.http import (
    RESOURCE_COLLECTION_CONTRACT,
    ErrorResponse,
    ResourceCollection,
    resource_collection_response,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get(
    "/",
    response_model=ResourceCollection[Calendar],
    summary="List calendars",
    description=("Return calendars in the canonical Command Center resource collection contract."),
    operation_id="listCalendars",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid resource collection request.",
        }
    },
)
def get_calendars(
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across calendar uid, unique identifier, "
                "display name, type, source, and source identifier."
            ),
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of calendar rows to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered calendar list."),
    ] = 0,
    unique_identifier: Annotated[
        str | None,
        Query(description="Optional exact calendar unique identifier filter."),
    ] = None,
    unique_identifier_contains: Annotated[
        str | None,
        Query(description="Optional contains filter for calendar unique identifiers."),
    ] = None,
    calendar_type: Annotated[
        str | None,
        Query(description="Optional exact calendar type filter such as TRADING or SETTLEMENT."),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="Optional exact calendar source filter."),
    ] = None,
    source_identifier: Annotated[
        str | None,
        Query(description="Optional exact source-specific calendar identifier filter."),
    ] = None,
) -> ResourceCollection[Calendar]:
    response = list_calendars(
        search=search,
        limit=limit,
        offset=offset,
        unique_identifier=unique_identifier,
        unique_identifier_contains=unique_identifier_contains,
        calendar_type=calendar_type,
        source=source,
        source_identifier=source_identifier,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    response_model=Calendar,
    summary="Create calendar",
    description="Create one core calendar identity row.",
    operation_id="createCalendar",
)
def post_calendar(
    request: Annotated[
        CalendarCreate,
        Body(description="Create payload for a new calendar identity row."),
    ],
) -> Calendar:
    return create_calendar(payload=request.model_dump(exclude_none=True))


@router.get(
    "/{uid}/",
    response_model=Calendar,
    summary="Get calendar",
    description="Return one core calendar identity row by uid.",
    operation_id="getCalendar",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid calendar detail request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        },
    },
)
def get_calendar_by_uid(
    uid: str,
) -> Calendar:
    record = get_calendar(uid=uid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return record


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get calendar summary",
    description=(
        "Return the reusable frontend detail summary payload for one calendar identity row."
    ),
    operation_id="getCalendarSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        }
    },
)
def get_calendar_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_calendar_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return summary


@router.patch(
    "/{uid}/",
    response_model=Calendar,
    summary="Update calendar",
    description="Update mutable fields for one core calendar identity row.",
    operation_id="updateCalendar",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        }
    },
)
def patch_calendar(
    uid: str,
    request: Annotated[
        CalendarUpdate,
        Body(description="Patch payload for an existing calendar identity row."),
    ],
) -> Calendar:
    try:
        record = update_calendar(
            uid=uid,
            payload=request.model_dump(exclude_unset=True, exclude_none=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return record


@router.delete(
    "/{uid}/",
    response_model=Calendar | None,
    summary="Delete calendar",
    description=(
        "Delete one calendar identity row. Its session rules and exceptions are removed "
        "by the database cascade. The migrated API returns `null` on success."
    ),
    operation_id="deleteCalendar",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": (
                "The calendar is the trading calendar of an asset or the calendar of a "
                "portfolio. Move them to another calendar first."
            ),
        },
    },
)
def remove_calendar(uid: str) -> Calendar | None:
    try:
        deleted = delete_calendar(uid=uid)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return None


@router.get(
    "/{calendar_uid}/dates/",
    response_model=ResourceCollection[ComputedCalendarDate],
    summary="List calendar dates",
    description=(
        "Return the dates of one calendar from `start_date` to `end_date`. The dates are "
        "computed from the calendar's session rules and exceptions; nothing is stored per "
        "date, so an item has no uid and the collection is read-only. The flag filters, "
        "`limit` and `offset` apply to the computed dates."
    ),
    operation_id="listCalendarDates",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": (
                "`end_date` is before `start_date`, or the window is outside the calendar's "
                "`valid_from` to `valid_to` range."
            ),
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        },
    },
)
def get_calendar_dates(
    calendar_uid: str,
    start_date: Annotated[
        dt.date,
        Query(description="First local date of the window. Required."),
    ],
    end_date: Annotated[
        dt.date,
        Query(description="Last local date of the window. Required."),
    ],
    is_business_day: Annotated[
        bool | None,
        Query(description="Optional business-day flag filter."),
    ] = None,
    is_holiday: Annotated[
        bool | None,
        Query(description="Optional holiday flag filter."),
    ] = None,
    is_weekend: Annotated[
        bool | None,
        Query(description="Optional weekend flag filter."),
    ] = None,
    is_early_close: Annotated[
        bool | None,
        Query(description="Optional early-close flag filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of computed dates to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the computed date list."),
    ] = 0,
) -> ResourceCollection[ComputedCalendarDate]:
    try:
        response = list_calendar_dates(
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Calendar {calendar_uid!r} was not found.")
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{calendar_uid}/sessions/",
    response_model=ResourceCollection[ComputedCalendarSession],
    summary="List calendar sessions",
    description=(
        "Return the sessions of one calendar from `start_date` to `end_date`, with their "
        "UTC open and close. The sessions are computed from the calendar's session rules "
        "and exceptions; nothing is stored per session, so an item has no uid and the "
        "collection is read-only. The filters, `limit` and `offset` apply to the computed "
        "sessions."
    ),
    operation_id="listCalendarSessions",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": (
                "`end_date` is before `start_date`, or the window is outside the calendar's "
                "`valid_from` to `valid_to` range."
            ),
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        },
    },
)
def get_calendar_sessions(
    calendar_uid: str,
    start_date: Annotated[
        dt.date,
        Query(description="First local date of the window. Required."),
    ],
    end_date: Annotated[
        dt.date,
        Query(description="Last local date of the window. Required."),
    ],
    session_label: Annotated[
        str | None,
        Query(description="Optional exact session label filter."),
    ] = None,
    is_primary: Annotated[
        bool | None,
        Query(description="Optional primary-session flag filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of computed sessions to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the computed session list."),
    ] = 0,
) -> ResourceCollection[ComputedCalendarSession]:
    try:
        response = list_calendar_sessions(
            calendar_uid=calendar_uid,
            start_date=start_date,
            end_date=end_date,
            session_label=session_label,
            is_primary=is_primary,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Calendar {calendar_uid!r} was not found.")
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{calendar_uid}/rules/",
    response_model=ResourceCollection[CalendarSessionRule],
    summary="List calendar session rules",
    description=(
        "Return the session rules of one calendar: the regular week of each session, "
        "from a date on."
    ),
    operation_id="listCalendarSessionRules",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
)
def get_calendar_session_rules(
    calendar_uid: str,
    session_label: Annotated[
        str | None,
        Query(description="Optional exact session label filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of session rule rows to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the session rule row list."),
    ] = 0,
) -> ResourceCollection[CalendarSessionRule]:
    response = list_calendar_session_rules(
        calendar_uid=calendar_uid,
        session_label=session_label,
        limit=limit,
        offset=offset,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{calendar_uid}/rules/",
    response_model=CalendarSessionRule,
    summary="Create calendar session rule",
    description="Create one session rule under the path calendar uid.",
    operation_id="createCalendarSessionRule",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The session rule values were refused.",
        }
    },
)
def post_calendar_session_rule(
    calendar_uid: str,
    request: Annotated[
        CalendarSessionRuleCreateRequest,
        Body(description="Create payload for a calendar session rule row."),
    ],
) -> CalendarSessionRule:
    try:
        return create_calendar_session_rule(
            calendar_uid=calendar_uid,
            payload=request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{calendar_uid}/rules/bulk-upsert/",
    response_model=list[CalendarSessionRule],
    summary="Bulk upsert calendar session rules",
    description=(
        "Bulk upsert session rules under the path calendar uid. A rule is matched by "
        "session label and first date."
    ),
    operation_id="bulkUpsertCalendarSessionRules",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The session rule values were refused.",
        }
    },
)
def post_calendar_session_rules_bulk_upsert(
    calendar_uid: str,
    request: Annotated[
        BulkUpsertCalendarSessionRulesRequest,
        Body(description="Bulk upsert payload for calendar session rule rows."),
    ],
) -> list[CalendarSessionRule]:
    try:
        return bulk_upsert_calendar_session_rules(
            calendar_uid=calendar_uid,
            rows=[row.model_dump(exclude_none=True) for row in request.rows],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{calendar_uid}/rules/{rule_uid}/",
    response_model=CalendarSessionRule,
    summary="Get calendar session rule",
    description="Return one session rule by uid under the path calendar uid.",
    operation_id="getCalendarSessionRule",
    responses={
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar session rule uid was not found under this calendar."
            ),
        }
    },
)
def get_calendar_session_rule_by_uid(calendar_uid: str, rule_uid: str) -> CalendarSessionRule:
    record = get_calendar_session_rule(calendar_uid=calendar_uid, uid=rule_uid)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session rule {rule_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.patch(
    "/{calendar_uid}/rules/{rule_uid}/",
    response_model=CalendarSessionRule,
    summary="Update calendar session rule",
    description="Update mutable fields for one session rule under the path calendar uid.",
    operation_id="updateCalendarSessionRule",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The session rule values were refused.",
        },
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar session rule uid was not found under this calendar."
            ),
        },
    },
)
def patch_calendar_session_rule(
    calendar_uid: str,
    rule_uid: str,
    request: Annotated[
        CalendarSessionRuleUpdate,
        Body(description="Patch payload for an existing calendar session rule row."),
    ],
) -> CalendarSessionRule:
    try:
        record = update_calendar_session_rule(
            calendar_uid=calendar_uid,
            uid=rule_uid,
            payload=request.model_dump(exclude_unset=True, exclude_none=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session rule {rule_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.delete(
    "/{calendar_uid}/rules/{rule_uid}/",
    response_model=CalendarSessionRule | None,
    summary="Delete calendar session rule",
    description="Delete one session rule under the path calendar uid. Returns `null` on success.",
    operation_id="deleteCalendarSessionRule",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar session rule uid was not found under this calendar."
            ),
        }
    },
)
def remove_calendar_session_rule(calendar_uid: str, rule_uid: str) -> CalendarSessionRule | None:
    deleted = delete_calendar_session_rule(calendar_uid=calendar_uid, uid=rule_uid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session rule {rule_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return None


@router.get(
    "/{calendar_uid}/exceptions/",
    response_model=ResourceCollection[CalendarException],
    summary="List calendar exceptions",
    description=(
        "Return the exceptions of one calendar: its dated departures from the session "
        "rules, optionally bounded by local date."
    ),
    operation_id="listCalendarExceptions",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
)
def get_calendar_exceptions(
    calendar_uid: str,
    start_date: Annotated[
        dt.date | None,
        Query(description="Optional first local date to include."),
    ] = None,
    end_date: Annotated[
        dt.date | None,
        Query(description="Optional last local date to include."),
    ] = None,
    session_label: Annotated[
        str | None,
        Query(description="Optional exact session label filter."),
    ] = None,
    exception_type: Annotated[
        CalendarExceptionType | None,
        Query(description="Optional exception type filter."),
    ] = None,
    source: Annotated[
        str | None,
        Query(
            description=(
                "Optional exact source filter: `user`, or the name of the adapter that "
                "wrote the row."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of exception rows to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the exception row list."),
    ] = 0,
) -> ResourceCollection[CalendarException]:
    response = list_calendar_exceptions(
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        session_label=session_label,
        exception_type=exception_type.value if exception_type is not None else None,
        source=source,
        limit=limit,
        offset=offset,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{calendar_uid}/exceptions/",
    response_model=CalendarException,
    summary="Create calendar exception",
    description=(
        'Create one exception under the path calendar uid. The row is stored with `source="user"`.'
    ),
    operation_id="createCalendarException",
    responses={
        400: {
            "model": ErrorResponse,
            "description": (
                "The exception values were refused, or a `CLOSED` exception would stand next "
                "to another user exception for the same date and session."
            ),
        }
    },
)
def post_calendar_exception(
    calendar_uid: str,
    request: Annotated[
        CalendarExceptionCreateRequest,
        Body(description="Create payload for a calendar exception row."),
    ],
) -> CalendarException:
    try:
        return create_calendar_exception(
            calendar_uid=calendar_uid,
            payload=request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{calendar_uid}/exceptions/bulk-upsert/",
    response_model=list[CalendarException],
    summary="Bulk upsert calendar exceptions",
    description=(
        "Bulk upsert exceptions under the path calendar uid. The rows are stored with "
        '`source="user"` and matched by local date, session label and exception type.'
    ),
    operation_id="bulkUpsertCalendarExceptions",
    responses={
        400: {
            "model": ErrorResponse,
            "description": (
                "The exception values were refused, or a `CLOSED` exception would stand next "
                "to another user exception for the same date and session."
            ),
        }
    },
)
def post_calendar_exceptions_bulk_upsert(
    calendar_uid: str,
    request: Annotated[
        BulkUpsertCalendarExceptionsRequest,
        Body(description="Bulk upsert payload for calendar exception rows."),
    ],
) -> list[CalendarException]:
    try:
        return bulk_upsert_calendar_exceptions(
            calendar_uid=calendar_uid,
            rows=[row.model_dump(exclude_none=True) for row in request.rows],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{calendar_uid}/exceptions/{exception_uid}/",
    response_model=CalendarException,
    summary="Get calendar exception",
    description="Return one exception by uid under the path calendar uid.",
    operation_id="getCalendarException",
    responses={
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar exception uid was not found under this calendar."
            ),
        }
    },
)
def get_calendar_exception_by_uid(calendar_uid: str, exception_uid: str) -> CalendarException:
    record = get_calendar_exception(calendar_uid=calendar_uid, uid=exception_uid)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar exception {exception_uid!r} was not found "
                f"under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.patch(
    "/{calendar_uid}/exceptions/{exception_uid}/",
    response_model=CalendarException,
    summary="Update calendar exception",
    description="Update mutable fields for one exception under the path calendar uid.",
    operation_id="updateCalendarException",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The exception values were refused.",
        },
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar exception uid was not found under this calendar."
            ),
        },
    },
)
def patch_calendar_exception(
    calendar_uid: str,
    exception_uid: str,
    request: Annotated[
        CalendarExceptionUpdate,
        Body(description="Patch payload for an existing calendar exception row."),
    ],
) -> CalendarException:
    try:
        record = update_calendar_exception(
            calendar_uid=calendar_uid,
            uid=exception_uid,
            payload=request.model_dump(exclude_unset=True, exclude_none=False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar exception {exception_uid!r} was not found "
                f"under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.delete(
    "/{calendar_uid}/exceptions/{exception_uid}/",
    response_model=CalendarException | None,
    summary="Delete calendar exception",
    description="Delete one exception under the path calendar uid. Returns `null` on success.",
    operation_id="deleteCalendarException",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": (
                "The requested calendar exception uid was not found under this calendar."
            ),
        }
    },
)
def remove_calendar_exception(calendar_uid: str, exception_uid: str) -> CalendarException | None:
    deleted = delete_calendar_exception(calendar_uid=calendar_uid, uid=exception_uid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar exception {exception_uid!r} was not found "
                f"under calendar {calendar_uid!r}."
            ),
        )
    return None
