# Sizing Targets And Allocating: A Guide For Providers

This page is for a library or an application that uses ms-markets to keep an account's
targets and virtual funds. It says what your code does, what ms-markets does, and how to do
each step.

ms-markets is a record library. It stores units and assigns units. It never prices
anything. Every number that depends on a price, a contract's terms or a sizing rule is
yours ([ADR 0052](../../../ADR/0052-account-targets-in-units.md),
[ADR 0053](../../../ADR/0053-virtual-fund-allocation-routes-and-described-policies.md)).

## Who Does What

```text
   your code                         ms-markets
   ---------                         ----------
1. Sizing event
   prices, rules, the request  --->  2. Account target
                                        unit basket per fund

                                     3. Account holdings (units)
                                              |
                                              v
                                     4. Allocation
                                        units only, no prices
                                              |
                                              v
                                     5. Fund holdings (units)

6. Read the deltas, decide what to trade, value and report
```

| Step | Who | Needs market data |
| --- | --- | --- |
| Take the request ("40% of the account in this portfolio", "10,000 in this fund") | You | No |
| Size it into units | You | Yes |
| Record the target, the holdings and the fund holdings | ms-markets | No |
| Assign holdings to funds | ms-markets | No |
| Act on the deltas; value and report | You | Yes |

## Step 1: The Sizing Event

A sizing event turns a request into a unit basket. It happens when:

- a fund is sized: money goes into or out of the sleeve, or its share of the account changes;
- the fund's portfolio rebalances: its composition changes;
- your own rule says so, for example to bring a fund back to a fixed amount after prices
  have moved.

Between sizing events nothing is repriced. A price change alone never changes a fund's
basket in ms-markets. Whether and when to size again is your decision.

At a sizing event your code:

1. **Keeps the request.** Store the share, the amount or the risk budget in your own tables,
   next to the uid of the position set it produced. ms-markets does not store requests.
2. **Values what it needs** with your own market data: the account's NAV, each asset's
   price.
3. **Turns each leg into units** with your own rules: the contract multiplier, a delta, the
   lot size, how to round to whole contracts, FX.
4. **Writes the target** in units (step 2).

### A sizing rule

The rule below is an example of what your side owns. It turns a fund's size and each leg's
share into whole units:

```python
import math


def size_basket(fund_notional: float, legs: list[dict]) -> list[dict]:
    """One row per asset, in whole units. Prices and multipliers are the caller's."""

    rows = []
    for leg in legs:
        exposure = fund_notional * leg["share"]
        raw_units = exposure / (leg["price"] * leg["multiplier"])
        units = math.floor(raw_units / leg["lot"] + 0.5) * leg["lot"]
        if units == 0:
            continue  # A leg that rounds to nothing has no row.
        rows.append(
            {
                "asset_uid": leg["asset_uid"],
                "quantity": abs(units),
                "direction": 1 if units > 0 else -1,
                "metadata_json": {"raw_units": raw_units, "share": leg["share"]},
            }
        )
    return rows
```

With an account worth 10,000,000 and a fund at 40% of it, the fund is 4,000,000:

| Leg | Share of the fund | Your price | Multiplier | Raw units | Row you write |
| --- | --- | --- | --- | --- | --- |
| A stock | 50% | 250 | 1 | 8,000 | 8,000 shares, long |
| An index future | 30% of exposure | 6,100 | 50 | 3.93 | 4 contracts, long |
| A call written on the stock | −0.4% premium | 4 | 100 | −40 | 40 contracts, short |

- **Stock:** units are the notional divided by the price.
- **Future:** a future has no market value to weigh, so the share is an exposure. The
  multiplier and the rounding to whole contracts are your rule. Here 3.93 becomes 4.
- **Option:** what "share" means for an option, premium or delta-adjusted exposure, is your
  model's choice. ms-markets receives 40 contracts and the side.

A short position is a positive `quantity` with `direction: -1`. A leg that is no longer
wanted simply has no row.

### Sizing from a portfolio's unit book

When the portfolio keeps its own positions in units (`PortfolioStateStorage`), the basket is
that book scaled by one factor: the fund's size divided by the portfolio's size. Read the
book, multiply, apply your rounding, and write the rows. Record the factor and the book's
time in `metadata_json`.

## Step 2: Write The Target

Write the whole target of the account in one snapshot. Every row is a positive `quantity`
of one asset with a `direction`:

```python
from msm.client import MarketsClient

client = MarketsClient.from_environment()
target = client.add_account_target_positions(
    account_uid,
    target_positions_date=sized_at,
    positions=[
        # The fund's unit basket: one portfolio row per asset.
        *(
            {
                "target_type": "portfolio",
                "target_uid": portfolio_uid,
                "portfolio_uid": portfolio_uid,
                **row,
            }
            for row in size_basket(fund_notional, legs)
        ),
        # What the account keeps outside its funds, cash included, is a direct target.
        {
            "target_type": "asset",
            "target_uid": cash_asset_uid,
            "asset_uid": cash_asset_uid,
            "quantity": 6_000_000,
            "direction": 1,
        },
    ],
)
```

- **The target is the full picture.** Anything the account holds that no row names has a
  target of zero, and its delta will say to reduce it. Write a direct target for whatever
  the account should keep outside its funds.
- **One basket per portfolio.** The rows that share a `portfolio_uid` are that fund's whole
  basket. One asset appears at most once in a basket. The same asset can be in several
  baskets and be a direct target too.
- **A new snapshot to resize.** Write a new target at the new time. Do not edit an existing
  one.
- **`metadata_json` is yours.** Record how a row was sized: the scale factor, the portfolio
  book's time, the mandate share, a source note. ms-markets stores it and never reads it.
- **No value fields.** A share of NAV, a notional amount, a zero or a negative quantity is
  refused.

In-process code builds the same rows with `build_target_positions_frame(...)`.

## Step 3: Holdings

The allocation assigns the account's holdings snapshot taken at exactly the time you name.
Holdings are units too: a positive `quantity` and a `direction` per asset. Write them as you
do today; nothing changes here.

## Step 4: Plan

A plan writes nothing. It takes the target and the snapshot's time, and no price:

```python
plan = client.plan_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
)
for line in plan.lines:
    print(line.owner, line.asset_identifier, line.target, line.assigned, line.delta)
```

Each line is one owner and one asset. The owner is a fund or the direct account sleeve.

| Field | Meaning |
| --- | --- |
| `target` | What the owner should hold |
| `assigned` | What it gets from the account's holdings |
| `delta` | `target - assigned`: positive when units are missing, negative when there are more than the target asks for |

`plan.account_deltas` adds the deltas per asset: the account's total target minus what it
holds. That is what the account would have to trade to be on target.

The target may be older than the holdings: a target is in force from its own time on. A
target written after the holdings snapshot is refused.

### Choosing a policy

A policy decides how a shortfall is spread between funds. Read what exists and what each
takes:

```python
for policy in client.virtual_fund_allocation_policies():
    description = client.virtual_fund_allocation_policy(policy.id)
    print(policy.id, policy.version, description.arguments_schema)
```

Without a `policy`, `proportional_attribution` runs with its defaults: when the funds claim
more of an asset than the account holds, every fund gets the same fraction of its claim. To
choose, pass `policy={"id": ..., "version": ..., "arguments": {...}}`. Send the version you
read; a request built against another version is refused, so a changed policy never runs
silently.

## Step 5: Allocate

```python
result = client.allocate_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    plan_digest=plan.plan_digest,
)
```

The route plans again from the same inputs and writes the funds and their holdings in one
transaction. It never accepts a plan from you.

- **`plan_digest`** makes sure what is written is what you saw. If the target or the
  holdings changed since your plan, the call is refused and nothing is written. Plan again.
- **A shortfall is not refused.** The allocation is written with its deltas. If you want all
  or nothing, check the plan first and allocate only when no `account_deltas` entry is
  positive. That rule is yours.
- **An allocation is history.** The same plan again writes nothing and answers
  `already_applied`. A different allocation of the same snapshot is refused. To correct one,
  write a new holdings snapshot and allocate that.
- **A retired portfolio** stops the allocation. `plan.apply_blockers` tells you before you
  try.

## Step 6: After The Allocation

- **Read** what each fund holds with `GET /api/v1/account/{account_uid}/holdings/by-fund/`.
- **Deltas are not stored.** They are the target minus the holdings, so compute them from a
  plan whenever you need them.
- **Trading** to close a delta is your decision and your execution.
- **Valuing** a fund or the account, for NAV or performance, uses your prices.

## Rules To Keep

- Never send ms-markets a price, a NAV, a share or a notional amount. Send units.
- Keep the request, the prices and the rules that sized a target on your side.
- Size again only at a sizing event you define.
- Write the whole target, including what the account keeps outside its funds.
- Do not expect ms-markets to check that a basket matches its portfolio.

## If You Are Upgrading

See [Upgrading To 3.6](../../../upgrading-to-3-6.md) for what changes for existing code and
data.
