# 0062. Capital Given To A Virtual Fund

## Status

Amended by [ADR 0063](0063-a-policy-base-for-portfolios-and-accounts.md), proposed on
2026-11-23: decisions 8, 11, 12 and 13 are the defaults of the account policy's settings, not
fixed rules, and the two kinds of fund are two account rebalance strategies.

Amended by [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md),
decision 15, on 2026-11-23: while an engine runs for an account, the account's funds are
locked, and an operation on them is checked against the engine's book. See "An Account Locked
By A Running Engine".

Implemented together with Execution Engine ADR 0001 and ADR 0063, as one coordinated
implementation (owner, 2026-11-23). The three are kept in agreement: a change to one is
checked against the other two.

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23. Nothing in it is
implemented.

- The decisions marked (owner) were made by the owner:
  - On 2026-11-18 he described a fund that is given money and grows with its own result.
  - On 2026-11-19 he retired the amount
    ([ADR 0061](0061-retire-constant-notional-exposure.md)).
  - On 2026-11-23 he decided that each fund owns its cash
    ([Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md),
    decision 14). The same day he settled decisions 1, 3, 4, 5 and 8 to 13 and the rule in
    the [Ontology](#ontology). Decisions 8 to 10 came out of an analysis of accounts and
    portfolios that hold several currencies.
- This ADR is about cash funds only. A fund that is always a share of the account works exactly
  as today, and nothing here changes it.
- Everything not marked (owner) is a proposal. No question is left open for the owner.
- It would amend [ADR 0054](0054-account-exposure-and-sized-fund-targets.md) (what a portfolio
  row states, and how a cash fund is sized),
  [ADR 0053](0053-virtual-fund-allocation-routes-and-described-policies.md) and
  [ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md) (what a sync assigns to a
  cash fund), and answer open question 15 of Execution Engine ADR 0001.

## Ontology

| Term | Meaning |
| --- | --- |
| Owner | A fund, or the account itself, as in `AccountAllocationLinesStorage` |
| The account itself | What no fund owns: the account's own line |
| Share fund | A fund that is always a share of the account: its portfolio row states `weight_notional_exposure`. It works as today |
| Cash fund | A fund given cash. It grows or shrinks with its own result, and the account never rebalances it |
| Capital allocation | A dated record, made by a person, of cash or of units in kind allocated to a cash fund or moved away from it. Also called a manual allocation |
| Holdings allocation | What a sync assigns of the account's holdings to each owner (ADR 0053) |
| Fund fill | One owner's part of a fill or of an internal trade (Execution Engine ADR 0001, "Fund Fills") |
| Allowed currencies | The assets a portfolio may hold as cash, for example USD, EUR or BTC. Its build configuration declares them, and they are part of its identity |
| Valuation currency | The one allowed currency a portfolio is valued in: `valuation_asset_identifier` of its build configuration (ADR 0059). A cash fund's capital and result are in it |
| Available cash | The account itself's cash in one currency: the account's holding of it at its last sync, minus what its cash funds owned of it then, minus the cash allocated into them since, plus the cash moved away from them since |
| A cash fund's capital | What its capital allocations brought in minus what they took away, each valued when it moved |
| A cash fund's result | Its value, holdings plus cash, minus its capital |

**Only a manual allocation changes a cash fund (owner).** Once a fund is given cash, only a
manual allocation changes what it was given. Its own trades change what it holds, never what it
was given. No rule and no sync writes a capital allocation.

## Context

### What the owner asked for (owner)

The owner wants two different things from an account's funds:

- **Always a share of the account**, for example 50% in a portfolio, rebalanced to that share.
  This is today's mechanism, and automatic rebalancing runs on it. It stays as it is.
- **Money given to a fund**, for example 10,000 given to a portfolio today. That money belongs
  to the fund: it grows or shrinks with the portfolio, and the account is not forced to
  rebalance the fund when the portfolio goes up or down. This ADR is about this second kind.

### What happens today

- The account target states a share of the account's NAV per portfolio
  (`weight_notional_exposure`, ADR 0054). ADR 0061 retired the amount. So there is no way to
  give a fund money.
- At every sync the provider sizes each share into units, with that sync's prices and the
  account's NAV (ADR 0054, decision 3). `proportional_attribution` then gives each fund the
  account's units up to its sized target and never more. What no fund takes stays with the
  account itself (ADR 0053).
- A `VirtualFund` row holds its account and its portfolio only: no cash and no record of money
  moving in or out. A fund's holdings are what the last sync assigned it, and the next sync
  assigns them again from the account's units.
- `OrdersTS` and `TradesTS` name the account, not a fund.
- An account's cash is its holdings of currency assets (ADR 0051). The account row names no
  currency, and an account can hold several.
- A portfolio's valuation currency is on its build configuration (ADR 0059). No Markets table
  stores it: `PortfolioTable` has no currency column.
- A portfolio may hold assets priced in other currencies, converted with its FX source
  (ADR 0059). Its backtest book holds one cash figure in the valuation currency and converts
  for free. Its ledger holds a balance per currency but models no exchange. Nothing records
  which currencies a portfolio may hold, and its positions cannot tell in advance: that depends
  on its strategy.
- A trade records the currency it settled in (`TradesTS.settlement_asset_identifier`). A stock
  records no currency in any Markets table.

The portfolio backtest already keeps money in a portfolio. A portfolio starts with
`initial_nav` in cash. Its `RebalanceBook` holds shares and cash, and its orders are sized from
that book and limited by its cash ([ADR 0058](0058-trade-at-the-next-observed-price.md),
[ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md)). What it gains stays in it.
Execution Engine ADR 0001 decided that a live fund owns its cash the same way (decision 14), and
left open how cash reaches a fund and leaves it (question 15).

### The example

The account is worth 1,000,000. Prices are AAPL 200, MSFT 400, JNJ 150 and TSLA 250.

| Fund | Portfolio | Share | Value | Units |
| --- | --- | --- | --- | --- |
| A | 60% AAPL, 40% MSFT | 40% | 400,000 | 1,200 AAPL, 400 MSFT |
| B | 50% MSFT, 50% JNJ | 30% | 300,000 | 375 MSFT, 1,000 JNJ |

The account holds exactly these units, and also TSLA, which is in no fund, and cash.

AAPL rises 10%, to 220. Fund A's units are worth 424,000, and the account is worth 1,024,000.
At the next sync, fund B is sized at 30% of 1,024,000, which is 307,200: 384 MSFT and 1,024 JNJ
instead of 375 and 1,000. Its portfolio did not move, yet its target grew by 7,200, out of fund
A's gain.

That is right for a fund that must always be 30% of the account. It is wrong for a fund that
was given money to grow on its own.

## Decision

### 1. Two kinds of fund (owner)

- **A share fund** is always a share of the account: "always 50% in this portfolio". It is
  sized, allocated and rebalanced exactly as today (ADR 0054, ADR 0053). This ADR does not
  change it.
- **A cash fund** is given cash: "give this fund 10,000 and let it grow". Its value is its
  holdings plus its cash, and it grows or shrinks with its own result.

A portfolio row that states `weight_notional_exposure` is a share fund. A portfolio row that
states no share is a cash fund, and its money comes from manual allocations. An asset row does
not change.

### 2. A fund owns its cash (owner)

As Execution Engine ADR 0001 decided (decision 14): a fill, an internal trade and the fund's
share of a fee move the fund's cash, and the cash obeys the strategy's execution policy
(ADR 0058).

### 3. Capital moves as dated allocations (owner)

Every change in what a cash fund was given is a capital allocation: its date, and how much was
allocated to the fund or moved away from it. A capital allocation is not a trade. Nothing is
bought or sold, and it has no price.

| Column | Meaning |
| --- | --- |
| `time_index` | When it moves |
| `allocation_identifier` | Its key, so writing it again changes nothing |
| `account_uid`, `virtual_fund_uid` | The account and the fund |
| `asset_identifier` | The cash currency asset, or the asset of units moved in kind |
| `quantity`, `direction` | How much, and the side: into the fund, or away from it |
| `metadata_json` | Anything else the writer keeps |

- **An allocation is a fact.** It is never changed or deleted; a correction is a new allocation.
- **A move between cash funds** is two allocations at the same time: one away from one fund,
  one into the other.
- **A cash fund's capital and result** need prices, so the provider computes them (ADR 0054).

### 4. Only a manual allocation changes a cash fund (owner)

See the rule in the [Ontology](#ontology). A sync never resizes a cash fund, and never gives it
units that no record explains (decision 5).

### 5. A sync starts from each cash fund's own record

At a sync, each cash fund first keeps what its own record explains:

1. **Its units:** its holdings at the previous sync, plus its allocations in kind and its fund
   fills since then.
2. **Its cash, in each currency:** its cash at the previous sync, plus its cash allocations,
   plus what its fills sold, minus what they bought and its share of the fees.

Then:

- **Share funds** are sized and allocated as today.
- **Units that no record explains** go through the allocation policy among share funds only,
  as today. A cash fund gets none, and what is left stays with the account itself (owner). For
  example, 200 MSFT come into the account from outside, and share fund A asks for 10 more MSFT
  than it holds. Fund A gets 10, cash fund B gets none, and 190 stay with the account itself.
- **When the account holds less** than the cash funds' records add up to, they keep what their
  records say, and the account's own line shows the shortfall as a negative (owner, Execution
  Engine ADR 0001, "Fund Holdings At A Sync"). The same holds for cash, currency by currency.

A cash fund's cash is stored at the sync like its other holdings: a `VirtualFundHoldingsStorage`
row per currency asset.

### 6. A cash fund is sized from its own value

The provider sizes a cash fund's target units from the fund's own value, its holdings at the
provider's prices plus its cash, the way the backtest sizes from its book. A share fund is sized
from its share of the account, as today. In the engine, the account's rebalance strategy
gives each fund its size (Execution Engine ADR 0001, "The Account's Strategy Moves Money").
`sized_targets` keeps its shape (ADR 0054).

### 7. Whoever trades for a cash fund writes its fund fills

A cash fund's record must know which fills were its own. The fund fills of Execution Engine ADR
0001 ("Fund Fills": one row per owner and fill, with the price and the owner's share of the fee)
become a Markets record. Whoever trades for the fund writes them: the engine's recorder, or a
provider that trades for its funds without the engine. A trade that no fund fill claims is not
the cash fund's. A fund fill also records the currency it settled in, as `TradesTS` does, so it
moves the fund's cash in that currency.

### 8. Cash into a fund is in an allowed currency, and needs available cash in it (owner)

Cash allocated into a fund must be in one of the allowed currencies of the fund's portfolio, and
the account must have that much available cash in that currency. Each currency is checked on
its own: available EUR does not cover USD. ms-markets compares quantities of one asset at a
time, so it needs no price (ADR 0054).

The owner first allowed the valuation currency only. After the currency analysis of the same
day he widened it to the allowed currencies. Otherwise a portfolio that holds foreign assets
would have to convert every time it is given money, even when the account already holds the
currency.

### 9. A portfolio declares its allowed currencies (owner)

A portfolio's build configuration declares the assets it may hold as cash, next to its valuation
currency. They cannot be read off its positions in advance, because they depend on its strategy.

- **The list is part of the portfolio's identity.** Allowing another currency makes a new
  portfolio, as changing the valuation currency does (ADR 0059).
- **Registering the portfolio records the list in Markets**: a many-to-many link from the
  portfolio to each asset, with a foreign key to `AssetTable`. A currency here is any asset held
  as cash, for example USD, EUR or BTC.
- **The valuation currency is one of them.** `PortfolioTable` records it too. Proposal: a column
  whose key into the link table makes it one of the allowed currencies.

### 10. Converting currencies is the rebalance strategy's (owner)

Converting between a fund's currencies is part of the portfolio's rebalance strategy, and is
designed later. So is whether the backtest holds cash per currency. Until then the backtest
converts for free, as today, and differs from a live fund that holds several currencies.

### 11. Cash moved away from a cash fund is limited to its cash (owner)

Moving more cash away from a cash fund than it holds in that currency is refused. Its strategy
sells first, and the cash is moved once the fund holds it. To avoid a sale, units move away in
kind instead.

### 12. A cash fund keeps its holdings when its portfolio leaves the target (owner)

When the account's target no longer names a cash fund's portfolio, or the portfolio is retired,
the target change is accepted. The fund keeps what it holds, units and cash, and stops
rebalancing. Only a manual allocation empties it.

### 13. A live cash fund's cash never goes below zero (owner)

A live cash fund buys only with the cash it holds in that currency, whatever its execution
policy's `negative_cash` allows (ADR 0059). With 10,000 USD and a strategy that wants 25,000
of MSFT, it buys 10,000. A cash fund never borrows the account's cash.

## Operations

Every operation is one transaction through the Markets API: the checks and the write together,
so two requests can never spend the same cash. A request with several operations applies each
one that passes and lists the others with the reason, like every bulk call. A move between
funds is one operation. This is how an account with no engine running works. A locked account
is described below.

| Operation | What it records | Refused when |
| --- | --- | --- |
| Allocate cash to a cash fund | One allocation into the fund | The fund is not a cash fund of the account, or its portfolio is retired; the cash is not one of the portfolio's allowed currencies; the account's available cash in that currency is less (decision 8) |
| Move cash away from a cash fund | One allocation away from the fund | The fund's cash in that currency is less (decision 11) |
| Move cash from one cash fund to another | Two allocations at the same time | The first fund's cash is less; the cash is not one of the allowed currencies of the second fund's portfolio |
| Allocate units in kind to a cash fund | One allocation in kind | The account itself holds fewer of those units |
| Move units in kind away from a cash fund | One allocation in kind | The fund holds fewer of those units |

A person makes every operation. A quantity is positive in every operation, and the side says
which way it moves. An account delete (ADR 0050) deletes its capital allocations and fund fills
with the rest of its history.

### An Account Locked By A Running Engine

While an execution engine runs for an account, the account's funds are locked (owner,
2026-11-23; Execution Engine ADR 0001, decision 15). The engine trades faster than any call to
Markets, so Markets' rows about those funds are behind the engine's book. A check against
them can accept what a fund no longer has.

In the worked example, fund B has 50,000 in cash on day 2. Its engine spends it, and the
recorder has not written those fills yet. A person asks to move 50,000 away from fund B.
Markets' rows still show the cash. Checked against them, the move is accepted and fund B's
cash goes to -50,000, which decision 13 forbids.

So an operation on a locked account passes the lock. How it passes is a proposal:

1. Markets checks what the engine's book cannot change: the fund is a cash fund of the
   account, its portfolio is not retired, and the cash is one of the portfolio's allowed
   currencies. It keeps the operation as waiting.
2. The engine checks the cash and the units against its book, under the account's policy.
   These are the checks of decisions 8 and 11.
3. The engine's recorder publishes the answer, after the fills that came before it. Markets
   writes the capital allocation, or marks the operation refused with its reason.

- **A capital allocation is still a fact.** An operation becomes one only when the engine
  accepts it. A waiting operation is a separate row.
- **Waiting or refusing is a setting of the account's policy** (ADR 0063, decision 4). The
  proposed default is to wait for the engine.
- **A sync of a locked account** is written by the engine's recorder only.
- **With no engine running** nothing changes: the table above holds as written.

### Records

| Record | Change |
| --- | --- |
| Capital allocations | New, time-indexed (decision 3); its keys into the account and the fund cascade on delete |
| Waiting operations | New: an operation on a locked account, kept until the engine answers |
| Fund fills | New, as Execution Engine ADR 0001 proposes, with the currency each settled in (decision 7) |
| `VirtualFundHoldingsStorage` | Also holds a cash fund's cash, as a row per currency asset |
| `TargetPositionsStorage` | A portfolio row states a share, or nothing for a cash fund; an asset row is unchanged |
| A portfolio's allowed currencies | New: a many-to-many link from a portfolio to assets (decision 9) |
| `PortfolioTable` | Records the portfolio's valuation currency, one of its allowed currencies (decision 9) |
| `VirtualFund`, `OrdersTS`, `TradesTS` | Unchanged |

## Worked Example

Fund A is a share fund at 40% of the account, as today. Fund B is a cash fund; its portfolio is
valued in USD and allows only USD. TSLA is a direct row at 5%.

**Day 0.** The account holds fund A's units (1,200 AAPL and 400 MSFT), 200 TSLA and 550,000
USD. The owner allocates 300,000 to fund B, accepted because the account has 550,000 USD
available. Fund B buys its portfolio. Fees are left out.

| Owner | AAPL | MSFT | JNJ | TSLA | Cash | Value |
| --- | --- | --- | --- | --- | --- | --- |
| Fund A | 1,200 | 400 | | | | 400,000 |
| Fund B | | 375 | 1,000 | | 0 | 300,000 |
| The account itself | | | | 200 | 250,000 | 300,000 |
| Account | 1,200 | 775 | 1,000 | 200 | 250,000 | 1,000,000 |

**Day 1.** MSFT rises 10%, to 440. Fund B is worth 315,000: its capital is 300,000 and its
result +15,000. It keeps all of it, and nothing is recorded for it. Fund A is resized as today.

**Day 2.** The owner allocates 50,000 more to fund B, accepted because the account has 250,000
USD available. Fund B's cash is 50,000 and its capital 350,000. Its strategy invests the cash at
its next rebalance, sized from its own value.

**Day 3.** The owner asks to allocate 250,000 more to fund B. The account has 200,000 USD
available, so the allocation is refused. Had portfolio B allowed only EUR, the allocation of
day 2 would have been refused too: the account holds no EUR. Had it allowed EUR and USD, the USD
of day 2 would have been accepted.

**Day 4.** The owner asks to move 60,000 away from fund B, which has invested its cash and holds
none. The move is refused (decision 11). Moving 100 MSFT away in kind is accepted.

| Date | What moved |
| --- | --- |
| Day 0 | 300,000 USD into fund B |
| Day 2 | 50,000 USD into fund B |
| Day 4 | 100 MSFT away from fund B |

## What It Changes

- **ADR 0054.** Decision 1: a portfolio row states a share for a share fund, or nothing for a
  cash fund. Decision 3: a cash fund is sized from its own value.
- **ADR 0053 and ADR 0029.** A sync starts from each cash fund's own record. A cash fund gets
  none of the units that no record explains. Share funds are allocated as today.
- **ADR 0050.** An account delete also deletes the account's capital allocations and fund fills.
- **ADR 0059.** A build configuration also declares its allowed currencies, and the valuation
  currency is one of them. Markets records both.
- **ADR 0061.** It left open whether a share of the account stays a rule applied at every sync.
  It does, for share funds, unchanged (owner).
- **Execution Engine ADR 0001.** It answers question 15. A fund's size follows its kind, and
  the account's strategy gives it. Fund fills become a Markets record that any trader writes.
  Its rule for units that no fill explains applies to share funds only (owner). Its lock
  (decision 15) says how an operation is checked while an engine runs.

## Consequences

- A cash fund's value and result are its own. Only a manual allocation changes what it was
  given.
- A share fund behaves exactly as today.
- Target writers do not break: a share fund's row is today's row. A cash fund is a portfolio
  row with no share, plus manual allocations.
- Trading for a cash fund means writing its fund fills.
- Available cash is as fresh as the account's last sync. A trade of the account itself after
  it is not seen until the next holdings snapshot, so a provider that trades outside the funds
  syncs before it allocates. For an account locked by an engine, the engine's book answers
  instead.
- Every fund today is a share fund and stays one. There are no real portfolios yet, so nothing
  is converted.
- A strategy whose execution policy allows negative cash buys less live, as a cash fund, than
  in its backtest (decision 13).

## Not Decided Here

- Whether a portfolio row names its kind explicitly, instead of by stating a share or not.
  ADR 0063 (decision 11) proposes that a row may name its strategy.
- Whether cash that the account's own target keeps, a direct row on a currency (ADR 0053),
  limits its available cash.
- Moving a fund from one kind to the other.
- Dividends and interest that the account receives for a cash fund's holdings, and how the
  account's fees are shared among its funds.
- Whether ms-markets stores a cash fund's value or result series, which need prices (ADR 0054).
- Whether the cash currency asset gets an allocation line with a target.
- How Command Center shows a cash fund's capital, cash and result.

## Not Verified

- That `VirtualFundHoldingsStorage` and the allocation code take a row of the cash currency
  asset without change.
- That a fund's cash computed from its allocations and fills adds up to the account's cash
  holding when the venue books fees or interest that no fill shows.
