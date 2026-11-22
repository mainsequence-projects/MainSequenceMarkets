# Calendars

Calendars are core `msm` reference data. A calendar says, for a local date,
whether a market is open and when each of its sessions opens and closes. Other
packages reference a calendar by `CalendarTable.uid`.

A calendar is stored as its regular week plus the dates that differ from it.
Dates and sessions are computed from those rows when they are read; no row is
stored per date. The design is
[ADR 0055](../../../ADR/0055-calendars-as-rules-and-exceptions.md).

The stored rows are the source of truth, not `pandas_market_calendars`,
QuantLib, or any vendor helper. Such a library is an adapter: it writes rules
and exceptions into the calendar tables.

## Scope

Calendars answer these questions:

- whether a local date is a business day, a holiday, a weekend, or an early
  close;
- which sessions run on a local date, and their open and close as UTC instants;
- from which date to which date those answers are complete.

They do not own instrument payment schedules, portfolio construction, or
pricing runtime behavior. Those packages may reference a calendar but should not
redefine the core calendar row model.

## Table Relationships

```text
                +-----------------------------+
                | CalendarTable               |
                |-----------------------------|
                | uid PK                      |
                | unique_identifier unique    |
                | display_name                |
                | calendar_type               |
                | timezone                    |
                | source / source_identifier  |
                | valid_from / valid_to       |
                +--------------+--------------+
                               |
                               | 1 to many, cascade on calendar delete
               +---------------+----------------+
               v                                v
+-----------------------------+  +-----------------------------+
| CalendarSessionRuleTable    |  | CalendarExceptionTable      |
|-----------------------------|  |-----------------------------|
| uid PK                      |  | uid PK                      |
| calendar_uid FK             |  | calendar_uid FK             |
| session_label               |  | local_date                  |
| effective_from / _to        |  | session_label               |
| weekdays                    |  | exception_type              |
| opens_at_local              |  | opens_at_local              |
| closes_at_local             |  | closes_at_local             |
| open_day_offset             |  | name                        |
| close_day_offset            |  | source                      |
| is_primary                  |  | metadata_json               |
| unique(calendar_uid, label, |  | unique(calendar_uid, date,  |
|        effective_from)      |  |        label, type, source) |
+-----------------------------+  +-----------------------------+
```

- `CalendarTable` is the calendar's identity, its timezone, and the range its
  rows are complete for.
- `CalendarSessionRuleTable` is the regular week of one session, from a date on.
- `CalendarExceptionTable` is one dated departure from the rules.

### Session rules

| Field | Meaning |
|---|---|
| `session_label` | The session the rule describes. `regular` by default |
| `effective_from` | First local date the rule applies to |
| `effective_to` | Last local date, or null while the rule is current |
| `weekdays` | Seven characters of `0` and `1`, Monday first. `1111100` is Monday to Friday |
| `opens_at_local`, `closes_at_local` | Wall-clock times as `HH:MM:SS` text, in the calendar's timezone. Null for a date-only calendar such as a settlement calendar |
| `open_day_offset`, `close_day_offset` | Days from the session's local date, from `-1` to `1`. `-1` opens the evening before; `1` closes at the next midnight |
| `is_primary` | True when this is the calendar's main session for a date |

A change of regular hours, or of the weekend, is a new rule row with a later
`effective_from`. When several rules of one label cover a date, the one with the
latest `effective_from` is in force.

### Exceptions

| Field | Meaning |
|---|---|
| `local_date` | The calendar-local date |
| `session_label` | The session the row changes. Empty for the whole day |
| `exception_type` | `CLOSED`, `EARLY_CLOSE`, `LATE_OPEN` or `OPEN` |
| `opens_at_local`, `closes_at_local` | The times that replace the rule's. Null where the rule's time holds |
| `name` | For example `Thanksgiving`. Nullable |
| `source` | Who wrote the row: an adapter's name such as `pandas_market_calendars`, or `user` |

- `CLOSED`: no session on that date. It has no times.
- `EARLY_CLOSE`: the session runs and closes at `closes_at_local`.
- `LATE_OPEN`: the session runs and opens at `opens_at_local`.
- `OPEN`: a session runs on that date, with the rule's times unless the row
  gives others. It covers a trading Saturday, and it cancels a closure another
  source wrote.

### How a date is computed

NYSE from 2024-11-25 to 2024-12-31 is one rule and four exceptions:

| session_label | effective_from | weekdays | opens_at_local | closes_at_local |
|---|---|---|---|---|
| regular | 1990-01-01 | 1111100 | 09:30:00 | 16:00:00 |

| local_date | session_label | exception_type | closes_at_local | name |
|---|---|---|---|---|
| 2024-11-28 | | CLOSED | | Thanksgiving |
| 2024-11-29 | regular | EARLY_CLOSE | 13:00:00 | |
| 2024-12-24 | regular | EARLY_CLOSE | 13:00:00 | |
| 2024-12-25 | | CLOSED | | Christmas |

- 2024-11-27, a Wednesday with no exception: open 14:30 UTC, close 21:00 UTC.
- 2024-11-28: no session. It is a holiday, not a business day.
- 2024-11-29: open 14:30 UTC, close 18:00 UTC, an early close.
- 2024-11-30, a Saturday: no session, by the rule. It is a weekend.

Local times become UTC instants when the calendar is read, with the timezone
rules of the process that reads. A date is a business day when it has at least
one session.

## Primary Modules

- `msm.models.calendars`: SQLAlchemy MetaTable declarations.
- `msm.api.calendars`: public Pydantic row APIs and class-owned row helpers.
- `msm.repositories.calendars`: compiled SQL persistence helpers.
- `msm.services.calendars`: the computation, the `pandas_market_calendars`
  adapter, and the calendar write.

## User API

The row classes are `Calendar`, `CalendarSessionRule` and `CalendarException`:

```python
import msm

from msm.api.calendars import Calendar, CalendarException, CalendarSessionRule

msm.start_engine(models=["Calendar", "CalendarSessionRule", "CalendarException"])
```

Attach all three models. Creating a calendar from the library and reading its
dates or sessions need the three tables.

### Create a calendar from the library

```python
nyse = Calendar.create_from_pandas_calendar("NYSE")
custom = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")
crypto = Calendar.create_from_pandas_calendar("24/7", "CRYPTO_24_7", display_name="Crypto 24/7")
```

The first argument is the library's calendar. The second is the
`unique_identifier` of the stored one, and defaults to the library's name. The
call writes the `Calendar` row, its rules and its exceptions in one transaction.

| Argument | Default |
|---|---|
| `display_name` | The `unique_identifier` |
| `calendar_type` | `TRADING` |
| `timezone` | The library's timezone for that calendar |
| `session_label` | `regular` |
| `valid_from` | 1990-01-01 |
| `metadata_json` | The call adds `source_version`, the library version that wrote the calendar |

- No end date is passed. `valid_to` is the last date the library can answer
  for. That is 2200-12-31 for most calendars. A library calendar with no
  holidays, such as `24/7`, has no last date and `valid_to` is null.
- Nobody extends a calendar as time passes.
- `Calendar.source` is `pandas_market_calendars` and
  `Calendar.source_identifier` is the library's calendar.
- Every exception the call writes has `source="pandas_market_calendars"`.
- Without its `user` rows, the stored calendar reproduces the library's schedule
  for the range, session for session.
- `Calendar.create_from_pandas_calendar("24/7", "CRYPTO_24_7")` stores one rule
  and no exception: `weekdays=1111111`, open `00:00:00`, close `00:00:00` with
  `close_day_offset=1`.

One library calendar can back several stored calendars. `NYSE` and `CustomNYSE`
above are two calendars with their own rows. A calendar is found by its
`unique_identifier` only; `source_identifier` does not name one.

Calling it again on a stored calendar writes what the installed library knows
now:

- The library's own exceptions are replaced by difference. A row that did not
  change is not rewritten.
- Every `source="user"` exception is kept.
- The display name, calendar type and timezone stay as stored unless the call
  passes them.
- Without `valid_from`, the calendar starts at the earlier of its stored first
  date and 1990-01-01.
- A call that changes nothing writes nothing.

The call is refused with `ValueError` when:

- the stored calendar was written by hand or from another library calendar. Use
  another `unique_identifier`;
- `valid_from` is after the last date the library can answer for;
- the library calendar has a session whose open or close falls on another day
  than its regular week's.

### Correct a calendar by hand

A row written through `CalendarException.create`, `CalendarException.upsert` or
the routes has `source="user"`. A date that has any `user` row is computed from
its `user` rows alone. The library's rows for that date are ignored, not
deleted.

`CustomNYSE` starts as NYSE. Its desk trades a full day on 2024-12-24 and does
not trade on 2024-12-31:

