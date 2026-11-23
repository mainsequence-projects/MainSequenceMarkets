# 0063. Policies And Rebalance Strategies For Portfolios And Accounts

## Status

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23. Nothing in it is
implemented.

- The decisions marked (owner) were made by the owner on 2026-11-23, and he confirmed the
  names the same day. Everything else is a proposal.
- It is a different concept from [ADR 0062](0062-capital-given-to-a-virtual-fund.md), and
  kept apart from it (owner). ADR 0062 keeps the records of a cash fund. This ADR owns the
  choices.
- It would amend [ADR 0058](0058-trade-at-the-next-observed-price.md): `ExecutionPolicy`
  extends a base. It would amend ADR 0062: its decisions 8, 11, 12 and 13 become defaults
  of the account policy, and its two kinds of fund become two account rebalance strategies.
- It is implemented together with ADR 0062 and
  [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md), as one
  coordinated implementation (owner, 2026-11-23). The three are kept in agreement: a change
  to one is checked against the other two.

## Context

[ADR 0058](0058-trade-at-the-next-observed-price.md) separated facts from choices
(decision 9). The strategy base enforces the facts. The choices live in `ExecutionPolicy`:
a list of settings whose defaults are the owner's decisions, and which a user can change.
A rebalance strategy names its policy, and the strategy itself is a class a user extends.

An account has nothing like it. ADR 0062 wrote the account's choices as fixed rules, each
decided once: which currencies cash may be given in, what happens when more cash is taken
out than a fund holds, whether a fund may draw on the account's cash. The owner rejected
that: these are configuration, not one rule forced on every user, and users must be able to
extend them.

The seven settings of `ExecutionPolicy` are not about portfolios only. An account will need
trading rules too (owner), and they are the same choices: what is done with cash, whether
sells come before buys, and the rest.

An account is also similar to a portfolio (owner). Its target gives a weight to each
portfolio and asset, as a signal gives a weight to each asset. A portfolio has a rebalance
strategy that says when and how it moves toward its signal. An account has none. ADR 0062
describes one way an account's money moves, by hand, as if it were the only one: it is the
projection of a manual strategy (owner).

## Decision

### 1. A choice is a setting with a default (owner)

A rule that different users may reasonably want differently is a setting of a policy, with
the owner's decision as its default. It is not written into an ADR as the only behaviour.
Records and their keys stay decisions.

### 2. A policy base holds the seven settings (owner)

The seven settings of `ExecutionPolicy` move into a base, here called
`ExecutionPolicyBase`. It lives in core `msm`, because accounts live there and `msm`
imports no other package.

| Setting | What it chooses | Default |
| --- | --- | --- |
| `sizing` | When share counts are fixed | `at_decision` |
| `negative_cash` | Whether cash may go below zero | `not_allowed` |
| `negative_cash_limit` | How far below zero | `0` |
| `sells_before_buys` | Whether sells come before buys | `true` |
| `cash_shortfall_allocation` | How buys share too little cash | `pro_rata` |
| `uncovered_buys` | What happens to a buy that cash cannot cover | `cut_and_cancel` |
| `calendar_gating` | Whether the calendar gates trading | `portfolio_calendar` |

### 3. `ExecutionPolicy` extends the base, unchanged (owner)

`ExecutionPolicy` stays in `msm_portfolios` with its name, its seven settings and their
defaults. Nothing changes for a portfolio or for a strategy that names its policy.

### 4. An account policy extends the base (owner)

An account has a policy, here called `AccountPolicy`. It has the seven settings of the
base, for the account's own trading, and adds the account's own. The owner confirmed the
settings below and their names on 2026-11-23. Each default is what ADR 0062 decided.

| Setting | What it chooses | Default | Other values |
| --- | --- | --- | --- |
| `fund_cash_currencies` | Which currencies cash may be given to a fund in | `portfolio_allowed`: any currency the fund's portfolio allows | `valuation_only` |
| `fund_cash_in` | Whether giving cash needs available cash in the account | `needs_available_cash` | `unchecked`, `needs_cash_above_direct_target` |
| `fund_cash_out` | Taking out more cash than a fund holds | `refuse` | `sell_first` |
| `fund_draws_on_account` | Whether a fund's cash may go below zero on the account's cash | `not_allowed` | `up_to_limit`, with a limit |
| `fund_portfolio_removed` | A cash fund whose portfolio leaves the target | `keep_holdings` | `return_to_account` |
| `fund_unexplained_units` | Whether a cash fund gets units that no record explains | `none` | `through_allocation_policy` |
| `fund_income` | Who gets a dividend, a coupon or interest that an asset pays | `to_holders`: the owners that hold the asset, by their units | `to_account` |

