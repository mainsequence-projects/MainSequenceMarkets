from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Request, status

from apps.v1.schemas.calendars import (
    BulkUpsertCalendarDatesRequest,
    BulkUpsertCalendarEventsRequest,
    BulkUpsertCalendarSessionsRequest,
    Calendar,
    CalendarCreate,
    CalendarDate,
    CalendarDateCreateRequest,
    CalendarDateUpdate,
    CalendarEvent,
    CalendarEventCreateRequest,
    CalendarEventUpdate,
    CalendarSession,
    CalendarSessionCreateRequest,
    CalendarSessionUpdate,
    CalendarUpdate,
)
from apps.v1.schemas.common import (
    ErrorResponse,
    FrontEndDetailSummary,
    PaginatedResponse,
    build_paginated_response,
)
from apps.v1.services.calendars import (
    bulk_upsert_calendar_dates,
    bulk_upsert_calendar_events,
    bulk_upsert_calendar_sessions,
    create_calendar,
    create_calendar_date,
    create_calendar_event,
    create_calendar_session,
    delete_calendar,
    delete_calendar_date,
    delete_calendar_event,
    delete_calendar_session,
    get_calendar,
    get_calendar_date,
    get_calendar_event,
    get_calendar_session,
    get_calendar_summary,
    list_calendar_dates,
    list_calendar_events,
    list_calendar_sessions,
    list_calendars,
    update_calendar,
    update_calendar_date,
    update_calendar_event,
    update_calendar_session,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get(
    "/",
    response_model=PaginatedResponse[Calendar],
    summary="List calendars",
    description=(
        "Return core calendar identity rows. The `response_format` query parameter "
        "is accepted for compatibility, but rows use the `msm.api.calendars.Calendar` contract."
    ),
    operation_id="listCalendars",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        }
    },
)
def get_calendars(
    request: Request,
    response_format: Annotated[
        str,
        Query(description="Supported value for this endpoint is `frontend_list`."),
    ] = "frontend_list",
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
) -> PaginatedResponse[Calendar]:
    _require_response_format(
        response_format,
        expected="frontend_list",
        route="GET /api/v1/calendar/",
    )
    rows = list_calendars(
        search=search,
        limit=limit + 1,
        offset=offset,
        unique_identifier=unique_identifier,
        unique_identifier_contains=unique_identifier_contains,
        calendar_type=calendar_type,
        source=source,
        source_identifier=source_identifier,
    )
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
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
            "description": "Unsupported response format or invalid request boundary input.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        },
    },
)
def get_calendar_by_uid(
    uid: str,
    response_format: Annotated[
        str,
        Query(description="Supported value for this endpoint is `frontend_detail`."),
    ] = "frontend_detail",
) -> Calendar:
    _require_response_format(
        response_format,
        expected="frontend_detail",
        route="GET /api/v1/calendar/{uid}/",
    )
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
    record = update_calendar(
        uid=uid,
        payload=request.model_dump(exclude_unset=True, exclude_none=False),
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return record


@router.delete(
    "/{uid}/",
    response_model=Calendar | None,
    summary="Delete calendar",
    description=(
        "Delete one calendar identity row. Calendar date, session, and event rows "
        "are removed by the database cascade. The migrated API returns `null` on success."
    ),
    operation_id="deleteCalendar",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar uid was not found.",
        }
    },
)
def remove_calendar(uid: str) -> Calendar | None:
    deleted = delete_calendar(uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Calendar {uid!r} was not found.")
    return None


@router.get(
    "/{calendar_uid}/dates/",
    response_model=PaginatedResponse[CalendarDate],
    summary="List calendar dates",
    description="Return bounded local-date facts for one calendar.",
    operation_id="listCalendarDates",
)
def get_calendar_dates(
    request: Request,
    calendar_uid: str,
    start_date: Annotated[
        dt.date | None,
        Query(description="Optional first local date to include."),
    ] = None,
    end_date: Annotated[
        dt.date | None,
        Query(description="Optional last local date to include."),
    ] = None,
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
        Query(ge=1, le=10000, description="Maximum number of date rows to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the date row list."),
    ] = 0,
) -> PaginatedResponse[CalendarDate]:
    rows = list_calendar_dates(
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        is_business_day=is_business_day,
        is_holiday=is_holiday,
        is_weekend=is_weekend,
        is_early_close=is_early_close,
        limit=limit + 1,
        offset=offset,
    )
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{calendar_uid}/dates/",
    response_model=CalendarDate,
    summary="Create calendar date",
    description="Create one local-date fact under the path calendar uid.",
    operation_id="createCalendarDate",
)
def post_calendar_date(
    calendar_uid: str,
    request: Annotated[
        CalendarDateCreateRequest,
        Body(description="Create payload for a calendar date row."),
    ],
) -> CalendarDate:
    return create_calendar_date(
        calendar_uid=calendar_uid,
        payload=request.model_dump(exclude_none=True),
    )


