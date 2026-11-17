# Calendars

Route group for calendars. A calendar is stored as an identity row, its session
rules and its exceptions
([ADR 0055](../../ADR/0055-calendars-as-rules-and-exceptions.md)). Dates and
sessions are not stored: the API computes them for a requested window.

| Resource | Stored | Routes |
|---|---|---|
| Calendar | Yes | list, create, get, summary, update, delete |
| Session rule | Yes | list, create, bulk upsert, get, update, delete |
| Exception | Yes | list, create, bulk upsert, get, update, delete |
| Date | No, computed | list a window |
| Session | No, computed | list a window |

Every list route returns `command-center.resource_collection@v1` and has a
sibling `/discovery/` route.

## Calendar

- `GET /api/v1/calendar/`
  - supports `search`, `limit`, and `offset`
  - supports exact filters for `unique_identifier`, `calendar_type`, `source`,
    and `source_identifier`
  - supports `unique_identifier_contains`
  - returns library `msm.api.calendars.Calendar` rows
- `POST /api/v1/calendar/`
  - creates one calendar identity row
  - request body uses the library `CalendarCreate` contract
  - returns the created `Calendar` row
- `GET /api/v1/calendar/{uid}/`
  - returns one `Calendar` row by uid
- `GET /api/v1/calendar/{uid}/summary/`
  - returns the reusable `FrontEndDetailSummary` response for calendar detail
    pages
  - includes calendar identity, type and timezone badges, the valid range, and
    links to the date, session, rule and exception routes
- `PATCH /api/v1/calendar/{uid}/`
  - updates mutable calendar identity fields
  - request body uses the library `CalendarUpdate` contract
  - returns the updated `Calendar` row
- `DELETE /api/v1/calendar/{uid}/`
  - deletes one calendar identity row
  - returns `null` on success
  - its session rules and exceptions are removed by database cascade

`valid_from` and `valid_to` are optional. They are the first and last date the
calendar's rules and exceptions are complete for. `valid_to` is null on a
calendar with nothing to project, such as a 24/7 calendar. A null bound is not
checked.

## Dates And Sessions

```text
GET /api/v1/calendar/{calendar_uid}/dates/?start_date=2024-11-25&end_date=2024-12-31
GET /api/v1/calendar/{calendar_uid}/sessions/?start_date=2024-11-25&end_date=2024-12-31
```

Both routes are read-only. They compute the window from the calendar's session
rules and exceptions.

- `start_date` and `end_date` are required. A request without one of them
  returns `422`.
- `limit` and `offset` page the computed rows. There is no cap on the length of
  the window.
- Dates accept the flag filters `is_business_day`, `is_holiday`, `is_weekend`
  and `is_early_close`.
- Sessions accept `session_label` and `is_primary`.
- The filters apply to the computed rows.

A computed item has no `uid`. A date has `calendar_uid`, `local_date`,
`is_business_day`, `is_holiday`, `is_weekend`, `is_early_close` and
`holiday_name`:

```json
{
  "calendar_uid": "00000000-0000-0000-0000-000000000001",
  "local_date": "2024-11-28",
  "is_business_day": false,
  "is_holiday": true,
  "is_weekend": false,
  "is_early_close": false,
  "holiday_name": "Thanksgiving"
}
```

A session has `calendar_uid`, `local_date`, `session_label`, `opens_at`,
`closes_at`, `timezone`, `is_primary`, `is_early_close` and `is_late_open`.
`opens_at` and `closes_at` are UTC instants:

```json
{
  "calendar_uid": "00000000-0000-0000-0000-000000000001",
  "local_date": "2024-11-29",
  "session_label": "regular",
  "opens_at": "2024-11-29T14:30:00Z",
  "closes_at": "2024-11-29T18:00:00Z",
  "timezone": "America/New_York",
  "is_primary": true,
  "is_early_close": true,
  "is_late_open": false
}
```

| Status | Meaning |
|---|---|
| 400 | `end_date` is before `start_date`, or the window is outside the calendar's `valid_from` to `valid_to` range. The detail names the calendar and its range. |
| 404 | The calendar uid was not found. |
| 422 | `start_date` or `end_date` is missing or is not a date. |

The discovery documents of both collections name `local_date` (dates) and
`local_date` plus `session_label` (sessions) as identity. Their `extensions`
declare the window:

```json
{"computed": true, "read_only": true, "required_filters": ["start_date", "end_date"]}
```

## Session Rules

A session rule is the regular week of one session, from a date on. A change of
regular hours, or of the weekend, is a new rule row.

- `GET /api/v1/calendar/{calendar_uid}/rules/`
  - lists `CalendarSessionRule` rows for one calendar
  - supports `session_label`, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/rules/`
  - creates one rule under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/rules/bulk-upsert/`
  - bulk upserts rules under the path calendar uid
  - a rule is matched by `session_label` and `effective_from`
- `GET`, `PATCH`, and `DELETE /api/v1/calendar/{calendar_uid}/rules/{rule_uid}/`
  - manage one rule and require it to belong to the path calendar uid

Create body:

```json
{
  "session_label": "regular",
  "effective_from": "1985-01-01",
  "effective_to": null,
  "weekdays": "1111100",
  "opens_at_local": "09:30",
  "closes_at_local": "16:00",
  "open_day_offset": 0,
  "close_day_offset": 0,
  "is_primary": true
}
```

- `weekdays` is seven characters of `0` and `1`, Monday first.
- `opens_at_local` and `closes_at_local` are wall-clock times in the calendar's
  timezone, as `HH:MM` or `HH:MM:SS`. They are stored as `HH:MM:SS`. Both are
  null for a date-only calendar.
- `open_day_offset` and `close_day_offset` are days from the session's local
  date. `-1` opens the evening before. `1` closes at the next midnight.
- `PATCH` changes `effective_to`, `weekdays`, the times, the offsets and
  `is_primary`.

## Exceptions

An exception is one dated departure from the rules.

- `GET /api/v1/calendar/{calendar_uid}/exceptions/`
  - lists `CalendarException` rows for one calendar
  - supports `start_date`, `end_date`, `session_label`, `exception_type`,
    `source`, `limit`, and `offset`
- `POST /api/v1/calendar/{calendar_uid}/exceptions/`
  - creates one exception under the path calendar uid
- `POST /api/v1/calendar/{calendar_uid}/exceptions/bulk-upsert/`
  - bulk upserts exceptions under the path calendar uid
  - an exception is matched by `local_date`, `session_label` and
    `exception_type`
- `GET`, `PATCH`, and
  `DELETE /api/v1/calendar/{calendar_uid}/exceptions/{exception_uid}/`
  - manage one exception and require it to belong to the path calendar uid

Create body:

```json
{
  "local_date": "2024-12-24",
  "session_label": "",
  "exception_type": "EARLY_CLOSE",
  "closes_at_local": "13:00",
  "name": "Christmas Eve"
}
```

| `exception_type` | Meaning | Times |
|---|---|---|
| `CLOSED` | No session on that date. | None. |
| `EARLY_CLOSE` | The session closes at another time. | `closes_at_local` only. |
| `LATE_OPEN` | The session opens at another time. | `opens_at_local` only. |
| `OPEN` | A session runs on that date. | Optional. The rule's times hold where none is given. |

- `session_label` is the session the exception changes. It is empty for the
  whole day.
- `source` says who wrote the row. A row written through these routes has
  `source="user"`. A row an adapter wrote has the adapter's name, such as
  `pandas_market_calendars`. `source` is returned and is a list filter. A create,
  bulk-upsert or update body that contains it returns `422`.
- A date that has any `user` row is computed from its `user` rows alone. The
  adapter's rows for that date are ignored, not deleted. To cancel a closure the
  adapter wrote, create an `OPEN` exception for that date. To restore the
  adapter's answer, delete the `user` row.
- `PATCH` changes `opens_at_local`, `closes_at_local`, `name` and
  `metadata_json`.

| Status | Meaning |
|---|---|
| 400 | The values were refused. A `CLOSED` exception next to another `user` exception for the same date and session is refused. |
| 404 | The exception uid was not found under this calendar. |
| 422 | The body is malformed, names an unknown `exception_type`, or contains `source`. |

## Related Concepts

- [Calendars knowledge](../../knowledge/msm/calendars/index.md)
- [ADR 0055: Calendars As Rules And Exceptions](../../ADR/0055-calendars-as-rules-and-exceptions.md)