For the account's own trading, the seven settings of the base rule the account's cash at the
venue (owner): the total of what its funds and its direct rows send (Execution Engine ADR 0001,
"Routing What Is Left"). `sizing` has no use there, because the orders arrive already sized.
`calendar_gating` defaults to `none` for an account: it has no portfolio calendar, and each
fund's orders are already gated by its own.

An account run by an engine has more choices (Execution Engine ADR 0001, "Choices Are
Settings"). The choices, their defaults and their names are the owner's decisions of
2026-11-23.

| Setting | What it chooses | Default | Other values |
| --- | --- | --- | --- |
| `fund_operations_while_locked` | An operation on a fund while the account's engine runs | `wait_for_engine`: the engine answers from its book | `refuse` |
| `fill_split` | How a fill for several owners is divided | `pro_rata`: the same average price for all | `first_come` |
| `rejected_orders` | A request the venue rejects or cancels | `wait_for_strategy`: held back until a strategy asks again | `resend` |
| `failed_strategy` | A fund's strategy that raises | `stop_that_fund`: the others go on | `stop_the_account` |
| `internal_match_working_orders` | Whether a working order is pulled back to trade internally | `no` | `yes` |
| `recorder_lag_limit` | How far the records may fall behind before no new target is taken | None: trading continues | A duration |

### 5. Users extend a policy (owner)

A user extends `ExecutionPolicy` or `AccountPolicy` to change a default or to add a setting
of their own. A policy is recorded as a strategy is: the import path of its class and its
settings.

### 6. An account has a rebalance strategy (owner)

An account has a rebalance strategy, as a portfolio has. It says when and how money moves
between the account and its funds, toward the account's target.

| Portfolio | Account |
| --- | --- |
| Signal: a weight per asset | The account target: a weight per portfolio or asset |
| Rebalance strategy: when and how to trade toward the signal | Account rebalance strategy: when and how money moves toward the target |
| `ExecutionPolicy`: the strategy's choices | `AccountPolicy`: the strategy's choices |

The two kinds of fund of ADR 0062 are two strategies, not two fixed behaviours:

- **To the target at every sync:** "always 50% in this portfolio". It is today's behaviour.
- **Manual:** money moves only when a person records it. "Give this fund 10,000 and let it
  grow". Its moves are the capital allocations of ADR 0062.

A user writes another one as a class: back to the target every month, or only when a fund
drifts past a band. No ADR is needed for it. A strategy is recorded as a portfolio's is:
the import path of its class and its settings. It names its policy, as a portfolio's
strategy names its `ExecutionPolicy`.

### 7. `RebalanceStrategyBase` covers portfolios and accounts (owner)

`RebalanceStrategyBase` is the base of both. Today it also holds what only a portfolio
needs, so that part moves into a new class, `PortfolioRebalanceStrategy`:

- **`RebalanceStrategyBase`**, in core `msm`: what every rebalance strategy has.
- **`PortfolioRebalanceStrategy`**, in `msm_portfolios`, extends it with what a portfolio
  needs. `ImmediateSignal` and the bar strategies extend it.
- **`ManualAccount`**, in `msm`, extends the base directly.

The manual account strategy is the most basic rebalance strategy (owner): it has a target,
it acts only when a person records a move, and it uses no price. So the base holds what
`ManualAccount` needs, and everything else of today's class moves to
`PortfolioRebalanceStrategy`. The rule: what is about the target, the events and the policy
stays; what is about prices, fills, shares, bars, the ledger or the portfolio's calendar
moves.

| Today's `RebalanceStrategyBase` | Stays in the base | Moves to `PortfolioRebalanceStrategy` |
| --- | --- | --- |
| Fields | `timing_mode`, `target_succession`, `signal_lifetime`, `completion_tolerance` | `fill_rule`, `execution_model_instance`, `execution_cost_model_instances` |
| What it reads | `declared_dependencies`, `required_input_contract`, `dependency_window`, `dependency_seed_coordinates` | `session_events`, `own_execution_prices` |
| When it acts | `select_events`, `signal_expired`, `prepare_execution_context` | The earliest moment a calendar allows |
| What it does | `build_transitions`, as the contract only: target, events and previous state in, rows out | Its two implementations, at the next observed price and at the strategy's own bars; `bar_slices`, `bar_state`, `book_unit_value`, `simulate_recorded_fills` |
| Its policy | `fill_policy`, returning an `ExecutionPolicyBase` | |
| Its types | `RebalanceTarget`, `RebalanceInputContract`, the statuses | `AssetExecution`, `BarSlice`, `PriceConversion`, the price helpers |

Three things change in the base so that it fits both:

1. **`fill_policy` returns the policy base.** A portfolio strategy returns an
   `ExecutionPolicy`, `ManualAccount` an `AccountPolicy`.
2. **`build_transitions` takes no price.** `PortfolioRebalanceStrategy` adds the prices, the
   FX conversion and the book's unit to its own.
3. **Each side builds its target from its own source.** A portfolio from its signal's
   weights per asset, an account from its target's rows. `RebalanceTarget` stays: a key and
   a weight.

`PortfolioRebalanceStrategy` keeps two things apart (owner), so that the execution engine
can replace the second (Execution Engine ADR 0001, "A Runner Decides"):

| | What it is | Backtest | Live |
| --- | --- | --- | --- |
| Deciding | When a target may trade, the order fixed at the decision, the slice a bar allows, and how much may trade now under the cash rules | The strategy and its policy | The same strategy and policy |
| Filling | The price and the quantity each order gets, booked in the shares and the cash | The next observed price, or the bar | The venue |

Today the policy works out how much may trade and books the fill in one step. They have to be
separate before a strategy can trade live.

`ManualAccount` is then small:

| | `ManualAccount` |
| --- | --- |
| `timing_mode` | `manual` |
| Its target | The account target's rows: the portfolios the account follows |
| What it reads | The capital allocations a person recorded (ADR 0062) |
| When it acts | At each recorded allocation, and never by itself |
| What it does | Accepts or refuses the recorded move under its policy. It sizes nothing and reads no price |
| Its policy | `AccountPolicy` |

"To the target at every sync" is a second account strategy on the same base:
`SyncToTargetAccount` (owner). Whether the account strategies share a class of their own is
decided when it is written.

### 8. Accounts keep the boundary portfolios have (owner)

[ADR 0060](0060-producers-publish-markets-reads-only-its-own-tables.md) holds for accounts
as it does for portfolios: Markets reads and writes only its own tables, and data crosses
its boundary by publish or by keep. Nothing in this ADR makes Markets write in a provider's
tables or run a provider's code.

- **A strategy runs in the provider's process**, as `PortfolioRebalance` does. Markets
  never imports a provider's class. The shipped `ManualAccount` and `AccountPolicy` are
  Markets' own, so Markets is one more producer, as ADR 0060 says.
- **What a strategy produces is published.** Capital allocations, fund fills and fund
  holdings are sent to Markets operations and stored in Markets' tables (ADR 0062). They are
  Markets' rows from then on.
- **What a strategy needs to run is kept.** Its own state, its prices and its valuations
  stay in the provider's namespace. Markets holds nothing about them.
- **Markets checks only what its own rows can answer.** A publish operation applies the
  settings of the shipped `AccountPolicy` that need Markets' rows only: the currencies a
  portfolio allows, the account's available cash, a fund's cash. It applies them to every
  provider alike. A rule a user adds in their own class runs on the provider's side, before
  it publishes.
- **While an engine runs for an account, its funds are locked** (owner; Execution Engine ADR
  0001, decision 15). Markets' rows about those funds are then behind the engine's book. So
  Markets checks only what the book cannot change, and the engine applies the cash and unit
  settings against its book before the answer is published.
- **A policy reaches Markets as data.** An account's policy is recorded as the import path
  of its class and its settings. Markets reads the settings it knows and never loads the
  class.

Proposal: `AccountTable` gains `managed_by`, as `PortfolioTable` has, so that only the
application that manages an account publishes to it (ADR 0060, decision 4). The engine's lock
on an account belongs to that application. After a crash, that application or an
Organization admin releases it (owner).

### 9. A live fund trades under its portfolio's policy (owner)

A live fund trades by its portfolio strategy's `ExecutionPolicy`, the one its backtest ran.
Its account's policy can only restrict it, through the `fund_` settings: a live cash fund's
cash stays at or above zero even when its own policy allows less (ADR 0062, decision 13). A
fund has no policy of its own.

### 10. In a live account, the engine runs the account's strategy (owner)

The execution engine runs the account's rebalance strategy for the account it trades
(Execution Engine ADR 0001, "The Account's Strategy Moves Money"). It is in the provider's
process, with the book and the prices. An account with no engine needs nothing new: a manual
move is a Markets operation, and a fund at a share is sized by the provider's sync, as today.

### 11. A row may name its strategy, and the account's is the fallback (owner)

Each row of the account's target may name its own account strategy. A row that names none
uses the account's. An account that names none keeps today's behaviour: to the target at
every sync for a row that states a share, manual for a row that states none.

This is the owner's decision for direct asset rows (Execution Engine ADR 0001, decision 4),
applied here to portfolio rows. A strategy is named through `RebalanceStrategyMetadata`, as a
portfolio's is (Execution Engine ADR 0001, decision 5).

"To the target at every sync" records nothing new when it moves money. The sync's allocation
lines are its record, as today.

### 12. An account's strategy is named on its target snapshot (owner)

The account's strategy is named on the target snapshot, the `PositionSet`, and a row's on its
row, by `rebalance_strategy_uid`. The strategy names its policy, as a portfolio's does, so
the policy is recorded with it.

Neither is part of an identity. An account is not hashed. A change of strategy or of policy
is a new target snapshot with its date, so the account's history is kept.

### 13. A user's account strategy uses the two existing records (owner)

A user's own strategy records nothing new when it moves money. One that keeps funds at a
target is recorded by the sync's allocation lines, as today. One that gives or takes money
writes capital allocations (ADR 0062).

## What It Changes

- **ADR 0058.** `ExecutionPolicy` extends `ExecutionPolicyBase`. Its settings and defaults
  do not change. `RebalanceStrategyBase` moves to core `msm` as the base of both kinds of
  strategy, and the shipped portfolio strategies extend `PortfolioRebalanceStrategy`.
- **ADR 0062.** Decisions 8, 11, 12 and 13 stop being fixed rules. They are the defaults of
  `fund_cash_currencies` and `fund_cash_in`, `fund_cash_out`, `fund_portfolio_removed` and
  `fund_draws_on_account`. Its decision 15 is the default of `fund_income`. Its two kinds of
  fund (decision 1) and its rule that only a manual allocation changes a cash fund
  (decision 4) describe two strategies. Its records and its allowed currencies stand.
- **ADR 0060.** Unchanged, and now applied to accounts: their strategies run with the
  provider and publish to Markets.
- **ADR 0053.** Unchanged. Its allocation policies still say who owns the units that no
  record explains; `fund_unexplained_units` only says whether a cash fund takes part.
- **Execution Engine ADR 0001.** The engine runs the account's strategy, which replaces its
  `owner_size` hook. Its open choices become settings of `AccountPolicy`, and so does its
  lock: `fund_operations_while_locked`. A live fund trades under its portfolio's policy,
  restricted by its account's. While an account is locked, the engine applies the account
  policy's cash and unit settings against its book.

## Consequences

- An account's behaviour is read from its policy, not from an ADR.
- A new choice about accounts is a new setting with a default, not a question to settle
  once for everyone.
- Portfolios and accounts answer the same seven questions with the same settings.
- A new way to move an account's money is a new strategy class, not a new design.
- A strategy that works in weights needs the funds valued, and ms-markets reads no price
  (ADR 0054). It runs where the prices are, on the provider's side, as `PortfolioRebalance`
  does. The manual strategy needs no price.

## Not Decided Here

Nothing. The owner settled the last open points on 2026-11-23: the names, where an account
names its strategy and its policy (decision 12), and what a user's strategy records
(decision 13).

## Not Verified

- That moving the seven settings into a base leaves every portfolio's hash as it is.
- That the split of decision 7 holds in code. The class and its callers were read in
  full, and nothing was moved or run.
- That moving `RebalanceStrategyBase` leaves every portfolio's hash as it is. A strategy is
  hashed with the import path of its own class, which does not move.
