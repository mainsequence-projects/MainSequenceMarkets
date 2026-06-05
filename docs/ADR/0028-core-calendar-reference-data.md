# 0028. Core Calendar Reference Data Model

## Status

Accepted - planned

This ADR defines the target architecture for robust calendar reference data in
core `msm`. It is not yet implemented.

## Context

The current calendar model is too weak for the way calendars are used across
markets workflows.

Core `msm` already has a `CalendarTable`, but it stores a named JSON payload:

```text
-----------------------------+
| CalendarTable              |
|-----------------------------|
| uid PK                      |
| name unique                 |
| calendar_dates JSON         |
| metadata_json               |
+-----------------------------+
```

Portfolio code does not use this table as a relational dependency. Portfolio
identity stores a loose string:

```text
PortfolioTable.calendar_name
```

Rebalance strategies use another loose string validated by
`pandas_market_calendars`:

```text
RebalanceStrategyBase.calendar_key -> pandas_market_calendars.get_calendar(...)
```

That creates three separate calendar concepts with no enforced relationship:

```text
CalendarTable.name
PortfolioTable.calendar_name
RebalanceStrategyBase.calendar_key
```

The same weakness affects future pricing and fixed-income workflows. Swaps,
bonds, futures, fixings, settlements, payment schedules, and portfolio rebalance
dates all need deterministic calendar semantics. A helper library such as
`pandas_market_calendars` can generate dates, but it should not be the canonical
domain model.

## Decision

Calendars are core market reference data and belong in `msm`, not in
`msm_portfolios` or `msm_pricing`.

`msm` will model calendars as a named, versioned set of dates, sessions, and
calendar-level events. Adapters such as `pandas_market_calendars`, QuantLib
helpers, exchange feeds, or vendor files can generate calendar rows, but the
persisted `msm` calendar tables are the source of truth for library workflows.

The core model has four concepts:

```text
CalendarTable
  calendar identity, type, timezone, source, and validity horizon

CalendarDateTable
  one row per calendar/local date with business-day and holiday flags

CalendarSessionTable
  optional intraday sessions for dates that have trading or fixing windows

CalendarEventTable
  calendar-level events such as exchange holidays, early-close events,
  generic fixing days, expiry calendars, settlement calendars, or roll dates
```

Calendar materialization must be bounded. The project should not attempt to
create infinite calendars. Each calendar has a validity horizon such as:

```text
valid_from = 1990-01-01
valid_to   = 2050-12-31
```

For most financial calendars, one row per date is a standard and practical
contract. Even a 100-year daily materialization is roughly 36,500 rows per
calendar, which is modest for Postgres and gives deterministic joins,
overrides, auditability, and reproducible backtests.

## Core Table Shape

### CalendarTable

```text
+-----------------------------+
| CalendarTable               |
|-----------------------------|
| uid PK                      |
| unique_identifier unique    |
| display_name                |
| calendar_type               |
| timezone                    |
| source                      |
| source_identifier           |
| valid_from                  |
| valid_to                    |
| metadata_json               |
+-----------------------------+
```

Suggested `calendar_type` values:

```text
TRADING
SETTLEMENT
FIXING
BUSINESS
HOLIDAY
EVENT
CUSTOM
```

Examples:

```text
XNYS
TARGET
USD_GOVT
CME_EQUITY_INDEX
CRYPTO_24_7
```

`source` and `source_identifier` describe where the materialization came from:

```text
source = pandas_market_calendars
source_identifier = NYSE

source = quantlib
source_identifier = TARGET

source = vendor
source_identifier = CME_EQ_INDEX

source = user
source_identifier = custom desk calendar
```

### CalendarDateTable

```text
+-----------------------------+
| CalendarDateTable           |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| local_date                  |
| is_business_day             |
| is_holiday                  |
| is_weekend                  |
| is_early_close              |
| holiday_name nullable       |
| metadata_json               |
| unique(calendar_uid,        |
|        local_date)          |
+-----------------------------+
```

This table is the canonical daily join surface.

Consumers can answer:

```text
is this date valid for this calendar?
is this date a business day?
is this date a holiday?
was this date an early close?
```

without importing `pandas_market_calendars`, QuantLib, or vendor adapters.

### CalendarSessionTable

```text
+-----------------------------+
| CalendarSessionTable        |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| local_date                  |
| session_label               |
| opens_at UTC nullable       |
| closes_at UTC nullable      |
| timezone                    |
| is_primary                  |
| metadata_json               |
| unique(calendar_uid,        |
|        local_date,          |
|        session_label)       |
+-----------------------------+
```

Sessions are optional but important for trading, intraday portfolios, fixings,
and execution windows. Examples:

```text
regular
pre_market
post_market
pit
electronic
fixing_window
```

For simple holiday or settlement calendars, `CalendarDateTable` may be enough.

### CalendarEventTable

