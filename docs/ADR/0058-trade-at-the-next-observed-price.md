# 0058. Trade At The Next Observed Price

## Status

Accepted (2026-11-18). The owner decided the rule in
[issue #89](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/89) on
2026-11-18. Implemented on a branch for `development`; see "Implementation Notes".

The owner then separated facts from choices (decision 9): the strategy base enforces the
facts and no setting changes them; a configurable, hash-bearing execution policy owns the
choices, and the owner's decisions are its defaults.

- It amends [ADR 0040](0040-portfolio-temporal-ownership.md): the immediate `signal_time`
  mode, and the position ledger's own execution schedule.
- It extends [ADR 0056](0056-asset-trading-calendar-link.md), decision 7: a strategy that
  reads a calendar must use the portfolio's `calendar_uid`, and `ImmediateSignal` now reads
  one.
- It relies on ADR 0056, decision 4a: a price's `time_index` is the moment it was observed.

## Context

Read on `development` at `9ce4b7c2`.

- `ImmediateSignal.select_events` turned every signal observation into an event at its own
  `time_index`, and the strategy declared no dependency. A Saturday, after-close or
  Thanksgiving signal wrote executed weights at that time.
- `CalendarEventSignal` placed rebalances at calendar events without checking that a price
  was observed then.
- `PortfolioEngine` depended on the signal weights and the strategy's inputs, not on
  `PortfolioRebalance`. It rebuilt the schedule with `build_accounting_schedule`, with its
  own window, so it could record other trades than `PortfolioRebalance`. It re-sized every
  position at every scheduled event, also when `PortfolioRebalance` recorded nothing.
- `TargetWeightExecutionModel` required its own mark within `maximum_staleness` for every
  executed asset and raised `Missing fresh execution valuations` without one, even when the
  strategy supplied the execution price it then used.
- `InterpolatedPrices` writes forward-filled rows, flagged `interpolated=True`, where nothing
  traded.

A signal is the application's target weights. It can arrive at any hour and is not a trade.
An executed weight is a trade, and a trade happens at a price observed at its time.

## Decision

### 1. The earliest moment comes from the portfolio's calendar (owner)

The strategy's moment is the signal's `time_index` for `ImmediateSignal`, and each selected
`market_open` or `market_close`, plus `event_offset`, for `CalendarEventSignal`. Its target
is the latest signal at or before that moment.

- If the moment is inside a session of the portfolio's calendar, the earliest moment is the
  strategy's moment. "Inside" is `market_open <= t <= market_close`: a close is a moment the
  market trades.
- Otherwise the earliest moment is the calendar's next `market_open`.
- On a 24/7 calendar a session closes at the instant the next opens, so every moment is
  inside one, and the earliest moment is always the strategy's moment.

The sessions are the published events of the strategy's `calendar_events` dependency, read
for the strategy's `calendar_identifier` and `session_label`. On an incremental run the
latest open and close before the window are read explicitly, so a window that starts
mid-session knows the market is open. `PortfolioCalendarEvents` publishes events only up to
the time it runs, so a target set while the market is closed waits for a run after the next
open has been published.

### 2. Each asset trades at its next observed price (owner)

The price comes from the portfolio's `valuation_source_instance` and `valuation_column`. It
is the first row of the asset whose `time_index` is at or after the earliest moment **and
strictly after the `time_index` of the signal that set the target**, and that lies inside a
session of the portfolio's calendar: `market_open < time_index <= market_close`. A signal
stamped 16:08:00, perhaps computed from the 16:08 bar, never fills at that bar.

A bar is stamped at its end, so a row stamped exactly at an open describes the time before
the session and is not inside it. `InterpolatedPrices` writes synthetic rows at each
`market_open` and `market_close`, filled from the previous session; the open row never
counts, and neither does an after-hours row of an asset listed elsewhere.

Strategies that declare their own data (`TimeWeighted`, `VolumeParticipation`,
`LiquidityConstrained`, `TrailingAverageDailyVolumeParticipation`) keep trading at it, under
the same conditions: a bar trades only toward a signal observed strictly before it, an
asset moves only at its own observed row, at that row's observed price, and interpolated
rows and unobserved fill columns never count. These strategies declare no calendar, so
their earliest moment is their own moment and no session bounds their rows.

### 3. Only observed prices count (owner)

A row with `interpolated=True` is never a trade price, in the valuation source or in a
strategy's bars. A row without a finite positive price is not one either. The fill column
must be a value observed at its row's `time_index`, a close or a mark: `open`, `high`, `low`
and `vwap` describe the bar's interval and are refused as fill columns. Valuing a holding at
its last observed price is unchanged.

### 3a. A held asset is valued at its last observed price, however old (owner)

In the ledger and in the weights path, a held asset is always valued at its last observed
price at or before the valuation time, however old, and a foreign amount at its last
observed FX rate. Past the valuation policy's `maximum_staleness`
(`MarketPriceValuationModel.maximum_staleness`, `ValuationAlignmentPolicy.maximum_staleness`)
the price or rate is marked stale, never refused: `maximum_staleness` is that marking
threshold. Only a held asset with no observed price at all at or before the time raises.

- **Ledger.** The valuation reference carries `"stale": "true"`, `ValuationResult.stale_sources`
  lists it, and the event's `valuation_summary` row names it in its `extension_payload`
  (`{"stale_sources": ["valuation:<asset>", "fx:<currency>"]}`); a summary without stale
  sources has no payload.
- **Weights path.** `align_asset_observations` returns a `stale` column, and the portfolio
  value row has `valuation_stale` set when a held asset used a stale price
  (`PortfoliosStorage.valuation_stale`, Alembic revision 0029; nullable, null on rows
  written before it). `PortfoliosUpdater` also logs a warning naming those holdings. A
  provider with its own `PortfoliosTS` instances adds the column in a revision of its own:
  registration verifies instances against the contract's columns.

Marking is a choice of the valuation policy, and refusing stays an option:
`ValuationAlignmentPolicy.fail_on_missing_values` and
`MarketPriceValuationModel.fail_on_missing_values`, both `False` by default, raise on a price
or rate older than `maximum_staleness` instead of marking it.
`TargetWeightExecutionModel.maximum_staleness` is removed: sizing reads the last prices and
FX rates before the earliest moment (decision 6a), and a fill's FX rate is the last observed
at the fill, however old.

### 4. Assets fill independently, and a missing price makes the trade wait (owner)

Each asset of a target fills at its own next observed price. Between fills the portfolio is
partly rebalanced and the unfilled part is cash. A halted asset fills at its first observed
price after the halt. A delisted asset stays open until a newer signal replaces its target.
A missing price never raises.

Only an asset whose order steps gets a row: `PortfolioRebalance` writes it at the price's
own `time_index`, with the weight the fill reached as `weight_after` and the observed price
as `execution_price`. `execution_status` is the order's: `complete` once all of it filled,
`partial` while some is open, `cancelled` once its remainder was cut (decision 9); a
cancellation that filled nothing has no price. An asset waiting for a price has no row and
keeps the weight of its latest row. An asset with a zero target and a zero weight has
nothing to do. A newer target replaces the running rebalance at the first instant it could
trade itself, at or after its earliest moment and strictly after its signal; the orders not
filled yet are replaced by the newer target's.

Assets reach their latest rows at different times, so the state before a window is the
latest row of every asset, not the rows at the latest time: the update statistics hold the
latest time of every `(intent, asset)`, and those rows are read exactly. The newest target
with a fill is rebuilt from the signal that set it, which the signal read seeds before the
window.

### 4a. Time stamps are the moments things were known (owner)

A signal's `time_index` is the moment it was known, the same contract as a price's: the
producer is responsible for it. The rule uses `time_index` as it is; there is no
`observed_at` or publication-time logic for signals.

There is no completeness watermark for prices either. An asset waiting on a target looks for
its next observed price from that target's earliest moment, not from the run's window start
(the last recorded fill plus 1 ns): a slow asset's bar can arrive after another asset's later
fill was recorded, and it is still that asset's next observed price. A bar inserted later
into a gap the asset already traded across is a price correction, outside this ADR.

### 5. A fill is a trade, even when the weight does not change

A fill trades the asset to its target at the observed price. When a new target repeats an
asset's weight, the fill leaves `weight_after` unchanged and still carries the price: the
position ledger resizes the position to that weight at its NAV. A row carries an
`execution_price` exactly when its asset traded at that time.

### 6. The ledger books the recorded fills (owner)

`PortfoliosUpdater` refuses accounting configurations, so ledger portfolios run only
through `PortfolioEngine`. It depends on `PortfolioRebalance` (`portfolio_rebalance_instance`,
which replaces `signal_weights_instance`) and books exactly the fills it recorded: time,
asset and price. The ledger does not rebuild the schedule and does not look up its own mark
for a fill. `build_accounting_schedule` and `AccountingRebalanceEvent` are removed.

### 6a. Share counts are fixed once, at the decision (owner)

A rebalance fixes the share count of every asset once, at its decision:

```text
target quantity = target weight x NAV / price
```

NAV and every price are the last observed strictly before the rebalance's earliest moment,
the same set for all assets. Each asset then fills its fixed count at its own next observed
price, and the weight it reaches comes from the fill, not from the target.

| Rebalance | Sized with |
| --- | --- |
| `ImmediateSignal` at 16:07:23, in session | the 16:07:00 bar |
| Saturday signal | Friday's close |
| `CalendarEventSignal` at the close | the bar before 21:00, never the 21:00 close it fills at |

Sizing at the decision is the execution policy's default (`sizing="at_decision"`, decision
9); `"at_fill"` sizes each asset at its own fill from the NAV and its price then.
`PortfolioRebalance` sizes its book at the decision with the valuation source's last rows
before the earliest moment, interpolated rows included as the ledger values them, and
records each order's shares in the row's `strategy_state`.

