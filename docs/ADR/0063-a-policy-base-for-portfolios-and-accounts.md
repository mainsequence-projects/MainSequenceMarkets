# 0063. Policies And Rebalance Strategies For Portfolios And Accounts

## Status

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23. Nothing in it is
implemented.

- The decisions marked (owner) were made by the owner on 2026-11-23. Everything else is a
  proposal, the names included.
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
base, for the account's own trading, and adds the account's own. The settings below, their
names and their other values are a proposal. Each default is what ADR 0062 decided, except
the last, which comes from the engine's lock (Execution Engine ADR 0001, decision 15).

| Setting | What it chooses | Default | Other values |
| --- | --- | --- | --- |
| `fund_cash_currencies` | Which currencies cash may be given to a fund in | `portfolio_allowed`: any currency the fund's portfolio allows | `valuation_only` |
| `fund_cash_in` | Whether giving cash needs available cash in the account | `needs_available_cash` | `unchecked` |
| `fund_cash_out` | Taking out more cash than a fund holds | `refuse` | `sell_first` |
| `fund_draws_on_account` | Whether a fund's cash may go below zero on the account's cash | `not_allowed` | `up_to_limit`, with a limit |
| `fund_portfolio_removed` | A cash fund whose portfolio leaves the target | `keep_holdings` | `return_to_account` |
| `fund_unexplained_units` | Whether a cash fund gets units that no record explains | `none` | `through_allocation_policy` |
| `fund_operations_while_locked` | An operation on a fund while the account's engine runs | `wait_for_engine`: the engine answers from its book | `refuse` |

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

`ManualAccount` is then small:

| | `ManualAccount` |
| --- | --- |
| `timing_mode` | `manual` |
| Its target | The account target's rows: the portfolios the account follows |
| What it reads | The capital allocations a person recorded (ADR 0062) |
| When it acts | At each recorded allocation, and never by itself |
| What it does | Accepts or refuses the recorded move under its policy. It sizes nothing and reads no price |
| Its policy | `AccountPolicy` |

"To the target at every sync" is a second account strategy on the same base. Whether the
account strategies share a class of their own is decided when the second one is written.

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
on an account belongs to that application.

## What It Changes

- **ADR 0058.** `ExecutionPolicy` extends `ExecutionPolicyBase`. Its settings and defaults
  do not change. `RebalanceStrategyBase` moves to core `msm` as the base of both kinds of
  strategy, and the shipped portfolio strategies extend `PortfolioRebalanceStrategy`.
- **ADR 0062.** Decisions 8, 11, 12 and 13 stop being fixed rules. They are the defaults of
  `fund_cash_currencies` and `fund_cash_in`, `fund_cash_out`, `fund_portfolio_removed` and
  `fund_draws_on_account`. Its two kinds of fund (decision 1) and its rule that only a
  manual allocation changes a cash fund (decision 4) describe two strategies. Its records
  and its allowed currencies stand.
- **ADR 0060.** Unchanged, and now applied to accounts: their strategies run with the
  provider and publish to Markets.
- **ADR 0053.** Unchanged. Its allocation policies still say who owns the units that no
  record explains; `fund_unexplained_units` only says whether a cash fund takes part.
- **Execution Engine ADR 0001.** Its lock gets a setting of `AccountPolicy`:
  `fund_operations_while_locked`. While an account is locked, the engine applies the account
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

- The names `ExecutionPolicyBase`, `AccountPolicy`, `PortfolioRebalanceStrategy` and
  `ManualAccount`, the name of the second account strategy, and the names and values of the
  account's settings.
- The class that runs an account's strategy in the provider's process, as
  `PortfolioRebalance` runs a portfolio's.
- Whether an account has one strategy, or each row of its target names its own. An account
  with one fund at a fixed share and one run by hand needs one or the other.
- What a strategy other than the manual one records when it moves money.
- Whether an account's strategy is registered as a portfolio's is
  (`RebalanceStrategyMetadata`).
- Where an account names its policy, and whether the policy is part of an identity.
- Whether a fund may have a policy of its own, different from its account's.
- Which policy applies to a live fund when both have a say: its portfolio's
  `ExecutionPolicy`, or its account's policy.
- The `calendar_gating` value `portfolio_calendar` for an account, which has no portfolio
  calendar.

## Not Verified

- That moving the seven settings into a base leaves every portfolio's hash as it is.
- That the split of decision 7 holds in code. The class and its callers were read in
  full, and nothing was moved or run.
- That moving `RebalanceStrategyBase` leaves every portfolio's hash as it is. A strategy is
  hashed with the import path of its own class, which does not move.