```python
import datetime as dt

custom = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")

full_day = CalendarException.create(
    calendar_uid=custom.uid,
    local_date=dt.date(2024, 12, 24),
    exception_type="OPEN",
)
desk_closed = CalendarException.create(
    calendar_uid=custom.uid,
    local_date=dt.date(2024, 12, 31),
    exception_type="CLOSED",
    name="Desk closed",
)
```

Computed for `CustomNYSE`:

- 2024-12-24: open 14:30 UTC, close 21:00 UTC. The date has a `user` row, so the
  library's early close is ignored.
- 2024-12-31: no session.
- Every other date: as NYSE.

A later `Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")` leaves both
rows in place.

- To cancel a closure the library has, write an `OPEN` row for that date.
- To restore the library's answer, delete the row:
  `CalendarException.delete(full_day.uid)`.
- An `EARLY_CLOSE` row sets `closes_at_local` only, and a `LATE_OPEN` row sets
  `opens_at_local` only.
- A row with an empty `session_label` applies to every session of the date. Set
  `session_label` to change one session.
- A `CLOSED` row cannot stand next to another `user` row for the same date and
  session. The write is refused with `ValueError`.
- A `user` row stays until someone deletes it, also after the library learns the
  same fact.

### Read dates and sessions

```python
sessions = Calendar.sessions(custom.uid, dt.date(2024, 11, 25), dt.date(2024, 12, 31))
dates = Calendar.dates(custom.uid, dt.date(2024, 11, 25), dt.date(2024, 12, 31))
is_open = Calendar.is_business_day(custom.uid, dt.date(2024, 12, 31))
```

- `Calendar.sessions(calendar_uid, start_date, end_date, session_label=None)`
  returns one `ComputedCalendarSession` per session: `local_date`,
  `session_label`, `opens_at` and `closes_at` in UTC, `timezone`, `is_primary`,
  `is_early_close` and `is_late_open`.
- `Calendar.dates(calendar_uid, start_date, end_date)` returns one
  `ComputedCalendarDate` per local date, weekends included: `local_date`,
  `is_business_day`, `is_holiday`, `is_weekend`, `is_early_close` and
  `holiday_name`.
- `Calendar.is_business_day(calendar_uid, local_date)` returns whether the date
  has at least one session.

Both bounds are inclusive. A computed date or session is not a row and has no
`uid`.

A read outside the calendar's `valid_from` to `valid_to` raises
`msm.services.calendars.CalendarRangeError`, a `ValueError`. The message names
the calendar and its range:

```text
Calendar 'NYSE' is complete from 1990-01-01 to 2200-12-31; 2200-12-01 to 2201-01-31 is outside that range.
```

A null bound is not checked. Without this check, every weekday past the last
known holiday would read as a business day. An unknown `calendar_uid` raises
`LookupError`.

One read loads the calendar's rules and the exceptions of the requested window.
The same three calls work under the remote backend; see
[Client](../client/index.md). The Markets API serves the same computation on
its [calendar routes](../../../fast_api/v1/calendars.md).

### Write your own calendar

A calendar that no library has is a `Calendar` row plus at least one rule:

```python
desk = Calendar.create(
    unique_identifier="DESK",
    display_name="Desk hours",
    calendar_type="CUSTOM",
    timezone="Europe/London",
)
CalendarSessionRule.create(
    calendar_uid=desk.uid,
    effective_from=dt.date(2026, 1, 1),
    weekdays="1111100",
    opens_at_local="09:00",
    closes_at_local="17:30",
)
```

- Times are accepted as `HH:MM`, `HH:MM:SS` or `datetime.time`, and stored as
  `HH:MM:SS`.
- Leave `valid_from` and `valid_to` null on a calendar with nothing to project.
  Set them when the calendar's exceptions are complete only for a range; reads
  outside it are then refused.
- A calendar without rules has no business days.
- A date before the first rule's `effective_from` has no session.
- A holiday is a `CalendarException` with `exception_type="CLOSED"`.
- `CalendarSessionRule.upsert` matches on `calendar_uid`, `session_label` and
  `effective_from`. `CalendarException.upsert` matches on `calendar_uid`,
  `local_date`, `session_label` and `exception_type`.
- Deleting a calendar deletes its rules and exceptions. A calendar that is the
  trading calendar of an asset, or the calendar of a portfolio, is not deleted:
  the delete is refused with the number of each. Move them to another calendar
  first.

