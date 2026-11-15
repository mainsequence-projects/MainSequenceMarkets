# Sizing Targets And Allocating: A Guide For Providers

This page is for a library or an application that uses ms-markets to keep an account's
target and its virtual funds. It says what your code does, what ms-markets does, and how to
do each step.

ms-markets is a record library. It stores the exposure, the holdings and the funds, and it
assigns units. It never prices anything. Every number that depends on a price is yours
([ADR 0054](../../../ADR/0054-account-exposure-and-sized-fund-targets.md),
[ADR 0053](../../../ADR/0053-virtual-fund-allocation-routes-and-described-policies.md)).

## Who Does What

```text
   your code                              ms-markets
   ---------                              ----------
1. The user states an exposure     --->   Account target: a share of NAV or an
                                          amount per portfolio. The fund is created.

2. Sync: publish the holdings      --->   Account holdings (units)
3. Sync: size each exposure
   into units, with your prices    --->   4. Allocation: assign the holdings to the
                                             funds. No price.
                                          5. Allocation lines: sized target and assigned
                                             units per owner and asset.

6. Read the deltas and trade them
```

| Step | Who | Needs prices |
| --- | --- | --- |
| State the exposure: a share of NAV or an amount per portfolio | The user, through you | No |
| Record the exposure and create the fund | ms-markets | No |
| Publish the account's holdings | You | No |
| Size each exposure into units | You | Yes |
| Assign holdings to funds; record target and assigned units per owner | ms-markets | No |
| Read the deltas and trade them | You | Yes |

## The Example

Portfolio A is 60% AAPL and 40% MSFT. Portfolio B is 50% MSFT and 50% JNJ. The account holds
AAPL 1,000, MSFT 600, JNJ 1,000 and TSLA 1,640; TSLA is in no fund.

## Step 1: Write The Exposure

The account target says how much of each portfolio the account should hold. It is a share
of the account's NAV or an amount, never units: a portfolio has weights, not units.

```python
from msm.client import MarketsClient

client = MarketsClient.from_environment()
target = client.add_account_target_positions(
    account_uid,
    target_positions_date=target_time,
    positions=[
        # 40% of the account's NAV in portfolio A.
        {"target_type": "portfolio", "portfolio_uid": portfolio_a_uid, "weight_notional_exposure": 0.40},
        # 300,000 in portfolio B.
        {"target_type": "portfolio", "portfolio_uid": portfolio_b_uid, "constant_notional_exposure": 300_000},
    ],
)
```

- **One row per portfolio**, with exactly one of `weight_notional_exposure` and
  `constant_notional_exposure`.
- **The fund is created here.** Writing an exposure to a portfolio creates the `VirtualFund`
  of that account and portfolio if it does not exist. It has no holdings until the first
  sync.
- **A new snapshot to change it.** Write a new target at the new time.
- **An asset target** (`target_type="asset"`) is a direct target on one asset: a share, an
  amount, or `single_asset_quantity` in units.

## Step 2: Publish The Holdings

The sync starts with the account's holdings at time `T`, in units: a positive `quantity` and
a `direction` per asset. Write them as you do today.

## Step 3: Size The Exposure

A sync sizes every exposure of the target into units, with your prices at `T`. This is the
only step that needs market data, and it is yours.

With your prices (AAPL 200, MSFT 400, JNJ 150, TSLA 250) the account is worth 1,000,000.
Fund A is 40% of that, 400,000. Fund B is 300,000.

| Fund | Asset | Calculation | Target units |
| --- | --- | --- | --- |
| A | AAPL | 400,000 × 60% ÷ 200 | 1,200 |
| A | MSFT | 400,000 × 40% ÷ 400 | 400 |
| B | MSFT | 300,000 × 50% ÷ 400 | 375 |
| B | JNJ | 300,000 × 50% ÷ 150 | 1,000 |

A sizing rule turns a fund's size and its portfolio's weights into units. This one is an
example of what your side owns:

```python
import math


def size_fund(fund_notional: float, legs: list[dict]) -> list[dict]:
    """One position per asset. Prices, multipliers and rounding are the caller's."""

    positions = []
    for leg in legs:
        raw_units = fund_notional * leg["weight"] / (leg["price"] * leg["multiplier"])
        units = math.floor(raw_units / leg["lot"] + 0.5) * leg["lot"]
        if units == 0:
            continue  # A leg that rounds to nothing has no position.
        positions.append(
            {
                "asset_uid": leg["asset_uid"],
                "quantity": abs(units),
                "direction": 1 if units > 0 else -1,
            }
        )
    return positions
```

- **Stock:** units are the notional divided by the price.
- **Future:** it has no market value to weigh, so the weight is an exposure. The multiplier
  and the rounding to whole contracts are your rule.
- **Option:** whether the weight means premium or delta-adjusted exposure is your model's
  choice. ms-markets receives contracts and a side.

