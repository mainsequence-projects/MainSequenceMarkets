# Calendars

Create durable market, settlement, fixing, or custom calendars. Portfolio
construction in [Portfolios](04-portfolios.md) reads the sessions of the
calendar created here.

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Creating a calendar

A calendar is stored as its regular week plus the dates that differ from it:
session rules and exceptions. Dates and sessions are computed from those rows
when they are read. [Calendars](../knowledge/msm/calendars/index.md) explains
the model; this chapter is the workflow.

1. Before runtime, run the admin migration flow with
   `metatables --local migrations upgrade --provider msm_migrations:migration head`.
2. Attach `Calendar`, `CalendarSessionRule`, and `CalendarException` with
   `msm.start_engine(...)`.
3. Use `Calendar.create_from_pandas_calendar(...)` for a calendar the
   `pandas_market_calendars` library has, including `"24/7"` for the standard
   crypto calendar.
4. Write `CalendarSessionRule` and `CalendarException` rows yourself for a
   calendar no library has, or to correct one that came from the library.

```python
import msm

from msm.api.calendars import Calendar

msm.start_engine(models=["Calendar", "CalendarSessionRule", "CalendarException"])

calendar = Calendar.create_from_pandas_calendar(
    "24/7",
    "CRYPTO_24_7",
    display_name="Crypto 24/7",
)
```

The first argument is the library's calendar and the second is the name of the
stored one. No end date is passed: the calendar is written as far as the library
can answer, so nothing has to be extended as time passes.

`pandas_market_calendars` is not the durable source of truth. It is an adapter
that writes rules and exceptions; consumers read the stored calendar or
reference `CalendarTable.uid`.

## Reading it

```python
import datetime as dt

sessions = Calendar.sessions(calendar.uid, dt.date(2026, 5, 25), dt.date(2026, 5, 31))
is_open = Calendar.is_business_day(calendar.uid, dt.date(2026, 5, 30))
```

Each session carries its `local_date` and its `opens_at` and `closes_at` as UTC
instants. A read outside the calendar's `valid_from` to `valid_to` raises
`CalendarRangeError` instead of returning fewer sessions.

Portfolio construction reads sessions the same way. A portfolio whose calendar
does not exist, or whose update window ends after the calendar's `valid_to`,
fails with an error instead of producing an empty portfolio no-op.

See `examples/msm/calendars/calendar_rules_and_exceptions_workflow.py` for the
calendar workflow: NYSE stored under a custom name, corrections made by hand, a
`CRYPTO_24_7` calendar, and a calendar written with one session rule. See
`examples/msm_portfolios/portfolio_equal_weights_run.py` for the portfolio
workflow using the generated crypto calendar as `Portfolio.calendar_uid`.
Repeated portfolio runs are idempotent when upstream price coverage has not
advanced past the latest stored portfolio value: the portfolio TimeIndexTableUpdater reports
no new rows instead of calling the calendar with a reversed update window.

**Next →** [Accounts and Holdings](03-accounts.md)
