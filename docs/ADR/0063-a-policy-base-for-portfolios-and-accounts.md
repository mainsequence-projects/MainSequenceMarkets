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
names and their other values are a proposal. Each default is what ADR 0062 decided.

| Setting | What it chooses | Default | Other values |
| --- | --- | --- | --- |
| `fund_cash_currencies` | Which currencies cash may be given to a fund in | `portfolio_allowed`: any currency the fund's portfolio allows | `valuation_only` |
| `fund_cash_in` | Whether giving cash needs available cash in the account | `needs_available_cash` | `unchecked` |
| `fund_cash_out` | Taking out more cash than a fund holds | `refuse` | `sell_first` |
| `fund_draws_on_account` | Whether a fund's cash may go below zero on the account's cash | `not_allowed` | `up_to_limit`, with a limit |
| `fund_portfolio_removed` | A cash fund whose portfolio leaves the target | `keep_holdings` | `return_to_account` |
| `fund_unexplained_units` | Whether a cash fund gets units that no record explains | `none` | `through_allocation_policy` |

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

The account strategy has its own base, here called `AccountRebalanceStrategyBase`. It does
not extend `RebalanceStrategyBase`, which requires every fill to use an observed price: a
move of money between an account and its fund is not a trade and has no price.

## What It Changes

- **ADR 0058.** `ExecutionPolicy` extends `ExecutionPolicyBase`. Its settings and defaults
  do not change.
- **ADR 0062.** Decisions 8, 11, 12 and 13 stop being fixed rules. They are the defaults of
  `fund_cash_currencies` and `fund_cash_in`, `fund_cash_out`, `fund_portfolio_removed` and
  `fund_draws_on_account`. Its two kinds of fund (decision 1) and its rule that only a
  manual allocation changes a cash fund (decision 4) describe two strategies. Its records
  and its allowed currencies stand.
- **ADR 0053.** Unchanged. Its allocation policies still say who owns the units that no
  record explains; `fund_unexplained_units` only says whether a cash fund takes part.

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

- The names `ExecutionPolicyBase`, `AccountPolicy` and `AccountRebalanceStrategyBase`, the
  names of the two strategies, and the names and values of the account's settings.
- Whether an account has one strategy, or each row of its target names its own. An account
  with one fund at a fixed share and one run by hand needs one or the other.
- What a strategy other than the manual one records when it moves money.
- Whether the two strategy bases share a base of their own.
- Whether an account's strategy is registered as a portfolio's is
  (`RebalanceStrategyMetadata`).
- Where an account names its policy, and whether the policy is part of an identity.
- Whether a fund may have a policy of its own, different from its account's.
- Which policy applies to a live fund when both have a say: its portfolio's
  `ExecutionPolicy`, or its account's policy.
- Where a user's own policy class runs. The hosted Markets API can apply settings; it cannot
  import a provider's class.
- The `calendar_gating` value `portfolio_calendar` for an account, which has no portfolio
  calendar.

## Not Verified

- That moving the seven settings into a base leaves every portfolio's hash as it is.
- What `RebalanceStrategyBase` holds beyond its fields and hooks. Only those were read, so
  that the account's base cannot extend it is a reading, not a finding.
