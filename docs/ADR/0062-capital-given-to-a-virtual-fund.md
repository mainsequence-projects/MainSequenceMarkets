# 0062. Capital Given To A Virtual Fund

## Status

Proposed (2026-11-23). Drafted at the owner's request on 2026-11-23. Nothing in it is
implemented.

- The decisions marked (owner) were made by the owner: what the money given to a fund should do
  (2026-11-18), the retirement of the amount
  ([ADR 0061](0061-retire-constant-notional-exposure.md), 2026-11-19), and that each fund owns
  its cash
  ([Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md),
  decision 14, 2026-11-23). Everything else is a proposal.
- Three questions shape it and are not decided; see [Open Questions](#open-questions). The
  draft follows my recommendation for each.
- It would amend [ADR 0054](0054-account-exposure-and-sized-fund-targets.md) (what a portfolio
  row states and how a fund is sized),
  [ADR 0053](0053-virtual-fund-allocation-routes-and-described-policies.md) and
  [ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md) (what a sync assigns),
  and answer open question 15 of Execution Engine ADR 0001.

## Context

### What the owner asked for (owner)

On 2026-11-18 the owner described the money an account gives a portfolio: 10,000 given to a
portfolio today belongs to that portfolio. It grows or shrinks with the portfolio, and the
account is not forced to rebalance the fund when the portfolio goes up or down. He said this
should be the intention in most cases.

### What happens today

- The account target states a share of the account's NAV per portfolio
  (`weight_notional_exposure`, ADR 0054). ADR 0061 retired the amount.
- At every sync the provider sizes each share into units, with that sync's prices and the
  account's NAV (ADR 0054, decision 3). `proportional_attribution` then gives each fund the
  account's units up to its sized target and never more. What no fund takes stays with the
  account itself (ADR 0053).
- So a fund's size follows the account, not its own result. Part of a fund's gain goes to the
  other funds and to the account, and part of its loss is refilled from them, without anyone
  deciding it. The fund's value says little about how its portfolio did.
- A `VirtualFund` row holds its account and its portfolio only: no amount, no cash and no record
  of money moving in or out. A fund's holdings are what the last sync assigned it, and the next
  sync assigns them again from the account's units.
- `OrdersTS` and `TradesTS` name the account, not a fund.
- An account's cash is a holding of its cash currency asset (ADR 0051).

The portfolio backtest already works the way the owner describes. A portfolio starts with
`initial_nav` in cash. Its `RebalanceBook` holds shares and cash, and its orders are sized from
that book and limited by its cash ([ADR 0058](0058-trade-at-the-next-observed-price.md),
[ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md)). What it gains stays in it.
Execution Engine ADR 0001 decided that a live fund owns its cash the same way (decision 14),
and left open how cash reaches a fund and leaves it (question 15).

### The example

The account is worth 1,000,000. Prices are AAPL 200, MSFT 400, JNJ 150 and TSLA 250.

| Fund | Portfolio | Share | Value | Units |
| --- | --- | --- | --- | --- |
| A | 60% AAPL, 40% MSFT | 40% | 400,000 | 1,200 AAPL, 400 MSFT |
| B | 50% MSFT, 50% JNJ | 30% | 300,000 | 375 MSFT, 1,000 JNJ |

The account holds exactly these units, and also TSLA, which is in no fund, and cash.

AAPL rises 10%, to 220. Fund A's units are worth 424,000, and the account is worth 1,024,000.
At the next sync, today:

- Fund A is sized at 40% of 1,024,000, which is 409,600: 1,117 AAPL and 410 MSFT. The sync
  assigns it 1,117 of its 1,200 AAPL. The other 83, about 18,260, go to the account itself
  without any trade, and fund A now asks for 410 MSFT instead of 400.
- Fund B is sized at 30% of 1,024,000, which is 307,200: 384 MSFT and 1,024 JNJ instead of 375
  and 1,000. Its portfolio did not move, yet its target grew by 7,200, out of fund A's gain.

## Decision

### 1. The money given to a fund is the fund's (owner)

A fund is given money. From then on its value is its holdings plus its cash, and it grows or
shrinks with its own result. The account does not rebalance a fund because its portfolio
moved. Money moves between the account and a fund only when someone moves it (decision 3).

### 2. A fund owns its cash (owner)

As Execution Engine ADR 0001 decided (decision 14): a fill, an internal trade and the fund's
share of a fee move the fund's cash, and the cash obeys the strategy's execution policy
(ADR 0058). This ADR is about how ms-markets records it.

### 3. Money moves as dated flows

Cash or units enter or leave a fund only through a flow: one dated row per movement between
the account itself and one of its funds. A flow is not a trade. Nothing is bought or sold, and
it has no price.

| Column | Meaning |
| --- | --- |
| `time_index` | When it moves |
| `flow_identifier` | The flow's key, so writing it again changes nothing |
| `account_uid`, `virtual_fund_uid` | The account and the fund |
| `asset_identifier` | The cash currency asset, or the asset of units moved in kind |
| `quantity`, `direction` | How much, and the side: into the fund, or out of it |
| `source` | Who moved it: the user, or a rule of the provider |
| `metadata_json` | Anything else the provider keeps |

- **A flow is a fact.** It is never changed or deleted; a correction is a new flow.
- **A move between funds** is two flows at the same time: one out of fund A, one into fund B.
- **The fund's capital** is the value of its flows when they were made, and its result is its
  value minus its capital. Both need prices, so the provider computes them (ADR 0054).

### 4. A portfolio row names what the account follows

A portfolio row of the account target says that the account follows that portfolio, and it
creates the fund (ADR 0054, decision 2). It states no share and no amount: the fund's money is
its flows. An asset row does not change. It is the account's own target, a share of the
account or `single_asset_quantity`, measured against what the funds leave.

A share of the account becomes a way to state a flow. The provider turns "give portfolio B 30%
of the account" into an amount, with its own valuation of the account at that moment, and
writes a flow of that amount. ms-markets reads no price, so it never makes that conversion. A
client call can write the target row and the first flow together.

A provider that wants a standing split, for example back to 40% and 30% every month, writes the
flows that restore it, on its own schedule. Every move of money between funds is then a
recorded flow, not a side effect of a sync.

### 5. A fund is sized from its own value

The provider sizes a fund's target units from the fund's own value, its holdings at the
provider's prices plus its cash, the way the backtest sizes from its book. The `owner_size` hook
of Execution Engine ADR 0001 defaults to that value. `sized_targets` keeps its shape
(ADR 0054).

### 6. A sync starts from each owner's own record

An owner is a fund or the account itself, as in `AccountAllocationLinesStorage`. At a sync each
fund first keeps what its own record explains:

1. **Its units:** its holdings at the previous sync, plus its in-kind flows and its fund fills
   since then.
2. **Its cash:** its cash at the previous sync, plus its cash flows, plus what its fills sold,
   minus what they bought and its share of the fees.

What no fund's record explains stays with the account itself (open question 3). When the
account holds less than the funds' records add up to, the funds keep what their records say,
and the account's own line shows the shortfall as a negative (owner, Execution Engine ADR 0001,
"Fund Holdings At A Sync").

