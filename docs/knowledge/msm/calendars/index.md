# Calendars

Calendars are core `msm` reference data. They describe bounded local-date,
session, and calendar-event facts that other packages can reference by
`CalendarTable.uid`.

The canonical source is persisted MetaTable rows, not
`pandas_market_calendars`, QuantLib, or any vendor helper. Those helpers are
adapters that materialize rows into the core calendar tables.

## Scope

Calendars answer these questions:

- which local dates belong to a market, fixing, settlement, or custom calendar;
- whether each date is a business day, holiday, weekend, or early close;
- which optional session windows exist on a local date;
- which calendar-level events belong to a market convention.

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
               v
+-----------------------------+
| CalendarDateTable           |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| local_date                  |
| business / holiday flags    |
| unique(calendar_uid, date)  |
+-----------------------------+
               |
               | optional session facts for the same calendar/date
               v
+-----------------------------+
| CalendarSessionTable        |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| local_date                  |
| session_label               |
| opens_at / closes_at UTC    |
| unique(calendar_uid,        |
|        date, label)         |
+-----------------------------+
```

`CalendarEventTable` is a sibling of dates and sessions:

```text
+-----------------------------+
| CalendarEventTable          |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| event_date / event_time     |
| event_type / event_label    |
| optional target identity    |
+-----------------------------+
```

Calendar events are convention facts such as `EXPIRY`, `FIXING`,
`SETTLEMENT`, `ROLL`, `EARLY_CLOSE`, or `HOLIDAY`. Instrument-specific payment
or fixing schedules should live in the instrument-owning package and point back
to the calendar used to generate them.

## Primary Modules

- `msm.models.calendars`: SQLAlchemy MetaTable declarations.
- `msm.api.calendars`: public Pydantic row APIs and class-owned row helpers.
- `msm.repositories.calendars`: compiled SQL persistence helpers.
- `msm.services.calendars`: materialization helpers and adapters.

## User API

Users create or update calendar identities through `msm.api.calendars.Calendar`:

```python
from datetime import date

from msm.api.calendars import Calendar, CalendarType

calendar = Calendar.upsert(
    unique_identifier="XNYS",
    display_name="New York Stock Exchange",
    calendar_type=CalendarType.TRADING,
    timezone="America/New_York",
    source="pandas_market_calendars",
    source_identifier="NYSE",
    valid_from=date(2026, 1, 1),
    valid_to=date(2026, 12, 31),
)
```

Date, session, and event rows have their own APIs:

```python
from msm.api.calendars import CalendarDate, CalendarEvent, CalendarSession
```

For bulk date/session writes, prefer `msm.services.calendars` materialization
helpers rather than calling row upserts one row at a time.

For common generated calendars, the row API owns the entrypoint:

```python
from msm.api.calendars import Calendar

crypto_calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)

xnys_calendar = Calendar.create_from_pandas_calendar(
    source_identifier="NYSE",
    unique_identifier="XNYS",
    display_name="New York Stock Exchange",
    valid_from="2026-01-01",
    valid_to="2026-12-31",
)
```

`create_from_pandas_calendar(...)` upserts the `Calendar` row and, by default,
materializes bounded `CalendarDate` and `CalendarSession` rows in the active
runtime. Use `source_identifier="24/7"` for a crypto always-open calendar.

## Materialization

`pandas_market_calendars` is an adapter:

```python
from msm.services.calendars import (
    build_pandas_market_calendar_materialization,
    materialize_calendar_rows,
)

rows = build_pandas_market_calendar_materialization(
    calendar_uid=calendar.uid,
    source_identifier="NYSE",
    start_date=calendar.valid_from,
    end_date=calendar.valid_to,
    timezone=calendar.timezone,
)
materialize_calendar_rows(runtime.context, rows)
```

For 24/7 markets, prefer `Calendar.create_from_pandas_calendar(...)` with
`source_identifier="24/7"` in user workflows. Use
`build_always_open_calendar_materialization(...)` only when you need lower-level
service control.

The date range is intentionally bounded. Do not create infinite calendars.

## Portfolio And Pricing Boundaries

`msm_portfolios` may reference `CalendarTable.uid` through
`PortfolioTable.calendar_uid`. Portfolio rows do not duplicate calendar names.

`msm_pricing` may add future QuantLib adapters and instrument schedule tables.
Those schedule tables should reference `CalendarTable.uid` but remain outside
core `msm`.

## Example

See `examples/msm/calendars/calendar_materialization_workflow.py` for the core
calendar workflow and
`examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` plus
`examples/msm_portfolios/portfolio_equal_weights_run.py` for a portfolio that
creates or reuses a `CRYPTO_24_7` calendar before writing the
`Portfolio.calendar_uid` relationship.

## Related Concepts

- [Models](../models/index.md)
- [Services](../services/index.md)
- [msm_portfolios](../../msm_portfolios/index.md)
- [msm_pricing](../../msm_pricing/index.md)