```text
+-----------------------------+
| CalendarEventTable          |
|-----------------------------|
| uid PK                      |
| calendar_uid FK             |
| event_date nullable         |
| event_time UTC nullable     |
| event_type                  |
| event_label nullable        |
| target_type nullable        |
| target_uid nullable         |
| target_identifier nullable  |
| metadata_json               |
+-----------------------------+
```

This table is for events that belong to the calendar or market convention, not
to a single instrument position.

Examples:

```text
EXPIRY
LAST_TRADE
FIRST_NOTICE
FIXING
SETTLEMENT
ROLL
EARLY_CLOSE
HOLIDAY
```

`target_type`, `target_uid`, and `target_identifier` are optional because some
events are general calendar facts, while others may be scoped to a product
family, index, asset, or future contract.

## Mental Model

Calendar rows are reusable reference data:

```text
+-----------------------------+
| CalendarTable               |
+--------------+--------------+
               |
               | calendar_uid
               v
+-----------------------------+       +-----------------------------+
| CalendarDateTable           |       | CalendarSessionTable        |
| one row per local date      |       | zero or more sessions/date  |
+-----------------------------+       +-----------------------------+
               |
               | calendar_uid
               v
+-----------------------------+
| CalendarEventTable          |
| calendar-level events       |
+-----------------------------+
```

Application-specific schedules are not the same thing as calendars.

```text
CalendarTable
  reusable market/date system

InstrumentScheduleEventTable
  instrument-specific generated cashflow/fixing/payment/reset events
```

Do not put every bond coupon or swap reset date directly into
`CalendarEventTable`. Those belong to instrument-specific schedule tables in the
owning domain package.

## Adapters

`pandas_market_calendars` becomes an adapter, not the source of truth:

```text
pandas_market_calendars.get_calendar("NYSE")
        |
        v
CalendarTable("XNYS")
        |
        +--> CalendarDateTable
        +--> CalendarSessionTable
        +--> CalendarEventTable where applicable
```

QuantLib and fixed-income helpers follow the same rule:

```text
QuantLib TARGET calendar
        |
        v
CalendarTable("TARGET")
        |
        +--> CalendarDateTable
```

Core `msm` should not depend on QuantLib. QuantLib-specific adapters belong in
`msm_pricing` or another optional package.

## Portfolio Usage

Portfolios should not use a loose `calendar_name` string as the durable
relationship.

Target direction:

```text
+-----------------------------+       +-----------------------------+
| PortfolioTable              |       | CalendarTable               |
|-----------------------------|       |-----------------------------|
| uid PK                      |       | uid PK                      |
| unique_identifier unique    |       | unique_identifier unique    |
| calendar_uid FK ------------+------>| display_name                |
| portfolio_index_uid FK      |       | timezone                    |
| DataNode UID pointers       |       | valid_from / valid_to       |
+-----------------------------+       +-----------------------------+
```

`PortfolioTable.calendar_uid` should reference `CalendarTable.uid`.

Serialized portfolio/rebalance configurations may keep a readable
`calendar_identifier`, but runtime persistence should resolve it to
`CalendarTable.uid`.

Portfolio rebalance logic should consume materialized calendar dates/sessions,
not call `pandas_market_calendars.get_calendar(...)` as the canonical source
during every workflow.

## Fixed-Income And Pricing Extension Model

Fixed-income instruments should reference calendars through foreign keys, but
their generated schedules should live in instrument-specific tables.

Example future bond extension direction:

```text
+-----------------------------+       +-----------------------------+
| BondAssetDetailsTable       |       | CalendarTable               |
|-----------------------------|       |-----------------------------|
| asset_uid PK/FK             |       | uid PK                      |
| issuer_uid                  |       | unique_identifier unique    |
| currency_asset_uid          |       +-----------------------------+
| issue_date                  |              ^       ^       ^
| maturity_date               |              |       |       |
| payment_calendar_uid -------+--------------+       |       |
| settlement_calendar_uid ----+----------------------+       |
| fixing_calendar_uid --------+------------------------------+
+-----------------------------+
```

Swap or rate-product extensions can use the same model:

```text
+-----------------------------+       +-----------------------------+
| SwapAssetDetailsTable       |       | CalendarTable               |
|-----------------------------|       |-----------------------------|
| asset_uid PK/FK             |       | uid PK                      |
| pay_leg_payment_calendar_uid+------>| unique_identifier unique    |
| receive_leg_payment_cal_uid +------>| timezone                    |
| pay_leg_fixing_calendar_uid +------>| valid_from / valid_to       |
| receive_leg_fixing_cal_uid  +------>|                             |
+-----------------------------+       +-----------------------------+
```

Instrument-specific generated dates should use a separate schedule table owned
by the instrument/pricing package:

```text
+-----------------------------+       +-----------------------------+
| InstrumentScheduleEvent     |       | CalendarTable               |
|-----------------------------|       |-----------------------------|
| uid PK                      |       | uid PK                      |
| asset_uid FK                |       +-----------------------------+
| calendar_uid FK ------------+------>|
| event_date                  |
| event_time nullable         |
| event_type                  |
| leg_key nullable            |
| amount nullable             |
| currency_asset_uid nullable |
| metadata_json               |
+-----------------------------+
```