On a calendar an adapter wrote, the adapter owns the rules: the next write from
the library replaces them. Correct such a calendar with exceptions.

## Writing A Calendar Again After A Library Upgrade

A stored calendar holds what the library knew when it was written. A newer
library version can know a new closure, a new holiday or new regular hours.
Taking them is a decision a person makes, so nothing does it automatically: not
the Markets API when it starts, not a release, and not a schedule.

`jobs/resync_calendars.py` is the admin job for it:

```text
resync_calendars.py NYSE CustomNYSE     write these calendars again
resync_calendars.py                     every calendar the adapter wrote
resync_calendars.py --dry-run [...]     print the same report and write nothing
resync_calendars.py --valid-from DATE   first date to write
resync_calendars.py --list-all          list every exception added and removed
```

- For each calendar it does what `create_from_pandas_calendar` does on a stored
  calendar. Every `user` exception is kept.
- Per calendar it prints the library version before and after, the range,
  whether the session rules changed, and the exceptions added and removed. It
  lists 20 exceptions on each side unless `--list-all` is given.
- Without `--valid-from`, a calendar keeps its first date, or moves back to
  1990-01-01 when it starts later.
- A named calendar that does not exist, or that the adapter did not write,
  fails. The job exits with 1 when a calendar fails; the calendars before it are
  written and the ones after it are still tried.

Run it with `--dry-run` first. Until the job runs, a calendar stays as the
library version recorded in its `metadata_json["source_version"]` left it. See
[Calendar re-sync Job](../../../releasing.md#calendar-re-sync-job) for running
it on a deployment.

## Limits

- A lunch break is not modelled. A session from the library runs from the
  library's open to its close.
- A rule has one open and one close for all its weekdays. A library calendar
  whose hours differ by weekday is stored with the most frequent hours as the
  rule and the odd weekday as an exception on each such date.
- The library names its holiday rules, not its schedule. An ad-hoc closure is a
  `CLOSED` exception without a `name`.
- Price interpolation and the `intraday_trend` signal read stored calendars too
  ([ADR 0056](../../../ADR/0056-asset-trading-calendar-link.md)). An asset is
  linked to its trading calendar with `AssetCalendar`, so a correction made by
  hand moves a portfolio's rebalance dates and the bars of its assets together.
  See [Trading Calendar](../assets/asset_indexed_updaters.md#trading-calendar).

## Portfolio And Pricing Boundaries

`msm_portfolios` may reference `CalendarTable.uid` through
`PortfolioTable.calendar_uid`. Portfolio rows do not duplicate calendar names.
Calendar-relative rebalancing reads a stored calendar through
`Calendar.sessions`; see [Portfolios](../../msm_portfolios/portfolios/index.md).

`msm_pricing` may add future QuantLib adapters and instrument schedule tables.
Those schedule tables should reference `CalendarTable.uid` but remain outside
core `msm`.

## Example

See `examples/msm/calendars/calendar_rules_and_exceptions_workflow.py` for the
core calendar workflow and
`examples/msm_portfolios/portfolio_equal_weights_run.py` for a portfolio that
creates or reuses a `CRYPTO_24_7` calendar before writing the
`Portfolio.calendar_uid` relationship.

## Building On Calendars In Another Project

A project that installs ms-markets gets its calendar guidance with
`msm copy-msm-skills`: the packaged skill
`.agents/skills/ms_markets/calendars/calendar_workflow/SKILL.md` has the rules
for getting, reading and correcting a calendar, the Markets API routes, and a
table for moving code off the per-date rows.

In short:

- Use the remote backend ([Client](../client/index.md)). The application needs
  no role on `mainsequence.markets`.
- Look a calendar up by `unique_identifier` and create it only when the lookup
  finds none. Do not call `create_from_pandas_calendar` again to extend it.
- Read with `Calendar.sessions`, `Calendar.dates` and
  `Calendar.is_business_day`. A window outside the range raises `ValueError`
  under the remote backend; let it fail.
- Correct with `CalendarException` rows, on a calendar of your own name when the
  correction is not true for everyone.
- Taking a newer library version is the Markets deployment's re-sync Job.

## Related Concepts

- [Models](../models/index.md)
- [Services](../services/index.md)
- [msm_portfolios](../../msm_portfolios/index.md)
- [msm_pricing](../../msm_pricing/index.md)
