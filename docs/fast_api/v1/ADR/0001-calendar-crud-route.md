# 0001. Calendar CRUD Route For FastAPI v1

## Status

Proposed

## Date

2026-06-05

## Context

ADR 0028 defines calendars as core market reference data with four persisted
concepts:

- `CalendarTable` for calendar identity, type, source, timezone, and validity
  horizon
- `CalendarDateTable` for one bounded local-date fact per calendar date
- `CalendarSessionTable` for optional intraday sessions on calendar dates
- `CalendarEventTable` for calendar-level convention events

The current codebase has implemented those core concepts under `src/msm`:

- `msm.models.calendars`
- `msm.api.calendars`
- `msm.repositories.calendars`
- `msm.services.calendars`

The local FastAPI v1 surface under `apps/v1` is intentionally a thin resolver
layer. Route handlers should parse HTTP inputs, call reusable `src/` APIs or
services, and serialize declared Pydantic response models. Calendar maintenance
must follow that rule: `apps/v1` must not become a separate calendar business
logic layer.

The project owner also explicitly does not want this work to start by running
SDK or scaffold refresh commands that mutate local files. Any future execution
of those commands requires separate approval.

## Decision

Add a new FastAPI v1 route group at:

```text
/api/v1/calendar/
```

The route group will expose calendar identity list, detail, and CRUD operations,
plus bounded maintenance operations for related date, session, and event rows.
The route is singular to match existing `apps/v1` route style such as
`/asset/`, `/index/`, and `/account/`.

The FastAPI layer will call `src/msm` calendar APIs and services. It will not
compile SQL directly, materialize calendars inline, or duplicate calendar row
validation already owned by `msm.api.calendars`.

## Success Criteria

The route plan is successful when a future implementation provides:

- documented OpenAPI contracts for calendar list, detail, create, update, and
  delete operations
- documented OpenAPI contracts for date, session, and event maintenance under a
  specific calendar
- response models based on the core `msm.api.calendars` row models whenever the
  endpoint returns one calendar resource type
- local request models only for HTTP-boundary wrappers such as path-scoped child
  creation, bulk upsert, or composed detail views
- route handlers that remain thin and delegate behavior into `apps/v1/services`
  and then `src/msm`
- focused tests under `tests/msm/fastapi/v1/`
- FastAPI documentation updated under `docs/fast_api/v1/`

## Proposed Route Contract

### Calendar Identity

```text
GET    /api/v1/calendar/
POST   /api/v1/calendar/
GET    /api/v1/calendar/{uid}/
PATCH  /api/v1/calendar/{uid}/
DELETE /api/v1/calendar/{uid}/
```

`GET /api/v1/calendar/` should support:

- `response_format=frontend_list`
- `search`
- `limit`
- `offset`
- `unique_identifier`
- `unique_identifier_contains`
- `calendar_type`
- `source`
- `source_identifier`

The list response should return `list[Calendar]`, where `Calendar` is imported
from `msm.api.calendars`.

`POST /api/v1/calendar/` should accept the core `CalendarCreate` payload and
return `Calendar`.

`GET /api/v1/calendar/{uid}/` should return `Calendar` by default. If a composed
maintenance detail view is needed later, add explicit include flags:

- `include_dates`
- `include_sessions`
- `include_events`
- `start_date`
- `end_date`

Those flags must return a declared composed response model, not an ad hoc
dictionary.

`PATCH /api/v1/calendar/{uid}/` should accept the core `CalendarUpdate` payload
and return `Calendar`.

`DELETE /api/v1/calendar/{uid}/` should return `null` on success, matching
existing `apps/v1` delete behavior. Deleting a calendar relies on the calendar
table foreign-key cascade for child date, session, and event rows.

### Calendar Dates

```text
GET    /api/v1/calendar/{calendar_uid}/dates/
POST   /api/v1/calendar/{calendar_uid}/dates/
POST   /api/v1/calendar/{calendar_uid}/dates/bulk-upsert/
GET    /api/v1/calendar/{calendar_uid}/dates/{date_uid}/
PATCH  /api/v1/calendar/{calendar_uid}/dates/{date_uid}/
DELETE /api/v1/calendar/{calendar_uid}/dates/{date_uid}/
```

Date list should require or strongly prefer a bounded date range:

- `start_date`
- `end_date`

Optional filters:

- `is_business_day`
- `is_holiday`
- `is_weekend`
- `is_early_close`
- `limit`
- `offset`

Single-row create should path-scope `calendar_uid` and accept the remaining
`CalendarDateCreate` fields. The service layer may merge the path
`calendar_uid` into the core payload before calling `msm.api.calendars`.

