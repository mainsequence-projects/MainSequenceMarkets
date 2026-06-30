# Calendars

Materialize durable market, settlement, fixing, or custom calendar facts. The
persisted session rows produced here are what portfolio construction depends on
in [Portfolios](04-portfolios.md).

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Calendar materialization

Use this workflow when a project needs durable market, settlement, fixing, or
custom calendar facts:

1. Before runtime, run the admin migration flow with
   `mainsequence migrations upgrade --provider migrations:migration head`.
2. Attach `Calendar`, `CalendarDate`, `CalendarSession`, and `CalendarEvent`
   with `msm.start_engine(...)`.
3. Use `Calendar.create_from_pandas_calendar(...)` for generated market
   calendars, including `source_identifier="24/7"` for the standard crypto
   24/7 calendar.
4. Use `msm.services.calendars` directly only when lower-level materialization
   control is required.

`pandas_market_calendars` is not the durable source of truth. It is an adapter
that writes into `CalendarDateTable` and `CalendarSessionTable`; consumers
should read the persisted rows or reference `CalendarTable.uid`.
Portfolio construction depends on those persisted session rows. A portfolio
calendar with no sessions for the requested update range raises a calendar
materialization error instead of producing an empty portfolio no-op.

```python
from msm.api.calendars import Calendar

calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)
```

See `examples/msm/calendars/calendar_materialization_workflow.py` for the
calendar workflow covering XNYS materialization from `pandas_market_calendars`
and a `CRYPTO_24_7` calendar. See
`examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` and
`examples/msm_portfolios/portfolio_equal_weights_run.py` for the portfolio
workflow using the generated crypto calendar as `Portfolio.calendar_uid`.
Repeated portfolio runs are idempotent when upstream price coverage has not
advanced past the latest stored portfolio value: the portfolio DataNode reports
no new rows instead of calling the calendar with a reversed update window.

**Next →** [Accounts and Holdings](03-accounts.md)