@router.post(
    "/{calendar_uid}/dates/bulk-upsert/",
    response_model=list[CalendarDate],
    summary="Bulk upsert calendar dates",
    description="Bulk upsert local-date facts under the path calendar uid.",
    operation_id="bulkUpsertCalendarDates",
)
def post_calendar_dates_bulk_upsert(
    calendar_uid: str,
    request: Annotated[
        BulkUpsertCalendarDatesRequest,
        Body(description="Bulk upsert payload for calendar date rows."),
    ],
) -> list[CalendarDate]:
    return bulk_upsert_calendar_dates(
        calendar_uid=calendar_uid,
        rows=[row.model_dump(exclude_none=True) for row in request.rows],
    )


@router.get(
    "/{calendar_uid}/dates/{date_uid}/",
    response_model=CalendarDate,
    summary="Get calendar date",
    description="Return one local-date fact by uid under the path calendar uid.",
    operation_id="getCalendarDate",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar date uid was not found under this calendar.",
        }
    },
)
def get_calendar_date_by_uid(calendar_uid: str, date_uid: str) -> CalendarDate:
    record = get_calendar_date(calendar_uid=calendar_uid, uid=date_uid)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar date {date_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return record


@router.patch(
    "/{calendar_uid}/dates/{date_uid}/",
    response_model=CalendarDate,
    summary="Update calendar date",
    description="Update mutable facts for one local-date row under the path calendar uid.",
    operation_id="updateCalendarDate",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar date uid was not found under this calendar.",
        }
    },
)
def patch_calendar_date(
    calendar_uid: str,
    date_uid: str,
    request: Annotated[
        CalendarDateUpdate,
        Body(description="Patch payload for an existing calendar date row."),
    ],
) -> CalendarDate:
    record = update_calendar_date(
        calendar_uid=calendar_uid,
        uid=date_uid,
        payload=request.model_dump(exclude_unset=True, exclude_none=False),
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar date {date_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return record


@router.delete(
    "/{calendar_uid}/dates/{date_uid}/",
    response_model=CalendarDate | None,
    summary="Delete calendar date",
    description="Delete one local-date row under the path calendar uid. Returns `null` on success.",
    operation_id="deleteCalendarDate",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar date uid was not found under this calendar.",
        }
    },
)
def remove_calendar_date(calendar_uid: str, date_uid: str) -> CalendarDate | None:
    deleted = delete_calendar_date(calendar_uid=calendar_uid, uid=date_uid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar date {date_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return None


@router.get(
    "/{calendar_uid}/sessions/",
    response_model=PaginatedResponse[CalendarSession],
    summary="List calendar sessions",
    description="Return session rows for one calendar, optionally bounded by local date.",
    operation_id="listCalendarSessions",
)
def get_calendar_sessions(
    request: Request,
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
    is_primary: Annotated[
        bool | None,
        Query(description="Optional primary-session flag filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of session rows to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the session row list."),
    ] = 0,
) -> PaginatedResponse[CalendarSession]:
    rows = list_calendar_sessions(
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        session_label=session_label,
        is_primary=is_primary,
        limit=limit + 1,
        offset=offset,
    )
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{calendar_uid}/sessions/",
    response_model=CalendarSession,
    summary="Create calendar session",
    description="Create one session row under the path calendar uid.",
    operation_id="createCalendarSession",
)
def post_calendar_session(
    calendar_uid: str,
    request: Annotated[
        CalendarSessionCreateRequest,
        Body(description="Create payload for a calendar session row."),
    ],
) -> CalendarSession:
    return create_calendar_session(
        calendar_uid=calendar_uid,
        payload=request.model_dump(exclude_none=True),
    )


@router.post(
    "/{calendar_uid}/sessions/bulk-upsert/",
    response_model=list[CalendarSession],
    summary="Bulk upsert calendar sessions",
    description="Bulk upsert session rows under the path calendar uid.",
    operation_id="bulkUpsertCalendarSessions",
)
def post_calendar_sessions_bulk_upsert(
    calendar_uid: str,
    request: Annotated[
        BulkUpsertCalendarSessionsRequest,
        Body(description="Bulk upsert payload for calendar session rows."),
    ],
) -> list[CalendarSession]:
    return bulk_upsert_calendar_sessions(
        calendar_uid=calendar_uid,
        rows=[row.model_dump(exclude_none=True) for row in request.rows],
    )


@router.get(
    "/{calendar_uid}/sessions/{session_uid}/",
    response_model=CalendarSession,
    summary="Get calendar session",
    description="Return one session row by uid under the path calendar uid.",
    operation_id="getCalendarSession",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar session uid was not found under this calendar.",
        }
    },
)
def get_calendar_session_by_uid(calendar_uid: str, session_uid: str) -> CalendarSession:
    record = get_calendar_session(calendar_uid=calendar_uid, uid=session_uid)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session {session_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.patch(
    "/{calendar_uid}/sessions/{session_uid}/",
    response_model=CalendarSession,
    summary="Update calendar session",
    description="Update mutable fields for one session row under the path calendar uid.",
    operation_id="updateCalendarSession",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar session uid was not found under this calendar.",
        }
    },
)
def patch_calendar_session(
    calendar_uid: str,
    session_uid: str,
    request: Annotated[
        CalendarSessionUpdate,
        Body(description="Patch payload for an existing calendar session row."),
    ],
) -> CalendarSession:
    record = update_calendar_session(
        calendar_uid=calendar_uid,
        uid=session_uid,
        payload=request.model_dump(exclude_unset=True, exclude_none=False),
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session {session_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return record


@router.delete(
    "/{calendar_uid}/sessions/{session_uid}/",
    response_model=CalendarSession | None,
    summary="Delete calendar session",
    description="Delete one session row under the path calendar uid. Returns `null` on success.",
    operation_id="deleteCalendarSession",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar session uid was not found under this calendar.",
        }
    },
)
def remove_calendar_session(calendar_uid: str, session_uid: str) -> CalendarSession | None:
    deleted = delete_calendar_session(calendar_uid=calendar_uid, uid=session_uid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Calendar session {session_uid!r} was not found under calendar {calendar_uid!r}."
            ),
        )
    return None


