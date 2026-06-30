# Calendars

Route group for calendar identity CRUD, summary composition, and bounded
maintenance of the calendar's date, session, and event rows. Child date,
session, and event routes are scoped to a path calendar uid.

- `GET /api/v1/calendar/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, and `offset`
  - supports exact filters for `unique_identifier`, `calendar_type`, `source`,
    and `source_identifier`
  - supports `unique_identifier_contains`
  - returns the library `msm.api.calendars.Calendar` contract
- `POST /api/v1/calendar/`
  - creates one calendar identity row
  - request body uses the library `CalendarCreate` contract
  - returns the created `Calendar` row
- `GET /api/v1/calendar/{uid}/`
  - supports `response_format=frontend_detail`
  - returns one library `Calendar` row by uid
- `GET /api/v1/calendar/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for calendar detail
    pages
  - resolves the calendar by `uid`
  - includes calendar identity, type/timezone badges, validity horizon, label
    management placeholders, and related date/session/event route links
- `PATCH /api/v1/calendar/{uid}/`
  - updates mutable calendar identity fields
  - request body uses the library `CalendarUpdate` contract
  - returns the updated `Calendar` row
- `DELETE /api/v1/calendar/{uid}/`
  - deletes one calendar identity row
  - returns `null` on success
  - related date, session, and event rows are removed by database cascade
- `GET /api/v1/calendar/{calendar_uid}/dates/`
  - lists `CalendarDate` rows for one calendar
  - supports `start_date`, `end_date`, flag filters, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/dates/`
  - creates one date row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/dates/bulk-upsert/`
  - bulk upserts date rows under the path calendar uid
- `GET`, `PATCH`, and `DELETE /api/v1/calendar/{calendar_uid}/dates/{date_uid}/`
  - manage one date row and require it to belong to the path calendar uid
- `GET /api/v1/calendar/{calendar_uid}/sessions/`
  - lists `CalendarSession` rows for one calendar
  - supports `start_date`, `end_date`, `session_label`, `is_primary`,
    `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/sessions/`
  - creates one session row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/sessions/bulk-upsert/`
  - bulk upserts session rows under the path calendar uid
- `GET`, `PATCH`, and
  `DELETE /api/v1/calendar/{calendar_uid}/sessions/{session_uid}/`
  - manage one session row and require it to belong to the path calendar uid
- `GET /api/v1/calendar/{calendar_uid}/events/`
  - lists `CalendarEvent` rows for one calendar
  - supports `start_date`, `end_date`, `event_type`, `event_label`,
    `target_type`, `target_uid`, `target_identifier`, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/events/`
  - creates one event row under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/events/bulk-upsert/`
  - bulk upserts event rows under the path calendar uid
- `GET`, `PATCH`, and `DELETE /api/v1/calendar/{calendar_uid}/events/{event_uid}/`
  - manage one event row and require it to belong to the path calendar uid

## Related Concepts

- [Calendars knowledge](../../knowledge/msm/calendars/index.md)