The result goes into `sized_targets`, one entry per exposure:

```python
sized_targets = [
    {
        "target_type": "portfolio",
        "target_uid": portfolio_a_uid,
        "positions": [
            {"asset_uid": aapl_uid, "quantity": 1_200, "direction": 1},
            {"asset_uid": msft_uid, "quantity": 400, "direction": 1},
        ],
    },
    {
        "target_type": "portfolio",
        "target_uid": portfolio_b_uid,
        "positions": [
            {"asset_uid": msft_uid, "quantity": 375, "direction": 1},
            {"asset_uid": jnj_uid, "quantity": 1_000, "direction": 1},
        ],
    },
]
```

- **Every exposure must be sized:** each portfolio row, and each asset row stated as a share
  or an amount. An asset row stated as `single_asset_quantity` is already in units and is not
  sized.
- **An empty `positions` list** is a target sized to nothing.
- **A target the `PositionSet` does not name** is refused.
- A mismatch answers 400 `invalid_sized_targets` and lists every problem.

## Step 4: Plan

A plan writes nothing and takes no price:

```python
plan = client.plan_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
)
for line in plan.lines:
    print(line.owner, line.asset_identifier, line.target, line.assigned, line.delta)
```

Each line is one owner and one asset. The owner is a fund or the direct account sleeve.

| Owner | Asset | Target | Assigned | Delta |
| --- | --- | --- | --- | --- |
| Fund A | AAPL | 1,200 | 1,000 | +200 |
| Fund A | MSFT | 400 | 309.68 | +90.32 |
| Fund B | MSFT | 375 | 290.32 | +84.68 |
| Fund B | JNJ | 1,000 | 1,000 | 0 |
| Direct | TSLA | 0 | 1,640 | −1,640 |

`delta` is `target - assigned`: positive when units are missing. The funds claim 775 MSFT
against 600 held, so each gets the same fraction of its claim.

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

Without a `policy`, `proportional_attribution` runs with its defaults. To choose, pass
`policy={"id": ..., "version": ..., "arguments": {...}}`. Send the version you read; a
request built against another version is refused.

## Step 5: Allocate

```python
result = client.allocate_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
    plan_digest=plan.plan_digest,
)
```

The route plans again from the same inputs and writes in one transaction. It never accepts
a plan from you.

What it stores:

- **The allocation's lines**, one row per sync, owner and asset, with the sized target and
  the assigned units. The owner is a fund, or the account itself for a direct target and for
  what no fund takes. This is the record of the sync, 1:1 with the holdings snapshot of `T`.
- **Each fund's holdings**: one holdings set per fund and one row per asset it was assigned.

| Owner | Asset | `target_quantity` | `assigned_quantity` | Delta (read) |
| --- | --- | --- | --- | --- |
| Fund A | AAPL | 1,200 | 1,000 | 200 |
| Fund A | MSFT | 400 | 309.68 | 90.32 |
| Fund B | MSFT | 375 | 290.32 | 84.68 |
| Fund B | JNJ | 1,000 | 1,000 | 0 |
| Direct | TSLA | 0 | 1,640 | −1,640 |

- **`plan_digest`** makes sure what is written is what you saw. It covers the sized targets,
  so other targets, a changed exposure or changed holdings refuse the call. Plan again.
- **Every owner is recorded.** A fund the account holds nothing of has its lines with nothing
  assigned, so its whole target reads as the delta. A direct asset target has its line too.
- **A shortfall is not refused.** If you want all or nothing, check the plan first and
  allocate only when no delta is positive. That rule is yours.
- **An allocation is history.** The same plan again writes nothing and answers
  `already_applied`. A different allocation of the same snapshot is refused. To correct one,
  publish a new holdings snapshot and sync that.
- **A retired portfolio** stops the allocation. `plan.apply_blockers` tells you before you
  try.

## Step 6: Read The Deltas

```python
record = client.account_virtual_fund_allocation(account_uid)   # the latest sync
for line in record.lines:
    print(line.owner, line.asset_identifier, line.target, line.assigned, line.delta)
```

`GET /api/v1/account/{account_uid}/virtual-fund-allocations/` answers the stored lines of one
sync: the latest, or the one at `valuation_time`. Each line has the owner (`fund` or
`direct`), the sized `target`, what was `assigned` and `delta = target - assigned`.

- **Trading** a delta is your decision and your execution.
- **The target is valid for that sync's prices.** The next sync sizes again.
- **Valuing** a fund or the account uses your prices.

## Rules To Keep

- State exposure in the account target: a share of NAV or an amount per portfolio.
- Never send ms-markets a price or a NAV. Send units, in `sized_targets`.
- Size at every sync, with the prices of that sync.
- Do not expect ms-markets to check that a sizing matches its portfolio's weights.

## If You Are Upgrading

See [Upgrading To 3.7](../../../upgrading-to-3-7.md).
