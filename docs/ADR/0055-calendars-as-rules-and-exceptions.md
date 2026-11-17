# 0055. Calendars As Rules And Exceptions

## Status

Accepted (2026-11-17). The decisions marked (owner) were made by the owner on 2026-11-17.
Implemented on `development` for 4.0.0; see "Decisions Taken During Implementation" and
"Implementation Notes".

- It supersedes the storage model of
  [ADR 0028](0028-core-calendar-reference-data.md): `CalendarDateTable`,
  `CalendarSessionTable` and `CalendarEventTable` are removed. ADR 0028's other decisions
  stand: calendars are core
  `msm` reference data, a portfolio references a calendar by `calendar_uid`, and source
  libraries are adapters.
- It amends [FastAPI v1 ADR 0001](fast_api/v1/0001-calendar-crud-route.md): the date and
  session routes change (see "5. Routes").
- It answers the calendar part of
  [issue 83](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/83). What
  issue 83 still needs is listed under "What Issue 83 Still Needs".

## Context

### What is stored

ADR 0028 stores a calendar as one `CalendarDate` row per calendar day, weekends included, and
one `CalendarSession` row per trading day. Its argument was that a 100-year calendar is only
about 36,500 rows.

Almost none of those rows carry information. Measured with
`build_pandas_market_calendar_materialization` (pandas-market-calendars 5.4.0):

| Calendar and range | Date rows | Session rows | Closures | Sessions off regular hours |
|---|---|---|---|---|
| NYSE, 2017-12-02 to 2027-11-18 | 3,639 | 2,503 | 96 | 20 |
| NYSE, 1990-01-01 to 2050-12-31 | 22,280 | 15,343 | 572 | 142 |
| LSE, 2017-12-02 to 2027-11-18 | 3,639 | 2,515 | 84 | 20 |
| A 24/7 calendar, any range | 1 per day | 1 per day | 0 | 0 |

The first NYSE range is 6,142 rows for 116 facts. Every other row restates the rule "Monday to
Friday, 09:30 to 16:00 New York time". Every row also repeats in `metadata_json` the source
that is already on the `Calendar` row.

### What goes wrong

- **The write is large.** Issue 83: a ten-year range is one 3.3 MB statement, which MetaTables
  refuses.
- **The header and the rows are written apart.** The `Calendar` row is upserted first. When the
  rows fail, the calendar claims a range its rows do not cover.
- **The range must be extended forever.** A calendar that has to reach a year ahead needs a
  write as time passes, and each write sends the whole range again.
- **The header drifts from the rows.** Observed on a deployed Markets API on 2026-11-17: one
  calendar's `valid_to` is 69 days past its last row, and another's `valid_from`..`valid_to`
  lies inside the range its rows cover and ends in the past. A later upsert with a different
  range changes the header and leaves the earlier rows.
- **Nothing checks the range on read.** No code compares a requested date with
  `valid_from`/`valid_to`. When the session rows run out, `PersistedCalendarSchedule` returns
  fewer rows and `PortfolioCalendarEvents` publishes no event, without an error.
- **Reads are windowed.** A governed read returns at most 1,000 rows, so
  `PersistedCalendarSchedule` reads two years at a time. A first run from 2018 is five reads.
- **`CalendarDate` has no reader.** Only its CRUD routes list it. `holiday_name` is never
  written. `CalendarSession` is read by `PortfolioCalendarEvents` and by the portfolio
  timestamp repair.
- **Future sessions are stored as UTC instants.** They fix the timezone rules known on the day
  of the write. A change of daylight-saving law, as in Mexico in 2022, leaves the stored
  instants wrong until they are written again.

### How other systems store a calendar

The systems of record checked for this ADR keep a rule and its exceptions:

- QuantLib: a weekend rule and a holiday rule in code, plus `addedHolidays` and
  `removedHolidays` date sets
  ([calendar.hpp](https://github.com/lballabio/QuantLib/blob/master/ql/time/calendar.hpp)).
- pandas-market-calendars and exchange_calendars: a week mask, regular open and close times
  with effective dates, holiday rules, ad-hoc holidays, and special opens and closes.
  `schedule(start, end)` is computed on request
  ([market_calendar.py](https://github.com/rsheftel/pandas_market_calendars/blob/master/pandas_market_calendars/market_calendar.py)).
- OpenGamma Strata: `ImmutableHolidayCalendar` "stores all dates that are holidays, plus a
  list of weekend days"
  ([source](https://github.com/OpenGamma/Strata/blob/main/modules/basics/src/main/java/com/opengamma/strata/basics/date/ImmutableHolidayCalendar.java)).
- SAP: a factory calendar is a set of working weekdays, a holiday calendar and special rules.

Tables with one row per date exist as derived output: the in-memory schedule of
exchange_calendars, vendor trading-hours files, and the date dimension of a data warehouse,
which serves reporting joins. In each case the table is rebuilt from the rule and its
exceptions.

## Decision

### 1. A calendar is session rules plus exceptions

Two tables replace `CalendarDate` and `CalendarSession`.

`CalendarSessionRule` is the regular week of one session, from a date on:

| Column | Meaning |
|---|---|
| `calendar_uid` | FK to `Calendar.uid`, `ON DELETE CASCADE` |
| `session_label` | `regular` by default |
| `effective_from` | First local date the rule applies to |
| `effective_to` | Last local date, or null while the rule is current |
| `weekdays` | Seven characters, Monday first: `1111100` |
| `opens_at_local`, `closes_at_local` | Wall-clock times in the calendar's timezone. Null for a date-only calendar such as a settlement calendar |
| `open_day_offset`, `close_day_offset` | Days from the session's local date. `-1` opens the evening before; `1` closes at the next midnight |
| `is_primary` | As on `CalendarSession` today |

It is unique on `(calendar_uid, session_label, effective_from)`. A change of regular hours, or
of the weekend, is a new rule row. NYSE needs one row from 1985.

`CalendarException` is one dated departure from the rules:

| Column | Meaning |
|---|---|
| `calendar_uid` | FK to `Calendar.uid`, `ON DELETE CASCADE` |
| `local_date` | The calendar-local date |
| `session_label` | The session it changes. Empty for the whole day |
| `exception_type` | `CLOSED`, `EARLY_CLOSE`, `LATE_OPEN` or `OPEN` |
| `opens_at_local`, `closes_at_local` | The times that replace the rule's. Null where the rule's time holds |
| `name` | For example `Thanksgiving`. Nullable |
| `source` | Who wrote the row: an adapter's name such as `pandas_market_calendars`, or `user` |
| `metadata_json` | Nullable. Not a copy of the calendar's source |

It is unique on `(calendar_uid, local_date, session_label, exception_type, source)`.

- `CLOSED`: no session on that date.
- `EARLY_CLOSE`, `LATE_OPEN`: the session runs with one time replaced.
- `OPEN`: a session runs on that date, with the rule's times unless the row gives others. It
  covers a trading Saturday, and it cancels a closure another source wrote.

A `CLOSED` row and another row of the same source for the same date and session are refused.

### 1a. A user's rows win, and an adapter replaces only its own (owner)

- A row written through the row API or the routes has `source="user"`. A row an adapter writes
  has the adapter's name.
- A date that has any `user` row is computed from its `user` rows alone. The adapter's rows
  for that date are ignored, not deleted.
- An adapter write deletes and writes only rows of its own `source`.

So a correction made by hand survives the next adapter write. To cancel a closure the library
has, a user writes an `OPEN` row for that date. To restore the library's answer, the user
deletes their row.

The cost: a `user` row stays until someone deletes it, also after the library learns the same
fact. The rules have no `source`: on a calendar an adapter wrote, the adapter owns them.

`Calendar` keeps its columns.

`CalendarEvent` is removed (owner). It was meant for dated facts that do not decide whether a
market is open, such as an expiry or a roll date. Nothing in the library writes it or reads
it, and its `HOLIDAY` and `EARLY_CLOSE` types are exceptions now. A later use gets a table
designed for it.

### 2. The range is the source's horizon, and nobody extends it (owner)

The owner's requirement: a user must not have to keep moving a calendar's range forward.

Today the range moves because rows are expensive, so a caller writes about a year ahead. With
exceptions only, the adapter writes as far as its library projects, once:

| Calendar, 1990-01-01 to 2200-12-31 | Rows today | Exceptions |
|---|---|---|
| NYSE | 130,063 | 2,517 |
| XMEX | 130,179 | 1,935 |

- `valid_to` is the last date the source can answer for. The adapter sets it; the caller does
  not pass it. For a pandas-market-calendars calendar it is 2200-12-31, where the library's
  holiday rules end. A source that knows less sets less.
- `valid_from` is optional in the adapter call and defaults to 1990-01-01 (owner). No updater
  in this repository starts earlier on a calendar: the portfolio updaters start on
  2018-01-01 and price interpolation on 2017-07-20. A later default would fail their first
  run. An earlier one adds rows where a library's regular week changed, such as NYSE's
  Saturday sessions before 1952. A caller that needs earlier dates passes `valid_from`.
- Both are null on a calendar with nothing to project, such as a 24/7 calendar or a user's
  own. A null bound is not checked.
- A read outside a set bound is refused with an error that names the calendar and its range.

This is how the source libraries behave. pandas-market-calendars has no range: it answers any
date, and past 2200 it reads every weekday as open (checked on 5.4.0: Thanksgiving 2250 is a
trading day). exchange_calendars has no bound for most calendars, and sets one where holidays
cannot be computed: its Saudi calendar stops at 2029-12-31, and a later date is an error. The
check here is that bound.

What changes with time is new facts: an ad-hoc closure, or new regular hours. They arrive
with a new library version, and the re-sync job writes them when a user runs it (see "4").

### 3. Dates and sessions are computed

Core `msm` gets one pure function set in `msm.services.calendars`. It takes a calendar's rules
and exceptions and returns, for a date range:

- whether each date is a business day: a date with at least one session;
- the sessions of each date, with `opens_at` and `closes_at` in UTC.

Local times become UTC instants at this point, with the timezone rules of the process that
asks. Nothing in this path imports a source library.

A read loads the rules, which are a few rows, and the exceptions of the requested range, which
are about 12 rows a year for an exchange. One read covers about 80 years inside the 1,000-row
limit. Longer ranges page.

The row API offers this as `Calendar.sessions(start, end)`, `Calendar.dates(start, end)` and
`Calendar.is_business_day(date)`. They work under the runtime backend and the remote backend,
because they only filter the two tables.

### 4. Adapters write rules and exceptions

`Calendar.create_from_pandas_calendar` keeps its name. It writes the `Calendar` row, the rules
and the exceptions in one statement list, so the header and the rows change together (as
[ADR 0051](0051-account-registration-in-one-transaction.md) does for accounts).

- The adapter reads the library's week mask and regular times into rules.
- It then compares the library's schedule for the range with what the rules alone produce.
  Every date that differs becomes an exception with `source="pandas_market_calendars"`.
- So the stored calendar, without its `user` rows, reproduces the library's schedule for the
  range, session for session. This is the adapter's test.
- A later call replaces the adapter's own rows: those the library no longer produces are
  deleted. `user` rows are not touched.
- The `Calendar` row records the library version that wrote it.

The `materialize` argument is removed. A calendar without rules has no business days.

#### A library calendar under another name (owner)

The first two arguments are the library's calendar and the name of the stored one:

```python
Calendar.create_from_pandas_calendar("NYSE")                # stored as NYSE
Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")  # stored as CustomNYSE
```

- `unique_identifier` defaults to `source_identifier`, and `display_name` to
  `unique_identifier`. No range is passed.
- Several stored calendars can come from one library calendar. Each has its own `user` rows.
- `CustomNYSE` is NYSE as the library has it, plus what its users changed. A later call
  refreshes the library's part and keeps the users' part.

#### Writing a calendar again is a job the user runs (owner)

A stored calendar holds what the library knew when it was written. A newer library version
can know a new closure, a new holiday or new regular hours. Taking them is the user's
decision, so nothing does it on its own:

- The Markets API never writes a calendar again by itself: not when it starts, not when its
  library version changes, and not on a schedule.
- `jobs/resync_calendars.py` is an admin job, separate from the deployment workflow and from
  `jobs/migrate_markets.py`. A person runs it.
- It takes the calendars to write again: named ones, or every calendar an adapter wrote.
- For each, it calls the adapter as `create_from_pandas_calendar` does. `user` rows are kept.
- It prints, per calendar, the library version before and after and the exceptions it
  added and removed. With `--dry-run` it prints the same and writes nothing.

Until the job runs, a calendar stays as the version recorded on its `Calendar` row left it.

A calendar is therefore found by `unique_identifier` only. `_find_persisted_calendar` looks a
calendar up by `source_identifier` when the first lookup finds none; with two calendars from
one source that lookup is ambiguous, and it is removed.

A 24/7 calendar is one rule, `weekdays=1111111` from 00:00 to the next midnight, and no
exceptions. `build_always_open_calendar_materialization` is removed.

### 5. Routes

- `/calendar/{uid}/dates/` and `/calendar/{uid}/sessions/` become read-only. They return the
  computed dates or sessions of a window.
- `start_date` and `end_date` are required on both (owner). Today they are optional filters
  over stored rows. A calendar now runs to its source's horizon, so a request without them
  would compute every day of it.
- `limit` and `offset` stay as they are, and so do the flag filters such as `is_holiday` and
  `is_early_close`. They apply to the computed rows. There is no cap on the window's length.
- The create, bulk-upsert, get-by-uid, update and delete routes of dates and sessions are
  removed: a computed date or session has no uid.
- `/calendar/{uid}/rules/` and `/calendar/{uid}/exceptions/` are added with the CRUD the date
  and session routes had.
- The six `/calendar/{uid}/events/` routes are removed.
- The `CalendarDate`, `CalendarSession` and `CalendarEvent` row classes, repositories and
  Command Center registry entries are removed. No alias is kept.

### 6. Consumers

- `PersistedCalendarSchedule.schedule` returns the same frame, computed from the rules and
  exceptions in one read.
- `PortfolioCalendarEvents` is unchanged in what it publishes. It now fails when its window
  ends after the calendar's `valid_to`, where today it publishes nothing.
- The portfolio timestamp repair reads sessions through the same computation.
- `PortfolioCalendarEventsStorage` stays the stored record of sessions that have happened. It
  is append-only and is written as time passes, which is where one row per session belongs.

## Worked Example

NYSE from 2024-11-25 to 2024-12-31.

Rule:

| session_label | effective_from | weekdays | opens_at_local | closes_at_local |
|---|---|---|---|---|
| regular | 1985-01-01 | 1111100 | 09:30 | 16:00 |

Exceptions:

| local_date | exception_type | closes_at_local | name |
|---|---|---|---|
| 2024-11-28 | CLOSED | | Thanksgiving |
| 2024-11-29 | EARLY_CLOSE | 13:00 | |
| 2024-12-24 | EARLY_CLOSE | 13:00 | |
| 2024-12-25 | CLOSED | | Christmas |

Computed:

- 2024-11-27, a Wednesday with no exception: open 14:30 UTC, close 21:00 UTC.
- 2024-11-28: no session, not a business day.
- 2024-11-29: open 14:30 UTC, close 18:00 UTC.
- 2024-11-30, a Saturday: no session, by the rule.

Today the same range is 37 date rows and 25 session rows. Here it is 1 rule and 4 exceptions.

`CustomNYSE`, created from the same library calendar, starts with the same rule and the same
four rows, each with `source="pandas_market_calendars"`. Its desk does not trade on
2024-12-31 and trades a full day on 2024-12-24, so a user adds:

| local_date | exception_type | source |
|---|---|---|
| 2024-12-24 | OPEN | user |
| 2024-12-31 | CLOSED | user |

Computed for `CustomNYSE`:

- 2024-12-24: open 14:30 UTC, close 21:00 UTC. The date has a `user` row, so the library's
  early close is ignored.
- 2024-12-31: no session.
- Every other date: as NYSE.

A later `create_from_pandas_calendar("NYSE", "CustomNYSE")` leaves both rows in place.

## Migration

One Alembic revision in the Markets namespace. ms-markets runs it; no consumer does anything.

1. Create `CalendarSessionRule` and `CalendarException`.
2. For each calendar, convert its stored rows in Python:
   - the rule of each session label is its most frequent weekday set and local open and close
     times;
   - every stored date that the rule does not reproduce becomes an exception, with the
     calendar's `source` as its `source`, or `user` where the calendar has none;
   - `valid_from` and `valid_to` are set to the first and last stored `local_date`.
3. Compute each calendar from its new rows and compare it with the stored rows. A difference
   fails the revision.
4. Drop `CalendarDate`, `CalendarSession` and `CalendarEvent`. Rows in `CalendarEvent` are
   not converted: they are deleted with the table.

The conversion uses the stored rows and not the source library, so a deployment keeps the
calendar it had. Step 2 also repairs the headers that drifted: a calendar whose rows end
before its `valid_to` gets the `valid_to` its rows support.

After the revision a calendar still ends where its stored rows ended. Running
`jobs/resync_calendars.py` takes it to the library's horizon. The revision does not run it.

## What Issue 83 Still Needs

- `bulk_upsert_model` still sends all its rows in one statement. Every other caller keeps the
  exposure, so the batching is still needed.
- The failure still reaches the caller as a bare `500`.

Both are [issue 84](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/84).
Issue 83 was closed on 2026-11-17 for its calendar part.

## Rejected Alternatives

### Keep The Per-Date Rows And Batch The Write

It removes the `422`. The daily rewrite, the header drift, the windowed reads and the stored
UTC instants stay.

### Store Holiday Rules

A rule such as "the fourth Thursday of November" would need a rule engine, which is what the
source libraries are. A stored date is simpler to read, to correct and to audit.

### Store Nothing And Ask The Library On Read

The answer would then depend on the library version installed in each process, and a user's
own calendar or correction would have nowhere to live. ADR 0028's reason for persistence
stands.

### Keep The Per-Date Tables As A Derived Copy

Nothing joins them in SQL today. A copy needs the sync this ADR removes. It can be added
later, built from the rules and exceptions, if a reporting use needs it.

### The Markets API Writes Calendars Again By Itself

The API would compare the library version on each `Calendar` row with the installed one when
it starts, and write the calendars that differ. Rejected by the owner: whether a calendar
takes a library's new answers is the user's decision. An upgrade of the API would otherwise
change calendars, and with them future rebalance dates, without anyone asking for it.

### Reuse `CalendarEvent` For Exceptions

An event is a dated fact about a product or a convention, with a target. An exception decides
whether a date is a business day. One table for both would make every business-day read filter
out the events.

## Consequences

- A calendar is about 12 rows a year. It is written once, to its source's horizon, and nothing
  is extended as time passes.
- The header and its rows cannot disagree: they are written in one transaction, and a read
  outside the range fails.
- A calendar changes only when someone writes it: a user's row, or the re-sync job. An
  upgrade of the Markets API does not change it, so a closure a new library version knows is
  missing until the job runs or a user adds it.
- A calendar can be corrected by hand, and the correction survives the adapter.
- One library calendar can back several stored calendars, each with its own corrections.
- `create_from_pandas_calendar` loses `valid_to` and `materialize`, `valid_from` becomes
  optional, and its first two arguments are positional.
- A calendar is no longer found by its `source_identifier`.
- A reader gets a whole calendar in one read.
- A date in SQL can no longer be joined to a calendar row. Code that needs business days asks
  the computation.
- This is a breaking release: three tables, their row classes and sixteen routes are
  removed.
- A portfolio whose calendar's `valid_to` has passed stops with an error where it was silent.
  After the first adapter write under this ADR that date is the library's horizon.
- Price interpolation (`msm_portfolios/contrib/prices/updaters.py`) and `intraday_trend`
  still ask pandas-market-calendars directly, by a calendar name read from the asset object,
  with `24/7` when it has none. A correction to a stored calendar therefore changes a
  portfolio's rebalance dates and not the bars of its assets. Linking an asset to a stored
  `Calendar` changes the asset model and the price updaters, and gets its own ADR (owner).

## Decisions Taken During Implementation

These were not in the accepted text. Each is a choice the code had to make.

- **Local times are `HH:MM:SS` text.** MetaTables declares a type for date, timestamp and
  JSON parameters only, so a `TIME` parameter would travel untyped. The stated fallback is
  used: `String(8)` columns, validated and normalized by the row payloads.
- **The adapter finds the regular weeks in the library's schedule, not in its settings.**
  Each full week has a signature: the weekdays with a session and the week's most frequent
  hours. A signature that holds for six weeks in a row is a regular week, and a rule starts
  where it starts. Up to two holiday weeks in a row may sit inside those six, as at the turn
  of a year. This needs nothing from the library but `schedule()`. It finds a change of
  hours on the day the library has it (CME equities: 2005-09-12 and 2012-11-19), a change of
  weekend (Tel Aviv, 2026-01-05), and an exchange that opened later (IEX gets no rule and no
  closure before 2013).
- **"Reproduces the library" is in local time.** The library computes UTC instants with
  pandas, which stops applying daylight saving in 2100. The stored local times do not. The
  adapter's test compares wall-clock times over the whole range and UTC instants to
  2099-12-31.
- **A calendar with nothing to project has a first date.** Decision 2 says both bounds are
  null. `valid_to` is null. `valid_from` is the first date the rules cover, because before
  it the calendar has no rule and would read as closed without an error.
- **Writing a calendar again changes exceptions by difference.** The adapter reads its own
  stored exceptions, deletes those the library no longer has and inserts those it learned.
  A row that did not change keeps its uid. When nothing changed, nothing is written.
- **Writing a calendar again never shortens its history.** Without a `valid_from`, the write
  starts at the earlier of the stored `valid_from` and 1990-01-01. A converted calendar that
  starts in 2022 is taken back to 1990.
- **A calendar is written again only from the source that wrote it.** Writing `CustomNYSE`
  from the library's LSE, or writing a hand-made calendar from the library, is refused: it
  would replace the rules.
- **A caller cannot choose an exception's `source`.** The row payloads and the routes do not
  accept it. Only an adapter writes another source, through the calendar services.
- **Two `user` exceptions for one date and session cannot contradict each other.** A
  `CLOSED` row next to another `user` row for the same date and session is refused when it
  is written. An adapter's row on the same date does not count: the user's row wins.
- **`PortfolioCalendarEvents` starts at the calendar's `valid_from`.** Its first run starts
  on 2018-01-01. A calendar that begins later has no event before its first date, so the
  read starts there. A window that ends after `valid_to` still fails.
- **The timestamp repair reads the part of its window the calendar is complete for.** It
  inspects stored values and reports a value with no expected session. It is the one reader
  that does not refuse a window outside the range.
- **`is_weekend` follows the calendar's week.** It is true on a weekday no rule runs on. The
  per-date rows stored Saturday and Sunday for every calendar, a 24/7 one included.
  `is_holiday` is true on a date a rule runs on that has no session. A date no rule
  covers, such as one before an exchange opened, is neither.
- **An update of a rule or an exception is checked like a new one.** The stored row and
  the change are validated together, so an update cannot put a close time on a `CLOSED`
  exception or end a rule before it starts.
- **The conversion makes one rule per session label.** A stored business day with no session
  row becomes a date-only session, so it stays a business day. A date stored as not a
  business day that also has a session stops the revision. A `timezone` that is not an IANA
  name becomes `UTC`, which keeps the stored instants.
- **`jobs/resync_calendars.py` is declared in the workflow file** as `resync-calendars`, in
  no execution step and with no schedule, so the platform has a Job a person can run.
- **A refused window answers `400`** on the computed routes, with the calendar's range in
  the message, as the API's other routes answer a refused value. A request without
  `start_date` or `end_date` answers `422`, and an unknown calendar `404`. The computed
  items carry `calendar_uid` and no `uid`.
- **Rules and exceptions can be deleted under the remote backend.** `CalendarSessionRule`
  and `CalendarException` define their own `delete`. A row class that inherits the base
  `delete` is not offered remotely, and deleting a `user` exception is how a user restores
  the library's answer.

## Implementation Notes

### 2026-11-17: 4.0.0

- Models: `CalendarSessionRuleTable`, `CalendarExceptionTable`; `CalendarTable.valid_from`
  and `valid_to` nullable. Revision `0027_calendar_rules_and_exceptions`.
- Computation: `msm.services.calendars.computation`. Adapter:
  `msm.services.calendars.pandas_market`. Write and re-sync: `msm.services.calendars.sync`,
  `msm.repositories.calendars.definition`.
- Row API: `CalendarSessionRule`, `CalendarException`, `Calendar.sessions`,
  `Calendar.dates`, `Calendar.is_business_day`, `Calendar.create_from_pandas_calendar`.
- Job: `jobs/resync_calendars.py`.
- Measured with the adapter on all 211 calendar names of pandas-market-calendars 5.4.0,
  from 1990-01-01 to each calendar's horizon:
  - 210 reproduce the library session for session. The 211th, `XSGO`, fails inside the
    library's own `schedule()`.
  - 199 calendars need one rule, 8 need two, 2 need three and 1 needs four.
  - The median calendar has 2,243 exceptions for 211 years. NYSE has 2,518.
  - No session opens or closes on another day than its regular week's, so an exception needs
    no day offset.
  - 200 calendars end on 2200-12-31. Five have no holidays and no last date (`24/7`, `24/5`
    and three FX names). Five end earlier because the library cannot compute their
    holidays: `XSHG` and `XSES` on 2026-12-31, `XSAU` on 2029-12-31, `XHKG` on 2049-12-31
    and `XKRX` on 2050-12-31.
- Run on PostgreSQL 16 in a local container, with rows shaped like a deployment's:
  - Revision 0027 turned 6,024 NYSE rows into 1 rule and 116 exceptions, and 5,550 rows of
    another calendar into 1 rule and 84 exceptions. Each computed back to the stored
    sessions. The downgrade and a second upgrade ran.
  - The legacy full upgrade from revision 0017 ran with every table seeded.
  - One write of a calendar to 2200, about 2,500 exceptions, ran as one transaction of nine
    statements, and reading it back paged through the exceptions.

## Not Verified

- The revision was not run on a deployment or on TimescaleDB. One deployment's rows were
  checked with read-only queries on 2026-11-17: every stored business day has a session,
  no date stored as not a business day has one, and every session opens and closes on its
  own date, so the conversion's checks pass there.
- Whether the hosted MetaTables API accepts a transaction of nine statements carrying about
  2,500 rows. Each statement is inside the 1,000,000-character limit and the list inside 32
  statements. It ran through the MetaTables SQLite backend and through psycopg on
  PostgreSQL, not through the hosted API.
- How the platform creates the `resync-calendars` Job from the workflow file, and whether a
  person can start it with arguments there. The declaration copies `migrate-markets`. Its
  workload User needs `data_writer` on `mainsequence.markets`, which an owner grants.
- Whether the Command Center sends `start_date` and `end_date` when it lists a calendar's
  dates or sessions, and whether it shows the removed event routes. Its code is not in this
  repository. If it sends none, it has to change in the same release.
- Whether any deployment has `CalendarEvent` rows. The one checked on 2026-11-17 has none.
- A calendar with a lunch break keeps one session from the library's open to its close, as
  the per-date rows did. The break is not stored.
- A calendar whose hours differ by weekday stores the odd weekday as exceptions. Tel Aviv
  has 14,516 for that reason. It is correct and it is many rows.
- The descriptions of QuantLib, pandas-market-calendars, exchange_calendars and Strata were
  read from the linked sources. SAP's is from its documentation and a third-party page.
  Bloomberg, Copp Clark and Murex were not checked.