The ledger runs the decision at the instant before the earliest moment that the fills record
(`earliest_time_index`): it values the portfolio there and asks the execution model for the
counts (`decision_quantities`). The NAV, the prices and the FX rates are the last observed
before that instant, however old (decision 3a): a decision after a weekend reads Friday's
close. Each recorded fill trades the same part of the ledger's own open order as it traded
of the book's (`fill_fraction`), rounded toward zero to the lot step; a complete fill trades
to the decided count. A strategy with its own bars records no earliest moment and is sized
at each fill, as before.

Each fill carries its price's `time_index` (`AssetExecution.price_time_index`), and the
ledger books it as an event stamped at that time. A price observed at another time is
refused, so a later price never enters an earlier event, and NAV at an event uses only marks
observed at or before it.

### 7. The calendar is required and is the portfolio's (owner)

`ImmediateSignal` requires `calendar_events_instance` and `calendar_identifier`;
`session_label` defaults to `"regular"`. `CalendarEventSignal` inherits them. The dependency
must publish both `market_open` and `market_close`: a `PortfolioCalendarEvents` configured
with one event type is refused when the strategy is built, published events of one type are
refused when read, and a calendar with no published events is refused. `PortfoliosUpdater`
refuses an `ImmediateSignal` or `CalendarEventSignal` whose `calendar_identifier` is not the
portfolio's `calendar_uid` (ADR 0056, decision 7).