@router.get(
    "/{calendar_uid}/events/",
    response_model=PaginatedResponse[CalendarEvent],
    summary="List calendar events",
    description="Return event rows for one calendar, optionally bounded by event date.",
    operation_id="listCalendarEvents",
)
def get_calendar_events(
    request: Request,
    calendar_uid: str,
    start_date: Annotated[
        dt.date | None,
        Query(description="Optional first event date to include."),
    ] = None,
    end_date: Annotated[
        dt.date | None,
        Query(description="Optional last event date to include."),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(description="Optional exact event type filter."),
    ] = None,
    event_label: Annotated[
        str | None,
        Query(description="Optional exact event label filter."),
    ] = None,
    target_type: Annotated[
        str | None,
        Query(description="Optional exact event target type filter."),
    ] = None,
    target_uid: Annotated[
        str | None,
        Query(description="Optional exact event target uid filter."),
    ] = None,
    target_identifier: Annotated[
        str | None,
        Query(description="Optional exact event target identifier filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of event rows to return."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the event row list."),
    ] = 0,
) -> PaginatedResponse[CalendarEvent]:
    rows = list_calendar_events(
        calendar_uid=calendar_uid,
        start_date=start_date,
        end_date=end_date,
        event_type=event_type,
        event_label=event_label,
        target_type=target_type,
        target_uid=target_uid,
        target_identifier=target_identifier,
        limit=limit + 1,
        offset=offset,
    )
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{calendar_uid}/events/",
    response_model=CalendarEvent,
    summary="Create calendar event",
    description="Create one calendar-level event row under the path calendar uid.",
    operation_id="createCalendarEvent",
)
def post_calendar_event(
    calendar_uid: str,
    request: Annotated[
        CalendarEventCreateRequest,
        Body(description="Create payload for a calendar event row."),
    ],
) -> CalendarEvent:
    return create_calendar_event(
        calendar_uid=calendar_uid,
        payload=request.model_dump(exclude_none=True),
    )


