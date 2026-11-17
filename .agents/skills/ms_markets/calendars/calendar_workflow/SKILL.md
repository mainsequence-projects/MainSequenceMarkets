---
name: mainsequence-markets-calendar-workflow
description: Use this skill when a project needs a market, settlement, or custom calendar from ms-markets, or when creating, reading, correcting, extending, or reviewing calendar code. Covers Calendar, CalendarSessionRule, CalendarException, Calendar.create_from_pandas_calendar, Calendar.sessions, Calendar.dates, Calendar.is_business_day, CalendarRangeError, user corrections, the calendar re-sync Job, the calendar routes of the Markets API, and moving code off the removed CalendarDate, CalendarSession and CalendarEvent rows.
---

# Main Sequence Markets Calendar Workflow

Use this skill for calendars in `msm`: the stored calendar model, how an
application gets and reads a calendar, how a calendar is corrected by hand, and
how a calendar takes what a newer library version knows.

The design is ADR 0055, `docs/ADR/0055-calendars-as-rules-and-exceptions.md`.

## Route First

Use these adjacent skills when the task crosses their boundary:

- Portfolio calendars, `PortfolioCalendarEvents`, `CalendarEventSignal`:
  `.agents/skills/ms_markets/portfolios/portfolio_workflow/SKILL.md`
- Asset-indexed updaters, price bars included:
  `.agents/skills/ms_markets/assets/asset_indexed_updaters/SKILL.md`
- Roles on `mainsequence.markets` and migration wiring:
  `.agents/skills/ms_markets/platform/metatable_migrations/SKILL.md`
- Bootstrap and runtime attachment:
  `.agents/skills/ms_markets/platform/bootstrap_registration/SKILL.md`
- Generic MetaTable behavior:
  `.agents/skills/metatables/metatables-meta-tables/SKILL.md`

## Read First

Before changing calendar code, inspect:

1. `docs/knowledge/msm/calendars/index.md`
2. `docs/ADR/0055-calendars-as-rules-and-exceptions.md`
3. `src/msm/api/calendars/core.py`, `rules.py`, `exceptions.py`, `computed.py`
4. `src/msm/services/calendars/computation.py`
5. `src/msm/services/calendars/pandas_market.py` and `sync.py`
6. `docs/fast_api/v1/calendars.md` for the HTTP routes
7. `docs/knowledge/msm/client/index.md` for the remote backend
8. `examples/msm/calendars/calendar_rules_and_exceptions_workflow.py`

In a project that only installs ms-markets, read the same files from the
installed package and its documentation site.

## The Model

A calendar is three kinds of rows. Nothing is stored per date.

```text
Calendar              identity, timezone, source, valid_from / valid_to
CalendarSessionRule   the regular week of one session, from a date on
CalendarException     one dated departure from the rules
```

- A rule holds `weekdays` (seven characters, Monday first, `1111100`), local
  `opens_at_local` and `closes_at_local` as `HH:MM:SS` text in the calendar's
  timezone, and `effective_from` / `effective_to`.
- An exception holds `local_date`, `session_label` (empty for the whole day),
  `exception_type` and `source`.
- `exception_type` is `CLOSED`, `EARLY_CLOSE`, `LATE_OPEN` or `OPEN`.
- `source` is `pandas_market_calendars` for a row the library adapter wrote and
  `user` for a row a person or an application wrote.
- Dates and sessions are computed from these rows when they are read. Local
  times become UTC instants at that moment.

NYSE from 1990 to 2200 is 1 rule and about 2,500 exceptions.

## Rules

1. A calendar is found by its `unique_identifier`. `source_identifier` is the
   library's name and does not name a stored calendar: several stored calendars
   can come from one library calendar.
2. A calendar from the library is written once. Do not call
   `create_from_pandas_calendar` to move a range forward. It takes no end date,
   and nothing has to be extended as time passes.
