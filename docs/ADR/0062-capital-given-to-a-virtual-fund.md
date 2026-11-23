# 0062. Capital Given To A Virtual Fund

## Status

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23. Nothing in it is
implemented.

- The decisions marked (owner) were made by the owner:
  - On 2026-11-18 he described a fund that is given money and grows with its own result.
  - On 2026-11-19 he retired the amount
    ([ADR 0061](0061-retire-constant-notional-exposure.md)).
  - On 2026-11-23 he decided that each fund owns its cash
    ([Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md),
    decision 14). The same day he settled the open questions of this draft: decisions 1, 3, 4
    and 5, and the rule in the [Ontology](#ontology).
- Everything not marked (owner) is a proposal.
- It would amend [ADR 0054](0054-account-exposure-and-sized-fund-targets.md) (what a portfolio
  row states and how a fund is sized),
  [ADR 0053](0053-virtual-fund-allocation-routes-and-described-policies.md) and
  [ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md) (what a sync assigns),
  and answer open question 15 of Execution Engine ADR 0001.

## Ontology

| Term | Meaning |
| --- | --- |
| Owner | A fund, or the account itself, as in `AccountAllocationLinesStorage` |
| The account itself | What no fund owns: the account's own line |
| Share fund | A fund that is always a share of the account: its portfolio row states `weight_notional_exposure`. Every sync resizes it to that share |
| Cash fund | A fund given cash. It grows or shrinks with its own result, and the account never rebalances it |
| Capital allocation | A dated record of cash, or of units in kind, allocated to a fund or moved away from it |
| Manual allocation | A capital allocation that a person makes |
| Rule allocation | A capital allocation that the share rule makes: a share fund's resize, or units a sync gives it that no record explains |
| Holdings allocation | What a sync assigns of the account's holdings to each owner (ADR 0053) |
| Fund fill | One owner's part of a fill or of an internal trade (Execution Engine ADR 0001, "Fund Fills") |
| A fund's capital | What its capital allocations brought in minus what they took away, each valued when it moved |
| A fund's result | Its value, holdings plus cash, minus its capital |

**Only a manual allocation changes a cash fund (owner).** Once a fund is given cash, only a
manual allocation changes what it was given. Its own trades change what it holds, never what it
was given. No rule and no sync writes a capital allocation for a cash fund.

## Context

### What the owner asked for (owner)

The owner wants two different things from an account's funds:

- **Always a share of the account**, for example 50% in a portfolio, rebalanced to that share.
  This is today's mechanism, and automatic rebalancing runs on it.
- **Money given to a fund**, for example 10,000 given to a portfolio today. That money belongs
  to the fund: it grows or shrinks with the portfolio, and the account is not forced to
  rebalance the fund when the portfolio goes up or down.

### What happens today

- The account target states a share of the account's NAV per portfolio
  (`weight_notional_exposure`, ADR 0054). ADR 0061 retired the amount. So every fund is a share
  fund, and there is no way to give a fund money.
- At every sync the provider sizes each share into units, with that sync's prices and the
  account's NAV (ADR 0054, decision 3). `proportional_attribution` then gives each fund the
  account's units up to its sized target and never more. What no fund takes stays with the
  account itself (ADR 0053).
- A `VirtualFund` row holds its account and its portfolio only: no cash and no record of money
  moving in or out. A fund's holdings are what the last sync assigned it, and the next sync
  assigns them again from the account's units.
- `OrdersTS` and `TradesTS` name the account, not a fund.
- An account's cash is a holding of its cash currency asset (ADR 0051).

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
At the next sync:

- Fund A is sized at 40% of 1,024,000, which is 409,600: 1,117 AAPL and 410 MSFT. The sync
  assigns it 1,117 of its 1,200 AAPL. The other 83, about 18,260, go to the account itself
  without any trade.
- Fund B is sized at 30% of 1,024,000, which is 307,200: 384 MSFT and 1,024 JNJ instead of 375
  and 1,000. Its portfolio did not move, yet its target grew by 7,200, out of fund A's gain.

That is right for a fund that must always be 40% or 30% of the account. It is wrong for a fund
that was given money to grow on its own.

## Decision

### 1. Two kinds of fund (owner)

- **A share fund** is always a share of the account: "always 50% in this portfolio". Every sync
  sizes it from the account's value, and it is rebalanced to that share. This is today's
  mechanism, and it stays.
- **A cash fund** is given cash: "give this fund 10,000 and let it grow". Its value is its
  holdings plus its cash, and it grows or shrinks with its own result.

A portfolio row that states `weight_notional_exposure` is a share fund. A portfolio row that
states no share is a cash fund, and its money comes from manual allocations. An asset row does
not change.

### 2. A fund owns its cash (owner)

As Execution Engine ADR 0001 decided (decision 14): a fill, an internal trade and the fund's
share of a fee move the fund's cash, and the cash obeys the strategy's execution policy
(ADR 0058). This holds for both kinds of fund.

### 3. Capital moves as dated allocations (owner)

Every change in what a fund was given is a capital allocation: its date, and how much was
allocated to the fund or moved away from it. A capital allocation is not a trade. Nothing is
bought or sold, and it has no price.

| Column | Meaning |
| --- | --- |
| `time_index` | When it moves |
| `allocation_identifier` | Its key, so writing it again changes nothing |
| `account_uid`, `virtual_fund_uid` | The account and the fund |
| `asset_identifier` | The cash currency asset, or the asset of units moved in kind |
| `quantity`, `direction` | How much, and the side: into the fund, or away from it |
| `source` | `manual`, or `rule` |
| `metadata_json` | Anything else the writer keeps |

- **An allocation is a fact.** It is never changed or deleted; a correction is a new allocation.
- **A move between funds** is two allocations at the same time: one away from fund A, one into
  fund B.
- **A fund's capital and result** need prices, so the provider computes them (ADR 0054).

### 4. Only a manual allocation changes a cash fund (owner)

See the rule in the [Ontology](#ontology). A cash fund's capital allocations are all manual. A
sync never resizes it, and never gives it units that no record explains (decision 5).

### 5. A sync starts from each owner's own record

At a sync, each fund first keeps what its own record explains:

1. **Its units:** its holdings at the previous sync, plus its allocations in kind and its fund
   fills since then.
2. **Its cash:** its cash at the previous sync, plus its cash allocations, plus what its fills
   sold, minus what they bought and its share of the fees.

Then:

- **A share fund is resized** to its share of the account. The provider sizes it, as today, and
  records what the resize moves as a rule allocation.
- **Units that no record explains** go only to share funds that still want more, through the
  allocation policy. Each such assignment is recorded as a rule allocation in kind (owner). A
  cash fund gets none, and what is left stays with the account itself (owner). For example,
  200 MSFT come into the account from outside, and share fund A asks for 10 more MSFT than it
  holds. Fund A gets 10, cash fund B gets none, and 190 stay with the account itself.
- **When the account holds less** than the funds' records add up to, the funds keep what their
  records say, and the account's own line shows the shortfall as a negative (owner, Execution
  Engine ADR 0001, "Fund Holdings At A Sync").

A fund's cash is stored at the sync like its other holdings: a `VirtualFundHoldingsStorage` row
of the cash currency asset.

### 6. A cash fund is sized from its own value

The provider sizes a cash fund's target units from the fund's own value, its holdings at the
provider's prices plus its cash, the way the backtest sizes from its book. A share fund is sized
from its share of the account, as today. The `owner_size` hook of Execution Engine ADR 0001
defaults to the one or the other. `sized_targets` keeps its shape (ADR 0054).

### 7. Whoever trades for a fund writes its fund fills

A fund's record must know which fills were its own. The fund fills of Execution Engine ADR 0001
("Fund Fills": one row per owner and fill, with the price and the owner's share of the fee)
become a Markets record. Whoever trades for a fund writes them: the engine's recorder, or a
provider that trades for its funds without the engine. A trade that no fund fill claims belongs
to the account itself.

### Records

| Record | Change |
| --- | --- |
| Capital allocations | New, time-indexed (decision 3) |
| Fund fills | New, as Execution Engine ADR 0001 proposes (decision 7) |
| `VirtualFundHoldingsStorage` | Also holds each fund's cash, as a row of the cash currency asset |
| `TargetPositionsStorage` | A portfolio row states a share, or nothing for a cash fund; an asset row is unchanged |
| `VirtualFund`, `OrdersTS`, `TradesTS` | Unchanged |

## Worked Example

Fund A is a share fund at 40% of the account. Fund B is a cash fund. TSLA is a direct row at 5%.

**Day 0.** The account holds 1,000,000 in cash, USD. The first sync resizes fund A to 40%: a
rule allocation of 400,000 into A. The owner allocates 300,000 to fund B: a manual allocation.
The funds buy their portfolios, and the account buys 200 TSLA for its own row. Fees are left
out.

| Owner | AAPL | MSFT | JNJ | TSLA | Cash | Value |
| --- | --- | --- | --- | --- | --- | --- |
| Fund A | 1,200 | 400 | | | 0 | 400,000 |
| Fund B | | 375 | 1,000 | | 0 | 300,000 |
| The account itself | | | | 200 | 250,000 | 300,000 |
| Account | 1,200 | 775 | 1,000 | 200 | 250,000 | 1,000,000 |

**Day 1.** MSFT rises 10%, to 440. Both funds hold it. The account is worth 1,031,000.

| Owner | Value before the sync | Resize | Value after | Capital | Result |
| --- | --- | --- | --- | --- | --- |
| Fund A, share | 416,000 | 3,600 away | 412,400 | 396,400 | +16,000 |
| Fund B, cash | 315,000 | None | 315,000 | 300,000 | +15,000 |
| The account itself | 300,000 | 3,600 in | 303,600 | | |

The sync resizes fund A to 40% of 1,031,000. Fund B keeps all of its gain, and nothing is
recorded for it. Both funds keep their result: a resize moves capital, not result.

**Day 2.** The owner allocates 50,000 more to fund B: a manual allocation. Fund B's cash is
50,000 and its capital 350,000. Its strategy invests the cash at its next rebalance, sized from
its own value. The account itself keeps 253,600.

| Date | Fund | Source | What moved |
| --- | --- | --- | --- |
| Day 0 | A | `rule` | 400,000 USD in |
| Day 0 | B | `manual` | 300,000 USD in |
| Day 1 | A | `rule` | 3,600 of value away (how, see "Not Decided Here") |
| Day 2 | B | `manual` | 50,000 USD in |

## What It Changes

- **ADR 0054.** Decision 1: a portfolio row states a share for a share fund, or nothing for a
  cash fund. Decision 3: a cash fund is sized from its own value.
- **ADR 0053 and ADR 0029.** A sync starts from each owner's own record. The policy runs only on
  units that no record explains, and only for share funds.
- **ADR 0061.** It left open whether a share of the account stays a rule applied at every sync.
  It does, for share funds (owner).
- **Execution Engine ADR 0001.** It answers question 15. The `owner_size` default depends on the
  kind of fund. Fund fills become a Markets record that any trader writes. Its rule for units
  that no fill explains now applies to share funds only (owner).

## Consequences

- A cash fund's value and result are its own. Only a manual allocation changes what it was
  given.
- A share fund behaves as today, and every resize is now a recorded rule allocation.
- Target writers do not break: a share fund's row is today's row. A cash fund is a portfolio
  row with no share, plus manual allocations.
- Trading for a fund means writing its fund fills. A trade with no fund fill stays the
  account's own, and no fund's cash changes.
- Every fund today is a share fund and stays one. There are no real portfolios yet, so nothing
  is converted.

## Not Decided Here

- How a share fund's resize moves: as cash only, with the fund's strategy then trading back to
  its weights; or the units it has too many of moving away in kind, as today.
- Whether a portfolio row names its kind explicitly, instead of by stating a share or not.
- Moving a fund from one kind to the other.
- A manual allocation away from a cash fund that is larger than the fund's cash: refused, or the
  fund sells first, and who decides what it sells.
- The currency of a fund's cash when the portfolio's currency (ADR 0059) is not the account's
  cash currency.
- Dividends and interest that the account receives for a fund's holdings, and how the account's
  fees are shared among its funds.
- Whether ms-markets stores a fund's value or result series, which need prices (ADR 0054).
- Whether the cash currency asset gets an allocation line with a target.
- How Command Center shows a fund's kind, capital, cash and result.

## Not Verified

- That `VirtualFundHoldingsStorage` and the allocation code take a row of the cash currency
  asset without change.
- That a fund's cash computed from its allocations and fills adds up to the account's cash
  holding when the venue books fees or interest that no fill shows.
