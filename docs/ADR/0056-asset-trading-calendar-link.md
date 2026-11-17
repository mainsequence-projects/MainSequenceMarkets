# 0056. Asset Trading Calendar Link

## Status

Accepted (2026-11-17). The decisions marked (owner) were made by the owner on 2026-11-17,
one at a time. Implemented on `development`; see "Implementation Notes".

- It builds on ADR 0055: it reads that ADR's rules, exceptions and computed sessions.
- It finishes, for prices, what [ADR 0028](0028-core-calendar-reference-data.md) decided for
  rebalancing: workflows read stored calendars and do not ask `pandas_market_calendars`.

## Context

Everything in this section was read from the code on `development` on 2026-11-17, as
committed at `603b4413`, before ADR 0055 and this ADR were implemented. It describes what
this ADR replaces. "Checked" means the call
was run. Where a statement is an inference, it says so.

### Three calendars, and they are not connected

| Question | Where the answer comes from today | Stored calendar? |
|---|---|---|
| When does a portfolio rebalance? | `calendar_identifier` on `PortfolioCalendarEventsConfiguration` and on `CalendarEventSignal`. `resolve_rebalance_calendar` turns it into a stored `Calendar` | Yes |
| Which calendar is the portfolio's? | `Portfolio.calendar_uid`, a required FK to `Calendar.uid` with `ON DELETE RESTRICT` | Yes |
| Which bars exist for an asset? | A calendar name read off the asset scope item, passed to `pandas_market_calendars` | No |

- The rebalance dates do not come from `Portfolio.calendar_uid`. They come from the
  `calendar_identifier` in the strategy's configuration. `Portfolio.calendar_uid` is read by
  the portfolio timestamp repair and by the public API. `PortfoliosUpdater` only checks that
  it is set and writes it back.
- No code in `src` compares the two. A portfolio can carry one calendar on its row and
  rebalance on another.
- The other rebalance strategies (`ImmediateSignal`, `TimeWeighted` and the rest) read no
  calendar.
- A portfolio's value series is indexed by its price bars:
  `_calculate_portfolio_workflow_values` takes its timestamps from the valuation source. So
  the asset's calendar decides when the portfolio has a value, and the strategy's calendar
  decides when it trades.

### Where an asset's calendar name comes from

`asset_calendar(asset)` in `msm_portfolios/asset_scope.py` tries, in order:

1. `asset.get_calendar()`, when the scope item has that method;
2. the `calendar` key or attribute of the scope item;
3. the `calendar` key of the item's `metadata` mapping;
4. the string `"24/7"`.

None of these reads stored data:

- The core `Asset` table has `uid`, `unique_identifier` and `asset_type`. No asset table
  (`AssetType`, `OpenFigiAssetDetails`, `CurrencySpotAssetDetails`, `BondAssetDetails`,
  the category tables) has a calendar column.
- No class in this repository defines `get_calendar` on an asset. Step 1 only serves objects
  from outside the repository.
- An `Asset` row cannot be a scope item at all. A scope object must expose
  `asset_identifier`; the `Asset` row has `unique_identifier`, and
  `asset_scope_identifier` raises `TypeError`.

So the name is whatever the caller typed into the scope. For each caller of the price
updater in this repository:

| Caller | Scope items | Calendar the bars use |
|---|---|---|
| `examples/msm_portfolios/portfolio_equal_weights_example.py` | Mappings with `"calendar": "24/7"` | `24/7`, typed in the example |
| `docs/knowledge/msm_portfolios/portfolios/index.md` | Strings | `24/7`, by default |
| `tests/identity/test_pinned_identities.py`, `tests/msm_portfolios/time_index/test_engine_instance_tables.py` | Strings | `24/7`, by default. Neither runs an update |
| `tests/msm_portfolios/time_index/test_storage_first_surface.py` | A mapping with `"calendar": "NYSE"` | `NYSE`. It tests the map only |
| `get_interpolated_prices_timeseries` | `AssetsConfiguration.asset_list`, passed through | Whatever the items carry. No caller in `src` |
| `InterpolatedPrices` with no `asset_list` | `bars_ts.get_asset_list()` of the source | Whatever the source's items carry |