3. Read dates and sessions with `Calendar.sessions`, `Calendar.dates` and
   `Calendar.is_business_day`. Do not compute them from the rules yourself and
   do not ask `pandas_market_calendars` for a stored calendar's answer.
4. A read outside `valid_from`..`valid_to` is an error, not an empty result.
   Do not catch it to continue with no sessions.
5. Correct a calendar with `CalendarException` rows. They get `source="user"`,
   win for their date, and survive every later write from the library.
6. An application never chooses an exception's `source` and never edits or
   deletes a row another source wrote.
7. Taking a newer library version's answers is the re-sync Job of the Markets
   deployment, run by a person. An application does not trigger it and the
   Markets API never does it by itself.
8. Do not copy a calendar's dates or sessions into a table of your own. Read
   them when they are needed.

## Runtime Attachment

Code that owns Markets tables, such as the Markets deployment and its Jobs,
attaches the three models:

```python
import msm

msm.start_engine(models=["Calendar", "CalendarSessionRule", "CalendarException"])
```

Every other application uses the remote backend and attaches nothing. It holds
no role on `mainsequence.markets`:

```python
from msm.api.remote import use_remote_backend
from msm.client import LazyRemoteBackend

use_remote_backend(LazyRemoteBackend())
```

The calls below are the same under both backends.

## Get A Calendar

Look the calendar up by its `unique_identifier`. Create it only when it does not
exist:

```python
from msm.api.calendars import Calendar


def trading_calendar(unique_identifier: str, library_calendar: str) -> Calendar:
    calendar = Calendar.get_by_unique_identifier(unique_identifier)
    if calendar is None:
        calendar = Calendar.create_from_pandas_calendar(library_calendar, unique_identifier)
    return calendar


nyse = trading_calendar("NYSE", "NYSE")
desk = trading_calendar("CustomNYSE", "NYSE")
crypto = trading_calendar("CRYPTO_24_7", "24/7")
```

- The first argument of `create_from_pandas_calendar` is the library's
  calendar. The second is the stored name and defaults to the library's.
- It writes the `Calendar` row, the rules and the exceptions in one transaction,
  from 1990-01-01 to the last date the library can answer for. That is
  2200-12-31 for most calendars. A calendar with no holidays, such as `24/7`,
  has no last date.
- Optional keyword arguments: `display_name`, `calendar_type`, `timezone`,
  `session_label`, `valid_from`, `metadata_json`. There is no `valid_to` and no
  `materialize`.
- It is refused with `ValueError` when the stored calendar was written by hand
  or from another library calendar. Use another `unique_identifier`.

Reference the calendar from your own rows by `Calendar.uid`, as
`Portfolio.calendar_uid` does. Serialized configuration keeps the
`unique_identifier`.

## Read Dates And Sessions

```python
import datetime as dt

sessions = Calendar.sessions(nyse.uid, dt.date(2024, 11, 25), dt.date(2024, 12, 31))
dates = Calendar.dates(nyse.uid, dt.date(2024, 11, 25), dt.date(2024, 12, 31))
is_open = Calendar.is_business_day(nyse.uid, dt.date(2024, 11, 28))
```

- Both bounds are inclusive. One call covers any window; do not page by year.
- A session has `local_date`, `session_label`, `opens_at` and `closes_at` in
  UTC, `timezone`, `is_primary`, `is_early_close` and `is_late_open`.
- A date has `local_date`, `is_business_day`, `is_holiday`, `is_weekend`,
  `is_early_close` and `holiday_name`.
- A business day is a date with at least one session. A weekend is a weekday no
  rule runs on. A holiday is a date a rule runs on that has no session.
- A computed date or session is not a row. It has no `uid`.

A window outside the calendar's range raises
`msm.services.calendars.CalendarRangeError` under the runtime backend. It is a
`ValueError`, and under the remote backend it arrives as a plain `ValueError`.
Catch `ValueError` when the code has to run under both. An unknown calendar
raises `LookupError`.