### 8. Every strategy, and new identities (owner)

The rule lives in `RebalanceStrategyBase`. Its hash-bearing `fill_rule` field,
`"next_observed_price"`, states it, so every portfolio gets a new identity. Existing
portfolios are retired and kept as history, never deleted. There is no optional or legacy
mode.

### 9. Facts in the base, choices in the execution policy (owner)

The facts hold for every strategy that trades at the portfolio's observed prices, and no
setting changes them:

- a fill uses a price observed strictly after the signal and at or after the earliest
  moment; only observed, non-interpolated rows count;
- with the portfolio calendar, a fill price is inside a session (`market_open < t <=
  market_close`);
- the fill column is observed at its row's time (`open`, `high`, `low`, `vwap` refused);
- each fill carries its price's time, the ledger books the recorded fills, and every time
  stamp is an observation time.

The choices are `ExecutionPolicy`, the `execution_policy` field of `ImmediateSignal` (and
`CalendarEventSignal`), returned by the base's `fill_policy` hook. It is part of the
strategy's identity. Its defaults are the owner's decisions:

| Field | Default | Choice |
| --- | --- | --- |
| `sizing` | `at_decision` | shares fixed at the decision (6a), or `at_fill` |
| `negative_cash` | `not_allowed` | or `fraction_of_nav`, or `fixed_amount` with a ledger ([ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md)) |
| `negative_cash_limit` | `0.0` | the fraction, or the amount in the portfolio's currency |
| `sells_before_buys` | `True` | sells at an instant are booked first and pay its buys |
| `cash_shortfall_allocation` | `pro_rata` | buys at one instant short of cash fill the same fraction |
| `uncovered_buys` | `cut_and_cancel` | see below |
| `calendar_gating` | `portfolio_calendar` | `none`: no earliest-moment wait and no session check |