A fund's cash is stored at the sync like its other holdings: a `VirtualFundHoldingsStorage` row
of the cash currency asset.

### 7. Whoever trades for a fund writes its fund fills

A fund's record must know which fills were its own. The fund fills of Execution Engine ADR 0001
("Fund Fills": one row per owner and fill, with the price and the owner's share of the fee)
become a Markets record. Whoever trades for a fund writes them: the engine's recorder, or a
provider that trades for its funds without the engine. A trade that no fund fill claims belongs
to the account itself.

### Records

| Record | Change |
| --- | --- |
| Flows between the account and its funds | New, time-indexed (decision 3) |
| Fund fills | New, as Execution Engine ADR 0001 proposes (decision 7) |
| `VirtualFundHoldingsStorage` | Also holds each fund's cash, as a row of the cash currency asset |
| `TargetPositionsStorage` | A portfolio row states no exposure; an asset row is unchanged |
| `VirtualFund`, `OrdersTS`, `TradesTS` | Unchanged |

## Worked Example

**Day 0.** The account holds 1,000,000 in cash, USD. Its target names portfolios A and B, and
TSLA as a direct row at 5% of the account. The provider gives fund A 400,000 and fund B
300,000: two flows. The funds buy their portfolios, and the account buys 200 TSLA for its own
row. Fees are left out.

| Owner | AAPL | MSFT | JNJ | TSLA | Cash | Value |
| --- | --- | --- | --- | --- | --- | --- |
| Fund A | 1,200 | 400 | | | 0 | 400,000 |
| Fund B | | 375 | 1,000 | | 0 | 300,000 |
| The account itself | | | | 200 | 250,000 | 300,000 |
| Account | 1,200 | 775 | 1,000 | 200 | 250,000 | 1,000,000 |

**Day 1.** AAPL rises 10%, to 220.

| Owner | Value | Capital | Result |
| --- | --- | --- | --- |
| Fund A | 424,000 | 400,000 | +24,000 |
| Fund B | 300,000 | 300,000 | 0 |
| The account itself | 300,000 | | |

Nothing is assigned again and nothing trades: fund A keeps its 1,200 AAPL and its gain. Whether
it trades back to 60% and 40% is its strategy's decision, in its own book.

**Day 2.** The owner moves 50,000 of the account's cash into fund B: one flow. Fund B's cash is
50,000 and its capital 350,000. Its strategy invests the cash at its next rebalance, sized from
its own value. The account itself keeps 200,000 in cash.

| `time_index` | Fund | Asset | Quantity, into the fund |
| --- | --- | --- | --- |
| Day 0 | A | USD | 400,000 |
| Day 0 | B | USD | 300,000 |
| Day 2 | B | USD | 50,000 |

## What It Changes

- **ADR 0054.** Decision 1: a portfolio row states no exposure. Decision 3: the provider sizes
  a fund from the fund's own value, not from the account's NAV.
- **ADR 0053 and ADR 0029.** The policy no longer splits the account's units at every sync. A
  fund keeps what its record explains.
- **ADR 0061.** It left open whether a share of the account stays a rule applied at every sync.
  Here it does not; it is a way to state a flow.
- **Execution Engine ADR 0001.** It answers question 15. The `owner_size` default becomes the
  fund's own value. Fund fills become a Markets record that any trader writes. Open question 3
  would change its rule for units no fill explains.

## Consequences

- A fund's value and result are its own. The account moves money between funds only by flows.
- A portfolio row no longer states a share, which breaks everyone who writes account targets.
- Trading for a fund means writing its fund fills. A trade with no fund fill stays the
  account's own, and the fund's cash does not change.
- Existing funds have no flows. There are no real portfolios yet, so nothing converts them:
  a fund starts with its first flow.

## Open Questions

These are the owner's to decide.

1. **Does a share of the account stay a standing rule?**
   - *Recommended:* no. It is a way to compute a flow's amount. A provider that wants a standing
     split writes the flows that restore it, so every move of money is recorded.
   - *Alternative:* keep it as a second mode, applied at every sync as today. Then each fund
     has one of two sizings, and the sync must know which.
2. **Is the money given to a fund a dated flow, or an amount on the target snapshot?**
   - *Recommended:* a dated flow. The target snapshot is replaced as a whole, so an amount on
     it cannot tell new money from the same money stated again. A fund's return also needs the
     dates of the money that moved.
   - *Alternative:* an amount on each portfolio row of the target, compared with the previous
     snapshot to find what moved.
3. **What happens to units no record explains at a sync**, for example shares transferred into
   the account?
   - *Recommended:* they stay with the account itself until a flow moves them into a fund. A
     fund then never gains units it did not pay for or was not given.
   - *Alternative:* the policy gives them to the funds that still want more, as Execution Engine
     ADR 0001 decided before funds had cash (owner). Each such assignment is then recorded as an
     in-kind flow.

## Not Decided Here

- A withdrawal larger than the fund's cash: refused, or the fund sells first, and who decides
  what it sells.
- The currency of a fund's cash when the portfolio's currency (ADR 0059) is not the account's
  cash currency.
- Dividends and interest the account receives for a fund's holdings, and how the account's fees
  are shared among its funds.
- Whether ms-markets stores a fund's value or result series, which need prices (ADR 0054).
- Whether the cash currency asset gets an allocation line with a target.
- How Command Center shows a fund's capital, cash and result.

## Not Verified

- That `VirtualFundHoldingsStorage` and the allocation code take a row of the cash currency
  asset without change.
- That a fund's cash computed from its flows and fills adds up to the account's cash holding
  when the venue books fees or interest that no fill shows.