`InterpolatedPrices.update` builds one `asset_calendar_map` from the scope and passes each
asset's name to the interpolation functions.

### Every call to the library outside the adapter

The adapter is `msm/services/calendars/pandas_market.py` and
`Calendar.create_from_pandas_calendar` (with `_pandas_market_calendar_timezone`) in
`msm/api/calendars/core.py`. Outside it:

| Place | Call | What it needs from the calendar |
|---|---|---|
| `contrib/prices/updaters.py`, `_get_schedule_cached` (daily bars) | `mcal.get_calendar(name).schedule(start, end)`. For `24/7` it builds its own frame and does not call the library | A schedule frame for the bars' range: one row per session with `market_open` and `market_close` in UTC. Output bars are stamped at `market_close`; `open_time` is filled from `market_open` |
| same file, `interpolate_intraday_bars` | `mcal.get_calendar(calendar.name)`, one `schedule(min, max)` and then `schedule(day, day)` for every trade day | The range frame, to add each open and close to the bar index. A single-day lookup: no row means closed, and the open and close clip the day's bar grid |
| same file, `UpsampleAndInterpolation.upsample_bars` | `mcal.get_calendar(calendar).schedule(min, max)`, turned into a dict by session | A single-day lookup of open and close. A trading-halt flag, taken from the name: `trading_halts = calendar_name != "24/7"` |
| `contrib/signals/intraday_trend.py` | `mcal.get_calendar(self.calendar).schedule(start, end)` | The range frame. Each session's open and close bound an intraday grid at `source_frequency` |
| `services/calendars.py`, `PandasMarketCalendarSchedule` | `mcal.get_calendar(key).schedule(start, end)` | The range frame. It is reached only through `resolve_legacy_rebalance_calendar`, which nothing in `src` or `apps` calls |

All five read the same thing: sessions with an open and a close. The halt flag is the only
extra, and it is a property of the sessions (see "4").

### Defects found while reading

- **The intraday path cannot take a name.** `interpolate_intraday_bars` reads
  `calendar.name`, and `asset_calendar` returns a string by default. A string has no `.name`
  (checked: `AttributeError`). `upsample_bars` then passes the same value to
  `mcal.get_calendar`, which refuses an object (checked with a library calendar:
  `RuntimeError`). So minute bars work only for a scope object whose `get_calendar()`
  returns something with `.name`, and never with upsampling. No test covers the intraday
  path.
- **A 24/7 day closes at three different times.** The daily path's own frame closes at
  23:59 UTC. The library's `24/7` calendar closes at the next midnight (checked on 5.4.0),
  and so does `AlwaysOpenCalendarSchedule`. A stored calendar created from the library's
  `24/7`, as the example does, publishes its `market_close` event at the next midnight while
  the example's daily bars are stamped at 23:59.
- **`IntradayTrend` cannot run.** `_calculate_signal_weights` calls
  `price_source.related_time_series` and
  `price_source.pandas_df_concat_on_rows_by_key_between_dates`. Neither name exists
  elsewhere in `src`, nor in the installed `metatables` and `mainsequence` packages. The
  method fails before it reaches the calendar. Only its identity hash is tested.
- **The name is not checked until an update runs.** The pinned-identity test builds
  `IntradayTrendConfig(calendar="XNAS")`. The library has no calendar of that name (checked:
  `RuntimeError`).

### `msm_pricing`

`msm_pricing` is not affected and stays out of scope.

- It builds QuantLib `ql.Calendar` objects from codes in its own data
  (`CurveBuildingDetails.calendar_code`, index conventions, instrument JSON through
  `calendar_from_json`).
- It imports nothing from `msm.api.calendars`, `msm.services.calendars` or
  `msm.models.calendars`, has no `calendar_uid`, and does not import
  `pandas_market_calendars` (checked with a search of `src/msm_pricing`).
- Those calendars answer payment, fixing and settlement questions for an instrument. ADR
  0028 keeps them in type-specific tables and leaves them as its stage 5. This ADR links the
  calendar that says when an asset has price bars, and nothing else.

## Decision

### 1. The link is a one-to-one detail table (owner)