`PortfolioRebalance` runs the policy on a book of shares and cash. Its unit is the NAV at the
portfolio's first rebalance and never rescales, so an asset's shares change only when it
fills and the row of that fill records them. At each instant with eligible prices the
policy books sells, then buys with the cash on hand plus the allowed negative cash. A buy
cash cannot cover fills what it can and waits for the rebalance's pending sells; once none
is pending, the rest is cut and cancelled with the reason `insufficient_cash`.

Each row's `strategy_state` (schema 2) holds the decision (`earliest_time_index`,
`decision_nav`, `weight_at_decision`, `decision_price`), the order (`target_shares`,
`order_shares`, `filled_shares`, `remaining_shares`, `fill_fraction`, `cancelled_shares`,
`cancel_reason`) and the book after the instant (`held_shares`, `cash`). A run resumes the
newest rebalance from the latest row of every asset: shares from each asset's own row, cash
from the newest row, and the orders without a row sized again from the decision.

The ledger books those fills (6a) and records each cancellation as execution progress with
the row's `strategy_state`. It cuts only what is its own: lot rounding, execution costs and
lifecycle cash can leave its cash short of the book's. Its buys then share what is left
down to the policy's floor, pro rata, rounded down to the lot step, and the progress record
carries `ledger_cut` with the quantity and the reason.

The book and the ledger's cut are in the portfolio's currency; prices and cash in another
currency are converted at the last observed FX rate ([ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md)).

## Worked Examples

`ImmediateSignal`, NYSE regular session 14:30–21:00 UTC, prices stamped at observation:

| Signal (UTC) | Asset | Portfolio calendar | 1-minute bars | Daily closes |
| --- | --- | --- | --- | --- |
| Wed 11-18 16:07:23 | AAPL | NYSE | Wed 16:08 | Wed 21:00 |
| Wed 11-18 16:08:00 | AAPL | NYSE | Wed 16:09 | Wed 21:00 |
| Wed 11-18 21:30 | AAPL | NYSE | Thu 14:31 | Thu 21:00 |
| Sat 11-21 10:00 | AAPL | NYSE | Mon 14:31 | Mon 21:00 |
| Thu 11-26 15:00 (Thanksgiving) | AAPL | NYSE | Fri 14:31 | Fri 18:00 (half day) |
| Sat 11-21 10:00 | London-listed | NYSE | Mon 14:31 | Mon 16:30 (London close) |
| Sat 11-21 10:00 | London-listed | 24/7 | Mon 08:01 | Mon 16:30 (London close) |

London trades through the NYSE open, so the London asset has a bar stamped 14:30. It is not
inside the session (`market_open < time_index`), and the first price is 14:31.

`CalendarEventSignal`, signal Tue 11-17 22:00:

| Event | 1-minute bars | Daily closes |
| --- | --- | --- |
| `market_close` | Wed 21:00 | Wed 21:00 |
| `market_open` | Wed 14:31 | Wed 21:00 |

Several assets: AAPL first trades at 14:31 and an illiquid asset at 14:45. AAPL fills at
14:31 and the illiquid asset at 14:45. In between, the portfolio holds the new AAPL weight,
the old weight of the illiquid asset, and cash for the difference.

Cash, with the default policy:

| Case | Result |
| --- | --- |
| $200 of cash, a buy sized at $200 fills at a price 5% higher ($210) | 95.24% fills; the rest is cancelled, `insufficient_cash` |
| $1,000,000 of cash, two buys sized at $500,000 fill at $525,000 each | each fills 95.24%; the rest of each is cancelled |
| Fully invested; the sell is halted, the buy has a price | the buy waits; it fills at its first price after the sale |
| Same, `negative_cash_limit=0.5` | the buy fills half at once and the rest after the sale |

## Not Decided Here