@router.post(
    "/{calendar_uid}/events/bulk-upsert/",
    response_model=list[CalendarEvent],
    summary="Bulk upsert calendar events",
    description="Bulk upsert calendar-level event rows under the path calendar uid.",
    operation_id="bulkUpsertCalendarEvents",
)
def post_calendar_events_bulk_upsert(
    calendar_uid: str,
    request: Annotated[
        BulkUpsertCalendarEventsRequest,
        Body(description="Bulk upsert payload for calendar event rows."),
    ],
) -> list[CalendarEvent]:
    return bulk_upsert_calendar_events(
        calendar_uid=calendar_uid,
        rows=[row.model_dump(exclude_none=True) for row in request.rows],
    )


@router.get(
    "/{calendar_uid}/events/{event_uid}/",
    response_model=CalendarEvent,
    summary="Get calendar event",
    description="Return one calendar-level event row by uid under the path calendar uid.",
    operation_id="getCalendarEvent",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar event uid was not found under this calendar.",
        }
    },
)
def get_calendar_event_by_uid(calendar_uid: str, event_uid: str) -> CalendarEvent:
    record = get_calendar_event(calendar_uid=calendar_uid, uid=event_uid)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar event {event_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return record


@router.patch(
    "/{calendar_uid}/events/{event_uid}/",
    response_model=CalendarEvent,
    summary="Update calendar event",
    description="Update mutable fields for one calendar-level event under the path calendar uid.",
    operation_id="updateCalendarEvent",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar event uid was not found under this calendar.",
        }
    },
)
def patch_calendar_event(
    calendar_uid: str,
    event_uid: str,
    request: Annotated[
        CalendarEventUpdate,
        Body(description="Patch payload for an existing calendar event row."),
    ],
) -> CalendarEvent:
    record = update_calendar_event(
        calendar_uid=calendar_uid,
        uid=event_uid,
        payload=request.model_dump(exclude_unset=True, exclude_none=False),
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar event {event_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return record


@router.delete(
    "/{calendar_uid}/events/{event_uid}/",
    response_model=CalendarEvent | None,
    summary="Delete calendar event",
    description="Delete one calendar-level event under the path calendar uid. Returns `null` on success.",
    operation_id="deleteCalendarEvent",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested calendar event uid was not found under this calendar.",
        }
    },
)
def remove_calendar_event(calendar_uid: str, event_uid: str) -> CalendarEvent | None:
    deleted = delete_calendar_event(calendar_uid=calendar_uid, uid=event_uid)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar event {event_uid!r} was not found under calendar {calendar_uid!r}.",
        )
    return None


def _require_response_format(value: str, *, expected: str, route: str) -> None:
    if value == expected:
        return
    raise HTTPException(
        status_code=400,
        detail=f"Only response_format={expected} is implemented for {route}.",
    )