`PATCH` should use `CalendarDateUpdate`. Calendar identity fields such as
`calendar_uid` and `local_date` are not mutable through patch; changing them is
a delete/create operation.

Bulk upsert should delegate to `msm.services.calendars.materialize_calendar_rows`
or an equivalent `src/msm` helper, not route-local loops.

### Calendar Sessions

```text
GET    /api/v1/calendar/{calendar_uid}/sessions/
POST   /api/v1/calendar/{calendar_uid}/sessions/
POST   /api/v1/calendar/{calendar_uid}/sessions/bulk-upsert/
GET    /api/v1/calendar/{calendar_uid}/sessions/{session_uid}/
PATCH  /api/v1/calendar/{calendar_uid}/sessions/{session_uid}/
DELETE /api/v1/calendar/{calendar_uid}/sessions/{session_uid}/
```

Session list should support:

- `start_date`
- `end_date`
- `session_label`
- `is_primary`
- `limit`
- `offset`

`POST` should path-scope `calendar_uid` and accept the remaining
`CalendarSessionCreate` fields.

`PATCH` should use `CalendarSessionUpdate`. Natural-key fields such as
`calendar_uid`, `local_date`, and `session_label` are not mutable through patch.
Changing the session key is a delete/create operation.

### Calendar Events

```text
GET    /api/v1/calendar/{calendar_uid}/events/
POST   /api/v1/calendar/{calendar_uid}/events/
POST   /api/v1/calendar/{calendar_uid}/events/bulk-upsert/
GET    /api/v1/calendar/{calendar_uid}/events/{event_uid}/
PATCH  /api/v1/calendar/{calendar_uid}/events/{event_uid}/
DELETE /api/v1/calendar/{calendar_uid}/events/{event_uid}/
```

Event list should support:

- `start_date`
- `end_date`
- `event_type`
- `event_label`
- `target_type`
- `target_uid`
- `target_identifier`
- `limit`
- `offset`

`POST` should path-scope `calendar_uid` and accept the remaining
`CalendarEventCreate` fields.

`PATCH` should use `CalendarEventUpdate`. Natural-key fields such as
`event_date`, `event_type`, `event_label`, `target_type`, and
`target_identifier` are not mutable through patch. Changing those values is a
delete/create operation.

## Required Implementation Shape

Future implementation should add:

- `apps/v1/routers/calendars.py`
- `apps/v1/schemas/calendars.py`
- `apps/v1/services/calendars.py`
- router registration and a `calendar` OpenAPI tag in `apps/v1/main.py`
- calendar model names in `apps/v1/runtime_bootstrap.py`
- tests in `tests/msm/fastapi/v1/test_calendars.py`

If `src/msm` does not yet expose a helper needed for relationship maintenance,
add the helper under `src/msm` first. Good candidates are:

- calendar date list/detail/delete helpers
- calendar session list/detail/delete helpers
- calendar event list/detail/delete helpers
- bulk upsert wrappers that validate rows through core calendar payload models

The FastAPI service layer may normalize operation results into Pydantic models,
but it must not own calendar semantics.

## Error Behavior

The route group should use existing `apps/v1` behavior:

- `400` for unsupported compatibility modes or invalid HTTP-boundary inputs
- `404` when the requested calendar or child row does not exist
- `422` for Pydantic request validation failures
- `200` with `null` for successful deletes

Child-row detail, patch, and delete operations should verify the child row
belongs to the path `calendar_uid`. A row with a different parent calendar
should be treated as not found for this nested route.

## Non-Goals

This route will not:

- edit portfolio calendar relationships
- materialize a calendar from `pandas_market_calendars` inline in a route
- expose QuantLib-specific pricing calendar behavior
- create a separate frontend-only calendar projection when a core
  `msm.api.calendars` model is sufficient
- run SDK/scaffold update commands as part of implementation without explicit
  user approval

## Validation Plan

Future implementation should validate with:

```text
python -m pytest tests/msm/fastapi/v1/test_calendars.py
python -m pytest tests/msm/api/calendars tests/msm/models/calendars
python -m py_compile apps/v1/main.py
git diff --check
```

If local FastAPI runtime validation is required, inspect:

```text
GET /openapi.json
GET /docs
```

The OpenAPI schema should show the `calendar` tag, declared request models, and
declared response models for every new endpoint.

## Documentation Follow-Up

After implementation, update `docs/fast_api/v1/index.md` with the implemented
calendar route behavior and cross-link to `docs/knowledge/msm/calendars/`.

ADR 0028 should also be reconciled later because its status text says the
calendar model is not yet implemented, while the current repository already has
calendar models, row APIs, repositories, and services.