`AssetCalendar` in core `msm`, beside the other asset detail tables:

| Column | Meaning |
|---|---|
| `asset_uid` | Primary key. FK to `Asset.uid`, `ON DELETE CASCADE` |
| `calendar_uid` | FK to `Calendar.uid`, `ON DELETE RESTRICT`, as on `Portfolio.calendar_uid`. Not null |

- It is the calendar whose sessions say when the asset has price bars.
- An asset has at most one. An asset whose bars come from two venues with different hours
  is two assets.
- The description of `AssetTable` says it "holds only shared asset identity and
  asset_type", with other properties in one-to-one detail tables. A calendar is a property,
  not identity. A currency asset has none. So the link follows `OpenFigiAssetDetails`: its
  own table keyed by `asset_uid`. [ADR 0006](0006-asset-package-boundary.md) puts it under
  `msm.models.assets`.
- The row class is `AssetCalendar`, with `asset_uid` as its upsert key, as `OpenFigiDetails`
  has.
- A calendar that an asset uses cannot be deleted. A deleted asset loses its link.

### 2. An asset with no link fails the price update (owner)

- `DEFAULT_MARKET_CALENDAR`, `FULL_CALENDAR` and `asset_calendar` are removed. There is no
  default calendar.
- The price updater checks its whole scope before it reads any bar. When an asset has no
  `AssetCalendar` row, or its identifier is not an `Asset` row, the run fails. The error
  names every asset that has no calendar.
- The whole run fails. The assets that are linked get no bars in that run either: a skipped
  asset would be another gap nobody is told about.
- Nothing else fails. An asset without a calendar is a valid row; a currency never needs
  one. Creating the asset, the updater or the portfolio is not refused.
- A portfolio that reads those prices gets no new bars until the price run succeeds.
- An asset that trades around the clock is linked to a stored 24/7 calendar, like any other.
  ADR 0055 stores that as one rule and no exceptions.
- A scope mapping that carries a `calendar` key is refused (owner), the way a
  `unique_identifier` key is refused today. The error says the key is no longer read and
  points to the asset's link.

### 3. One way to get a schedule from an asset

`msm_portfolios.services.calendars` gets one function: from a list of asset identifiers to
a `PersistedCalendarSchedule` per asset.

1. Read the `Asset` rows by `unique_identifier`. The interpolated price storage already has
   a foreign key from `asset_identifier` to `Asset.unique_identifier`, so every asset with
   bars is a row.
2. Read their `AssetCalendar` rows.
3. Read each distinct `Calendar` once.

Three reads for any number of assets, plus ADR 0055's one read of rules and exceptions per
distinct calendar. All go through the row API, so they work under the runtime backend and
the remote backend.

`PersistedCalendarSchedule.schedule(start, end)` is ADR 0055's computed frame: one row per
session, `market_open` and `market_close` in UTC. A read past the calendar's `valid_to`
fails, as ADR 0055 decides.

### 4. The price updaters take a schedule, not a name

`InterpolatedPrices.update` resolves its assets with "3" and computes each distinct
calendar's frame once for the update window. It passes the frame down.

| Function | Today | Proposed |
|---|---|---|
| `interpolate_daily_bars` | `_get_schedule_cached(name, start, end)` | The frame, sliced to the bars' range |
| `interpolate_intraday_bars` | Library object, one range call, one call per day | The same frame. The per-day lookup is a lookup by session date; a missing date is a closed day |
| `upsample_bars` | Library object, a dict by session, a flag from the name | The same frame. The flag is computed |

- **The halt flag.** A window has trading halts when some session does not open at the
  instant the previous one closed. This is computed from the frame. A stored 24/7 calendar
  has none. A 24/7 calendar that a user closed for a day has one, which the name could not
  say.
- `_get_calendar_by_name` and `_get_schedule_cached` are removed, with their `lru_cache`.
  `import pandas_market_calendars` leaves the file.
- The string/object defect of the intraday path goes away: the functions no longer receive
  a calendar.

### 4a. Daily bars: the close, the window and the source's contract (owner)