The `calendar_uid` in an instrument schedule event means:

```text
this event was generated or resolved using this calendar
```

It does not mean the event is a global calendar event.

## Package Boundary

Core `msm` owns:

```text
CalendarTable
CalendarDateTable
CalendarSessionTable
CalendarEventTable
calendar import/materialization service interfaces
```

`msm_portfolios` owns:

```text
portfolio calendar FK usage
portfolio/rebalance schedule consumption
pandas_market_calendars import helpers if needed for portfolio examples
```

`msm_pricing` owns future TODO work:

```text
QuantLib calendar adapters
fixed-income instrument calendar FK usage
instrument schedule generation
InstrumentScheduleEvent-style tables
```

## Repository Organization

The implementation should replace the current flat calendar module with
calendar-owned packages. Calendar persistence remains in core `msm`; package
specific code only consumes or adapts those persisted calendars.

Core SQLAlchemy MetaTable declarations:

```text
src/msm/models/calendars/
  __init__.py
  core.py          # CalendarTable
  dates.py         # CalendarDateTable
  sessions.py      # CalendarSessionTable
  events.py        # CalendarEventTable
```

Core public row APIs:

```text
src/msm/api/calendars/
  __init__.py
  core.py          # Calendar
  dates.py         # CalendarDate
  sessions.py      # CalendarSession
  events.py        # CalendarEvent
```

Core calendar services and repositories:

```text
src/msm/services/calendars/
  __init__.py
  materialization.py
  pandas_market.py
  validation.py

src/msm/repositories/calendars/
  __init__.py
  core.py
  dates.py
  sessions.py
  events.py
```

Focused tests should follow the same boundaries:

```text
tests/msm/models/calendars/
tests/msm/api/calendars/
tests/msm/services/calendars/
```

User-facing docs and examples should be package-scoped:

```text
docs/knowledge/msm/calendars/index.md
examples/msm/calendars/calendar_materialization_workflow.py
```

Portfolio integration belongs in `msm_portfolios` and should not own core
calendar rows:

```text
src/msm_portfolios/services/calendars.py
src/msm_portfolios/rebalance_strategy/calendar_resolver.py
tests/msm_portfolios/calendars/
```

Pricing and fixed-income integration remains a later `msm_pricing` TODO:

```text
src/msm_pricing/calendars/quantlib_adapter.py
src/msm_pricing/calendars/instrument_schedule.py
```

## Implementation Plan

### Stage 1: Core Calendar Tables

- [x] Replace the JSON-only `CalendarTable` shape with a robust calendar
  identity table keyed by `unique_identifier`.
- [x] Add `CalendarDateTable` with one row per `(calendar_uid, local_date)`.
- [x] Add `CalendarSessionTable` with one row per
  `(calendar_uid, local_date, session_label)`.
- [x] Add `CalendarEventTable` for calendar-level events.
- [x] Add table descriptions, column descriptions, indexes, and FK constraints.
- [x] Add all calendar tables to the core `msm` MetaTable provider model graph.

### Stage 2: Core Calendar API And Services

- [x] Add Pydantic row APIs under `msm.api.calendars`.
- [x] Add typed upsert/filter helpers for calendar identity, dates, sessions,
  and events.
- [x] Add service functions to materialize a bounded date horizon.
- [x] Add validation that `valid_from` and `valid_to` bound materialization.

### Stage 3: Adapter Helpers

- [x] Add a `pandas_market_calendars` adapter that materializes
  `CalendarDateTable` and `CalendarSessionTable` rows.
- [x] Keep adapter dependency optional if possible; core persisted tables must
  not require portfolio code.
- [x] Add examples for `XNYS` and `CRYPTO_24_7` style calendars.

### Stage 4: Portfolio Integration

- [x] Add `PortfolioTable.calendar_uid` FK to `CalendarTable.uid`.
- [x] Deprecate `PortfolioTable.calendar_name` as durable relationship state.
- [x] Update `Portfolio` row API payloads to accept `calendar_uid` and/or a
  `calendar_identifier` resolver.
- [x] Update rebalance strategy code to consume persisted calendar schedules
  instead of treating `pandas_market_calendars` as the canonical source.
- [x] Update portfolio examples and docs.

### Stage 5: Pricing And Fixed-Income TODO

- [ ] Design fixed-income calendar FK fields for bond and swap detail tables.
- [ ] Design instrument-specific schedule event tables.
- [ ] Add QuantLib calendar adapters in `msm_pricing`, not core `msm`.
- [ ] Add pricing examples for payment, fixing, settlement, and accrual
  schedule generation.

## Consequences

Calendar semantics become reusable across portfolios, execution, pricing,
fixed income, derivatives, and backtests.

Persisted calendar rows make workflows deterministic and auditable. The tradeoff
is more rows, but bounded daily materialization is manageable and follows common
financial-system practice.

Portfolio code will need a migration away from loose calendar strings. Pricing
work remains intentionally TODO so core `msm` does not take a QuantLib
dependency.