```text
Calendar 'NYSE' is complete from 1990-01-01 to 2200-12-31; 2200-12-01 to 2201-01-31 is outside that range.
```

Start a first read at the calendar's `valid_from` when your own start is
earlier. `PortfolioCalendarEvents` does this.

## Correct A Calendar

```python
from msm.api.calendars import CalendarException

full_day = CalendarException.create(
    calendar_uid=desk.uid,
    local_date=dt.date(2024, 12, 24),
    exception_type="OPEN",
)
CalendarException.create(
    calendar_uid=desk.uid,
    local_date=dt.date(2024, 12, 31),
    exception_type="CLOSED",
    name="Desk closed",
)
```

- A date that has any `user` row is computed from its `user` rows alone. The
  library's rows for that date are ignored, not deleted.
- `OPEN` runs a session with the rule's times unless the row gives others. It
  cancels a closure the library has, and it opens a date the rule has no session
  on.
- `EARLY_CLOSE` sets `closes_at_local` only. `LATE_OPEN` sets `opens_at_local`
  only. `CLOSED` has no times.
- An empty `session_label` applies to every session of the date.
- A `CLOSED` row next to another `user` row for the same date and session is
  refused with `ValueError`.
- `CalendarException.delete(full_day.uid)` restores the library's answer.
- A `user` row stays until someone deletes it.

Correct a shared calendar only when the correction is true for everyone who
uses it. For a desk's own hours, create a calendar under another name from the
same library calendar and correct that one.

## Write A Calendar No Library Has

```python
from msm.api.calendars import CalendarSessionRule

settlement = Calendar.create(
    unique_identifier="DESK_SETTLEMENT",
    display_name="Desk settlement days",
    calendar_type="SETTLEMENT",
    timezone="Europe/London",
)
CalendarSessionRule.create(
    calendar_uid=settlement.uid,
    effective_from=dt.date(2026, 1, 1),
    weekdays="1111100",
)
```

- A rule without times is a date-only session: business days and no hours.
- A calendar without rules has no business days.
- A change of hours or of the weekend is a new rule with a later
  `effective_from`. Set `effective_to` on the rule it replaces.
- Leave `valid_from` and `valid_to` null unless the exceptions are complete only
  for a range.
- A holiday is a `CalendarException` with `exception_type="CLOSED"`.

## Take A Newer Library Version

A stored calendar holds what the library knew when it was written. A release
that upgrades `pandas-market-calendars` changes no stored calendar.

`jobs/resync_calendars.py` in the Markets deployment writes calendars again. A
person runs it:

```text
resync_calendars.py --dry-run           report what would change, write nothing
resync_calendars.py                     every calendar the adapter wrote
resync_calendars.py NYSE CustomNYSE     these calendars
```

- It keeps every `user` exception.
- It prints, per calendar, the library version before and after, the range, and
  the exceptions added and removed.
- Read the dry run first. A changed session moves the rebalance times of the
  portfolios on that calendar.
- Its workload User needs `data_writer` on `mainsequence.markets`.

`docs/releasing.md`, "Calendar re-sync Job", has the commands for a deployment.

## Markets API Routes

A client that does not use the Python row classes calls the routes:

| Route | What it does |
|---|---|
| `GET /api/v1/calendar/?unique_identifier=NYSE` | find a calendar |
| `GET /api/v1/calendar/{uid}/sessions/?start_date=&end_date=` | computed sessions |
| `GET /api/v1/calendar/{uid}/dates/?start_date=&end_date=` | computed dates |
| `/api/v1/calendar/{uid}/rules/` | list, create, bulk-upsert, get, update, delete |
| `/api/v1/calendar/{uid}/exceptions/` | list, create, bulk-upsert, get, update, delete |
| `POST /api/v1/rows/calendar/create_from_pandas_calendar/` | create from the library |

- `start_date` and `end_date` are required on the computed routes. A request
  without them answers `422`.