`interpolate_daily_bars` keeps the rows whose timestamp is a session close, and fills each
from the latest source bar at or before it. It was run on a 24/7 asset with four daily bars
(closes Monday 101, Tuesday 102, Wednesday 103, Thursday 104):

| Source stamps a day's bar at | Close 23:59 (today) | Close at the next midnight |
|---|---|---|
| its close (Monday's bar at Tuesday 00:00) | Monday's 101 is written at Tuesday 23:59: every close is a day late, and every row is flagged `interpolated` | Exact matches, not flagged. Monday's bar is dropped, and a row is invented one session after the last bar |
| its open (Monday's bar at Monday 00:00) | Monday's 101 at Monday 23:59: right, by accident | Tuesday's 102 is written at Monday's close: a day early |

These decisions follow.

- **A 24/7 day closes at the next midnight.** The bar takes its close from the stored
  calendar, as every other bar does. The price updater's own 23:59 frame is removed. The bar
  and the rebalance event of a 24/7 portfolio then fall on the same instant.
- **The window is chosen by close instant.** Today the function asks for the sessions
  between the *dates* of the first and the last source bar. A close at midnight falls on the
  next date, so the window is one session late at both ends: that is the dropped first bar
  and the invented last one. The sessions to keep are those whose `market_close` lies between
  the first and the last source bar. No row is written after the last source bar. Exchange
  calendars such as NYSE close on the session's own UTC date, so their output does not
  change.
- **`time_index` is the time of observation.** The library is event driven: a row is an
  event, and its `time_index` is the instant its values became known. This is the general
  rule for every time-indexed table, not a rule of the price updater. A bar holds a close,
  and a close is known when the bar ends, so a bar is stamped at its end: a daily bar at its
  session close. Its open goes in `open_time`.
- **A bar stamped at its open is not handled.** Many vendors label a bar with the start of
  its interval. Such a row says its close was known at the open, and every reader that takes
  "the latest row at or before T" would use a price from the future. The library has no
  setting for it and cannot detect it.
- **The source converts (owner).** The contract is that a source hands over bars stamped at
  the session close. A source updater that ingests vendor data stamped at the open shifts
  it to the close itself, and keeps the vendor's timestamp as `open_time`. The price updater
  does not convert and is unchanged.
- The rule is stated in the user documentation, in
  `docs/knowledge/msm/assets/asset_indexed_updaters.md` and in the valuation source section
  of `docs/knowledge/msm_portfolios/portfolios/index.md`.

### 5. `IntradayTrend` names a stored calendar (owner)

- `IntradayTrendConfig.calendar` is replaced by `calendar_identifier`, the
  `unique_identifier` of a stored `Calendar`, as on `PortfolioCalendarEventsConfiguration`.
- The signal resolves it with `resolve_rebalance_calendar` and reads
  `schedule(start, end)`. The frame has the columns it already uses.
- It keeps one calendar for the whole signal. It builds one time grid for all its assets,
  so the calendar belongs to the signal and not to each asset.
- This changes the signal's configuration, and so its hash.

### 6. The library is called by the adapter only

`PandasMarketCalendarSchedule`, `AlwaysOpenCalendarSchedule` and
`resolve_legacy_rebalance_calendar` are removed. Nothing in `src` or `apps` calls them.
After this ADR, `pandas_market_calendars` is imported only by the adapter named in
"Context". It stays a core dependency, because the adapter runs in the Markets API.

### 7. An asset's calendar and its portfolio's calendar may differ (owner)

They answer different questions, and a portfolio that holds assets from two markets cannot
have them equal.

- The asset's calendar decides which bars exist.
- The portfolio's calendar decides when it rebalances.
- When a rebalance falls where an asset has no bar, the valuation uses the asset's latest
  bar, within `ValuationAlignmentPolicy.maximum_staleness` (one day by default). With
  `fail_on_missing_values` (the default) an older bar is an error. This is today's
  behaviour and does not change.
- No new check compares the two calendars.

What changes is that both are stored calendars. When they are the same row, a correction
moves the bars and the rebalance dates together. When they differ, the difference is two
`calendar_uid` values that can be read, not a string in a configuration.

On the portfolio side there are two candidates for "the portfolio's calendar" (see
"Context"). They must be the same one (owner). `PortfoliosUpdater` refuses a `CalendarEventSignal` whose `calendar_identifier`
is not the `unique_identifier` of the portfolio's `calendar_uid`. The error names both
calendars. The other strategies read no calendar and are not checked. Then the portfolio
has one calendar, and the worked example below has one meaning.

### 8. Row API

- `AssetCalendar.upsert(asset_uid=..., calendar_uid=...)` links or relinks an asset.
- `AssetCalendar.filter(asset_uid__in=[...])` is the read in "3".
- Deleting the row unlinks the asset. Its price updates then fail (see "2").
- Routes and the Command Center registry entry are not built (see "Implementation Notes").

## Worked Example

One portfolio, `P`, holds one asset, `ACME`. The calendar is `CustomNYSE` from ADR 0055's
worked example: the library's NYSE, plus two rows a user wrote.

| local_date | exception_type | source | Effect |
|---|---|---|---|
| 2024-12-24 | OPEN | user | A full day, 14:30 to 21:00 UTC. The library has an early close at 18:00 UTC |
| 2024-12-31 | CLOSED | user | No session. The library has a full day |

`P` has `calendar_uid` of `CustomNYSE` and rebalances with
`CalendarEventSignal(calendar_identifier="CustomNYSE", rebalance_event="market_close")`.
The source has one daily bar per NYSE session, stamped at the exchange's close. Interpolation
is `ffill`.

**Today.** The scope item is `{"asset_identifier": "ACME", "calendar": "NYSE"}`. The bars
come from the library.

| Date | Rebalance event of `P` | Bar of `ACME` |
|---|---|---|
| 2024-12-23 | 21:00 UTC | 21:00 UTC |
| 2024-12-24 | 21:00 UTC | 18:00 UTC |
| 2024-12-26 | 21:00 UTC | 21:00 UTC |
| 2024-12-31 | none | 21:00 UTC |

- On 2024-12-24 `P` rebalances at 21:00 and has no bar at 21:00. Its value series has a
  point at 18:00, before the rebalance, and the next at 2024-12-26 21:00.
- On 2024-12-31 `P` gets a value on a day its calendar says is closed.
- The user's two rows changed the rebalance dates and not the bars.

**Proposed.** There is one row: `AssetCalendar(asset_uid=<ACME>, calendar_uid=<CustomNYSE>)`.
The scope item is `"ACME"`.

| Date | Rebalance event of `P` | Bar of `ACME` |
|---|---|---|
| 2024-12-23 | 21:00 UTC | 21:00 UTC |
| 2024-12-24 | 21:00 UTC | 21:00 UTC |
| 2024-12-26 | 21:00 UTC | 21:00 UTC |
| 2024-12-31 | none | none |

- 2024-12-24: the bar at 21:00 carries the source's 18:00 close and is flagged
  `interpolated`. Its `open_time` is 14:30 UTC, from the calendar. The source's 18:00 row is
  not kept: daily interpolation keeps only rows at a session close.
- 2024-12-31: no bar. The source's bar for that day is not kept. Its price move shows in the
  bar of 2025-01-02.
- Every rebalance of `P` has a bar at the same instant, and every bar is on a day `P` can
  rebalance.

If the user later deletes the 2024-12-24 row, the library's early close is back for both.
Bars and events already stored for that date stay as written (see "Consequences").

## Migration

One Alembic revision in the Markets namespace, after ADR 0055's. ms-markets runs it; no
consumer does anything.

1. Create `AssetCalendar`.
2. Write no rows (owner).

No stored data says which calendar an asset trades on, so the revision has nothing to
convert:

- The names live in callers' scope items, not in a table.
- `OpenFigiAssetDetails.exchange_code` exists for some assets. Mapping exchange codes to
  stored calendars would be a guess, and ADR 0055 allows several stored calendars for one
  exchange.

After the revision every asset is unlinked, and a price update fails until its assets are
linked. Each asset is linked by whoever owns it, with the normal write on `AssetCalendar`.
Nothing links an asset on its own.

Bars already stored are not rewritten.

- For an asset linked to a calendar created from the same library calendar, with no `user`
  rows, new bars continue the old series: ADR 0055's adapter test is that the stored
  calendar reproduces the library's schedule.
- For a 24/7 asset with daily bars, new bars are stamped at the next midnight where the old
  ones are stamped at 23:59. If the source stamps at the close, the old bars are also a day
  late (see "4a"). Rebuilding the table from its source is the user's action.
- The caller's code changes in the same release: the `calendar` key leaves the scope items,
  and `IntradayTrendConfig.calendar` becomes `calendar_identifier`.

## Rejected Alternatives

### Keep The Name In The Scope And Resolve It Against Stored Calendars

`{"asset_identifier": "ACME", "calendar": "CustomNYSE"}`, looked up as a stored calendar.
It needs no table. But the calendar stays something each caller types. Two updaters can
give the same asset two calendars, nothing can list an asset's calendar, and the owner's
decision is a link on the asset.

### One Calendar For The Whole Price Updater

`InterpolatedPricesConfig.calendar_identifier`, as `IntradayTrend` has. One updater often
covers assets from several markets. It would have to be split by market, and the calendar
would still not be on the asset.

### A Link Table With A Role

`(asset_uid, role, calendar_uid)` with roles such as `TRADING`, `SETTLEMENT` and `FIXING`.
Only the trading role has a reader. ADR 0028 puts payment, fixing and settlement calendars
in the detail tables of bonds and swaps, where one instrument can have several per leg.

### Use The Portfolio's Calendar For Its Assets' Bars

No link on the asset: bars are interpolated on the calendar of the portfolio that holds the
asset. A bar table is shared by every portfolio that reads it, and those portfolios can
have different calendars. An asset priced outside any portfolio would have no calendar.

### Fall Back To 24/7

Keep today's default for an unlinked asset, against a stored 24/7 calendar. An exchange
asset nobody linked would get weekend and holiday bars filled forward, with no error. That
is the silent behaviour this ADR removes. Rejected by the owner.

### Link Every Existing Asset To 24/7 In The Migration

It reproduces today's default, so nothing fails after the upgrade. It also writes, for
every asset, a fact nobody stated, and it is wrong for each asset a caller mapped to an
exchange. Reference data would then have to be corrected asset by asset with no way to tell
a real 24/7 link from a migrated one. Rejected by the owner: an asset that is not 24/7 must
not be linked to 24/7; it fails until it is linked correctly.

### Derive The Calendar From The Exchange Code

See "Migration". A guess written as reference data.

### Skip The Unlinked Assets And Update The Rest

The run would succeed with bars for the linked assets only. The missing ones would show as
a gap in a table, not as an error.

### Refuse A Portfolio Whose Assets Are On Another Calendar

It forbids any portfolio across two markets.

### Close A 24/7 Day At 23:59

Keep the price updater's close and move stored 24/7 calendars to it. It changes ADR 0055,
and "4a" shows it is a day late for a source that stamps at the close.

### Remove `IntradayTrend`

It cannot run today. The owner keeps it: only its calendar read is converted here.

## Consequences

- An asset's trading calendar is stored once and read by every updater. A hand correction
  to a calendar changes the bars of every asset linked to it, and the rebalance dates of
  every portfolio on it.
- A calendar now has two kinds of dependents. Changing `CustomNYSE` changes bars as well as
  rebalance dates. A user who wants different answers for the two makes two calendars from
  the same library calendar, which ADR 0055 allows.
- A correction to a past date does not rewrite stored bars or stored calendar events. Both
  tables are written as time passes. Rebuilding them is the user's action.
- An asset with no link stops its price update with an error that names it. Today it gets
  24/7 bars.
- After the upgrade no price update runs until its assets are linked. This is a breaking
  release.
- Daily bars of a 24/7 asset move from 23:59 to the next midnight. For a source that stamps
  at the close they also stop being a day late and stop being flagged `interpolated`.
- `time_index` as the time of observation is written down as the rule for every
  time-indexed table. A source whose bars are stamped at the open is not handled.
- A calendar cannot be deleted while an asset is linked to it.
- A price update fails when its window passes the calendar's `valid_to`, as ADR 0055 decides
  for every reader.
- `asset_calendar`, `DEFAULT_MARKET_CALENDAR`, `FULL_CALENDAR`, `_get_calendar_by_name`,
  `_get_schedule_cached`, `PandasMarketCalendarSchedule`, `AlwaysOpenCalendarSchedule` and
  `resolve_legacy_rebalance_calendar` are removed. No alias is kept.
- A price update makes three more reads, plus one per distinct calendar. Under the remote
  backend each is an HTTP call.
- A portfolio whose strategy names another calendar than its row is refused. Deployments
  where the two differ have to fix one of them.
- `msm_pricing` does not change.

## Implementation Notes

- **Table and migration.** `AssetCalendarTable` is in `msm/models/assets/calendars.py`.
  Revision `0028_asset_trading_calendar` creates it and writes no rows.
- **Row class.** `AssetCalendar` in `msm.api.assets`, with `asset_uid` as its upsert key.
- **Resolver.** `resolve_asset_schedules` in `msm_portfolios.services.calendars` makes the
  three reads of "3". `AssetCalendarMissingError` carries the assets with no link and the
  identifiers that are not an `Asset` row.
- **Price updater.** `InterpolatedPrices.update` resolves every asset's calendar before it
  reads a bar. It computes each distinct calendar's sessions once, for the window of the
  bars widened by a day at both ends, and passes that frame to the interpolation functions.
- **Daily window.** `_sessions_closing_between` picks the sessions whose close lies between
  the first and the last source bar.
- **Halt flag.** `_has_trading_halts` is computed from the sessions of that frame.
- **Scope.** `refuse_scope_calendar` refuses a `calendar` key, at the top level of a scope
  mapping or under its `metadata`, when the updater is built and again when it updates.
- **`IntradayTrend`.** `IntradayTrendConfig.calendar_identifier` replaces `calendar`. Its
  pinned signal uid changed with it.
- **Portfolio check.** `PortfoliosUpdater._require_strategy_calendar` runs at the start of
  `run`, before any update.
- **Removed.** `asset_calendar`, `DEFAULT_MARKET_CALENDAR`, `FULL_CALENDAR`,
  `_asset_calendar_map`, `_get_calendar_by_name`, `_get_schedule_cached`,
  `PandasMarketCalendarSchedule`, `AlwaysOpenCalendarSchedule`,
  `resolve_legacy_rebalance_calendar`, and the unused parallel branch of the price updater
  with `_get_required_cores`.
- **Not built.** Routes for `AssetCalendar` and a Command Center registry entry. The link is
  written through the row API.

## Not Verified

- **No run against a deployment.** The suite passes with the storages stubbed. A price
  update on a Markets API, the migration on PostgreSQL, and the reads under the remote
  backend were not run.
- **How deployed price sources stamp their bars.** The rule in "4a" is the end of the bar.
  Only the example source in this repository was looked at; it stamps at the close.
- **Incremental daily runs.** The window fix is tested on first runs. A run that starts from
  a previous observation was not tested.
- **The back-fill on a first run.** It is unchanged. In the run of "4a" the first rows took
  their `open_time` from the next day's bar. How far that reaches was not traced.
- **Upsampling.** `upsample_bars` takes computed sessions now. No test runs it.
- **A calendar with a break inside the day, or two sessions a day.** The price updaters read
  the `regular` session only, as `PersistedCalendarSchedule` does by default.
- **Whether `asset_list` enters the hash of `InterpolatedPrices`.** If it does, taking the
  `calendar` key out of a scope mapping changes the updater's identity.
- **Access.** Whether a price updater that runs outside the Markets API can read `Asset`,
  `AssetCalendar` and `Calendar` rows, and whether its runtime has `AssetCalendar` attached.
- **The example.** `portfolio_equal_weights_example.py` links its assets now. It was parsed,
  not run.
- **`IntradayTrend` still cannot run.** It calls two methods that exist nowhere. Only its
  calendar read was converted.
- **Deployed portfolios whose strategy calendar differs from their `calendar_uid`.** None
  was inspected. Each one stops until one of the two is fixed.
- **`get_calendar()` on scope objects from outside the repository.** It is no longer read.