Decided after this ADR, in [ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md):
the fixed-amount cash limit, the portfolio's currency and FX source, cash across
currencies, and weights that drift in the weights-only path. Decision sizing and the cash
rule for the strategies with their own bars are
[issue #90](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/90),
built on 2026-11-22 (see "Implementation Notes").

Also not decided here:

- `InterpolatedPrices` back-fills rows before an asset's first observed bar on its first run.
  Known, left for later.
- [Issue #88](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/88): the
  first rebalance of a `CalendarEventSignal` portfolio.
- A calendar for the bar strategies. They declare none, so the earliest moment does not gate
  them.

## Rejected Alternatives

### Rebalance At The Next Session Start

The first design put a closed-market rebalance at the next `market_open` itself. A session
start is not a price: with 1-minute bars stamped at their end, nothing was observed at 14:30,
and with daily closes the first price is hours later.

### Keep The Ledger's Own Schedule

The ledger would keep recording trades `PortfolioRebalance` never made, and failing on its
own stale marks for prices the rebalance already observed.

### A Row For Every Asset At Every Fill

A first implementation wrote, at each fill, a row for every asset of the target: `pending`
for the waiting ones, and `superseded` rows when a newer target replaced them. It kept the
state at one time, but it stamped assets with an event at a time they had no price. Rows are
written only for fills, and the state is the latest row of every asset.

### Calendar Events As A Ledger Input With A Revision

An early variant kept the ledger's schedule and exempted the calendar input from the
ledger's `source_revision` requirement. Once the ledger books recorded fills it reads no
strategy input, and the exemption has nothing to apply to.

### An Optional Legacy Mode

Rejected by the owner: existing portfolios get new identities instead.

## Consequences

- A portfolio trades at the times its valuation source observes prices. A daily-close source
  trades at closes; 1-minute bars trade within the minute after the earliest moment.
- `PortfolioRebalance` declares the valuation source as a dependency when its strategy has no
  bars of its own; `PortfolioEngine` declares `PortfolioRebalance`.
- Rebalance-state rows are written only for fills, at the price's time, and `event_source`
  is `"valuation_source"` for the strategies that trade at the valuation source. A strategy
  with its own bars still writes a row for each asset of an event; only a row that traded
  carries a price.
- A `CalendarEventSignal` re-sized ledger positions at every selected event before; the
  ledger now trades only at the fills of a new target.
- A slow asset's fill (decision 4a) can be recorded after another asset's later fill, so
  `PortfolioRebalance` writes a row earlier than rows it already wrote. `PortfolioWeights`
  projects only rows after its latest projection and does not pick that row up, and the
  position ledger's replay refuses the changed history (the later fills are sized from a
  different NAV). Neither is handled here.
- A calendar dependency that publishes only closes, accepted for a `CalendarEventSignal`
  before, is refused.

## Implementation Notes

### 2026-11-18: branch for `development`

- `RebalanceStrategyBase`: `fill_rule`; the hooks `session_events` and
  `own_execution_prices`; `build_transitions(..., fill_prices=...)` with a path for the next
  observed price and one for a strategy's own bars; `simulate_recorded_fills`;
  `earliest_moment` and `observed_prices`; `dependency_seed_coordinates`, which
  `read_rebalance_input` uses to read the latest rows before a window.
- `ImmediateSignal`: the calendar fields, the dependency, its checks and `session_events`;
  `select_events` returns the signals as the strategy's moments. `CalendarEventSignal`
  inherits them.
- `PortfolioRebalance`: reads the valuation source's observed prices and passes them as
  `fill_prices`.
- `PortfolioEngine`: `portfolio_rebalance_instance`; `calculate_backtest(...,
  rebalance_state=...)`; `recorded_fills`. `TargetWeightExecutionModel` books the recorded
  price and executes only the filled assets.
- Removed: `build_accounting_schedule`, `simulate_accounting_event`,
  `target_selection_mode` and `AccountingRebalanceEvent`. Targets are the latest signal at
  or before each strategy moment, and no strategy used another mode.
- Seed reads select rows at or before the microsecond floor of a window start, so a row
  stamped at the last fill time is not lost (`strictly_before`).
- `in_session` and `require_observed_price_column`; `AssetExecution.price_time_index`;
  `PortfolioRebalance._previous_state` reads the latest row of every asset.
- `RebalanceStrategyBase.recorded_earliest_moment`: `PortfolioRebalance` reads prices from
  the newest recorded rebalance's earliest moment.
- `PositionExecutionModel.decision_quantities` (`TargetWeightExecutionModel` implements it)
  and `AssetExecution.target_quantity`: the booker runs each rebalance's decision and every
  fill trades to its fixed count.
- `ExecutionPolicy`, `RebalanceBook` (`rebalance_strategy/execution_policy.py`); the base's
  `fill_policy` hook, `ImmediateSignal.execution_policy`.
- `PortfolioRebalance` reads the valuation source from the newest recorded rebalance's
  earliest moment: observed rows as `fill_prices`, and all rows plus each asset's last row
  before the window as `reference_prices` (`valuation_prices`).
- Ledger: `AssetExecution.fill_fraction` and `status`; `recorded_fills` keeps
  cancellations; `AccountingExecutionContext.negative_cash_limit` and the ledger's own cut;
  `PortfolioWeights` projects cancelled rows, which can carry a partial fill.
- Tests: `tests/msm_portfolios/time_index/test_next_observed_price.py` and
  `test_execution_policy.py`.

### 2026-11-22: strategies with their own bars (#90)

[Issue #90](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/90)
applies decisions 6a and 9 to `TimeWeighted`, `VolumeParticipation`,
`LiquidityConstrained` and `TrailingAverageDailyVolumeParticipation`. Decision 6a's "a
strategy with its own bars records no earliest moment and is sized at each fill" no
longer holds.

- **The earliest moment.** A bar trades only toward a signal observed strictly before
  it (decision 2), so a new target's moment, and its earliest moment, is the first of
  the strategy's selected bars after its signal (the first bar inside the strategy's
  window). The issue says "the last observations strictly before the earliest moment"
  without naming that moment for these strategies; this reading is the implementation's.
- **Sizing at the decision.** The order is fixed at the instant before the earliest
  moment: target weight x NAV / price, with each asset's last row of the strategy's own
  bars strictly before it. Interpolated rows count there, as they value the portfolio
  (decision 6a); they never fill. A target with an asset that has no bar before its
  earliest moment cannot be sized and raises, as at the next observed price.
- **Slices.** At each bar the strategy's `bar_slices` say how much of each open order
  may trade there (`BarSlice`, in shares of the book); `ExecutionPolicy.step(...,
  slices=...)` books them with the cash rules and never fills more than an order has
  open. `TimeWeighted`: what the even schedule from the earliest moment to that day's
  `rebalance_end` is still short of, so an order that missed bars catches up.
  `VolumeParticipation`: `max_percent_volume_in_bar` of the bar's volume.
  `LiquidityConstrained`: `max_liquidity_fraction` of the available liquidity.
  `TrailingAverageDailyVolumeParticipation`: the lesser of what is left of the daily cap
  and `max_bar_participation` of the bar's notional; the cap counts what filled.
- **Cash.** Buys short of cash at one bar fill the same fraction of their slices; once
  the rebalance's sells have filled, what a buy cannot pay is cut and its order
  cancelled (`insufficient_cash`). Without a calendar, `calendar_gating` has no effect.
- **The book.** The rows are those of decision 9 (schema 2), written only for a step of
  an order, at its bar, with `event_source` the bar's input and the strategy's facts
  about the bar under `strategy_state["bar"]`. No `pending` or `superseded` row is
  written: a newer target replaces the running rebalance at its earliest moment. A
  resumed run rebuilds the book from the stored rows; `PortfolioRebalance` reads the
  strategy's bars from the newest rebalance's earliest moment with each asset's last bar
  before it (`read_strategy_inputs`).
- **The book's unit.** It is the NAV at the portfolio's first rebalance. For the three
  strategies sized in money or volume (`SizedBarStrategy`), one unit is
  `total_notional` in the portfolio's currency, with or without a ledger:
  `RebalanceStrategyBase.book_unit_value`. `TimeWeighted` has no size; a ledger's
  initial NAV gives its book a currency, as for `ImmediateSignal`.
- **The ledger** runs each rebalance's decision and books every slice as a fill, at its
  bar's price and time, trading the recorded fraction of its own open order; its own
  cut applies (`cash_floor`).
- Code: `BarSlice`, `RebalanceStrategyBase.bar_slices`, `bar_state` and
  `book_unit_value`; `BarStrategy` and `SizedBarStrategy`
  (`rebalance_strategy/bars.py`); `ExecutionPolicy.size_at_fill`. `apply_event` and the
  weight-based loop are removed (this amends ADR 0040, decision 2).
- Tests: `tests/msm_portfolios/time_index/test_bar_strategy_orders.py`.

## Not Verified

- A run on hosted data. Existing portfolios must be retired by their owners; nothing here
  retires them.
- How often a slow asset's bar arrives behind another asset's recorded fill in deployed
  sources, which decides whether the projection and ledger consequences above need work.