- A window outside the calendar's range answers `400` with the range in the
  message. An unknown calendar answers `404`.
- An exception created through the routes has `source="user"`. The body does not
  accept `source`.

## Moving Code Off The Per-Date Rows

`CalendarDate`, `CalendarSession` and `CalendarEvent` no longer exist.

| Code written for the per-date rows | What it becomes |
|---|---|
| `CalendarSession.filter(calendar_uid=..., local_date__gte=..., local_date__lte=...)` | `Calendar.sessions(calendar_uid, start, end)` |
| `CalendarDate.filter(...)` | `Calendar.dates(calendar_uid, start, end)` |
| a loop of yearly windows to stay under 1,000 rows | one call |
| `create_from_pandas_calendar(..., valid_from=..., valid_to=...)` | `create_from_pandas_calendar(library_name, stored_name)` |
| calling it on a schedule to move `valid_to` forward | nothing; delete the call |
| `materialize=False` to write only the header | `Calendar.create(...)` plus `CalendarSessionRule` rows |
| `models=["Calendar", "CalendarDate", "CalendarSession"]` | `models=["Calendar", "CalendarSessionRule", "CalendarException"]` |
| looking a calendar up by `source_identifier` | `Calendar.get_by_unique_identifier(...)` |
| `build_always_open_calendar_materialization(...)` | `Calendar.create_from_pandas_calendar("24/7", "CRYPTO_24_7")` |
| writing a holiday as a `CalendarDate` row | a `CalendarException` with `exception_type="CLOSED"` |
| `GET /calendar/{uid}/dates/` without dates | pass `start_date` and `end_date` |
| the `/calendar/{uid}/events/` routes | removed; nothing replaces them |

## Assets And Price Bars

A stored calendar also decides which price bars an asset has (ADR 0056). An
asset is linked to its trading calendar with
`AssetCalendar.upsert(asset_uid=..., calendar_uid=...)`.

- Price interpolation requires the link. An asset without one fails the price
  update; there is no default calendar.
- A correction to a calendar moves the bars of every asset linked to it and the
  rebalance dates of every portfolio on it. For different answers, make two
  calendars from the same library calendar.
- A calendar cannot be deleted while an asset is linked to it.

## Limits

- A lunch break is not stored. A session from the library runs from the
  library's open to its close.
- A rule has one open and one close for all its weekdays. A market whose hours
  differ by weekday stores the odd weekday as an exception on each such date.
- An ad-hoc closure from the library has no `name`.
- A few library calendars end before 2200 because the library cannot compute
  their holidays. `valid_to` says where. A read past it is refused.

## Do Not Reintroduce

- A table with one row per date or per session.
- A `valid_to` that a caller has to keep moving.
- A fallback from a stored calendar to `pandas_market_calendars` when a lookup
  fails or a window is out of range.
- A lookup by `source_identifier`.
- An automatic rewrite of stored calendars on API start, on a release, or on a
  schedule.
- Aliases for `CalendarDate`, `CalendarSession`, `CalendarEvent` or the removed
  materialization helpers.

## Validation

In ms-markets:

```bash
.venv/bin/pytest tests/msm/services/calendars tests/msm/api/calendars tests/msm/models/calendars -q
.venv/bin/pytest tests/msm/maintenance/test_calendar_rules_migration.py tests/msm/maintenance/test_resync_calendars_job.py -q
.venv/bin/pytest tests/msm/fastapi/v1/test_calendars.py tests/msm_portfolios/services/test_calendars.py -q
```

In a project that uses ms-markets, check that:

- no code names `CalendarDate`, `CalendarSession`, `CalendarEvent`, `valid_to=`
  or `materialize=` in a calendar call;
- every calendar is looked up by `unique_identifier`;
- a calendar is created only when the lookup finds none;
- code that reads a window handles `ValueError` for a window outside the range
  by failing, not by continuing with no sessions.
