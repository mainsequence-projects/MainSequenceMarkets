---
name: mainsequence-markets-account-target-sizing
description: Use this skill when a library or application that uses ms-markets writes an account's exposure to portfolios, sizes it into units at a sync, allocates holdings to virtual funds, reads fund deltas, or upgrades to ms-markets 3.7.
---

# Account Exposure, Sizing And Allocation

Use this skill when a workflow has to record "40% of the account in this portfolio" or
"300,000 in this portfolio", turn it into units at a sync, and keep each virtual fund's
target, holdings and delta.

ms-markets is a record library. It reads no price and computes no NAV (ADR 0054).

## Owning Context

Read with:

1. `.agents/skills/ms_markets/accounts/account_workflow/SKILL.md`
2. `docs/knowledge/msm/accounts/sizing_and_allocation.md`: the step-by-step guide
3. `docs/upgrading-to-3-7.md`: what changes for existing code and data
4. `docs/ADR/0054-account-exposure-and-sized-fund-targets.md`
5. `docs/ADR/0053-virtual-fund-allocation-routes-and-described-policies.md`

## The Three Things

| What | Where | Unit | Who writes it |
| --- | --- | --- | --- |
| The exposure the account wants to a portfolio | `TargetPositionsStorage`, one row per portfolio | A share of NAV or an amount | The user, through the project |
| The sized target of each owner per asset | `AccountAllocationLinesStorage.target_quantity` | Units | The project, at a sync |
| What each owner was assigned | `AccountAllocationLinesStorage.assigned_quantity`; `VirtualFundHoldingsStorage` for a fund | Units | ms-markets, at a sync |

A portfolio has weights, not units. Never write units as an account's target to a
portfolio, and never ask ms-markets to turn a share or an amount into units.

## Who Does What

| Step | Who | Needs prices |
| --- | --- | --- |
| State the exposure | The user, through the project | No |
| Record the exposure and create the fund | ms-markets | No |
| Publish the account's holdings | The project | No |
| Size each exposure into units | The project | Yes |
| Assign holdings to funds; record target and assigned units per owner | ms-markets | No |
| Read the deltas and trade them | The project | Yes |

## Writing The Exposure

```python
from msm.client import MarketsClient

client = MarketsClient.from_environment()
target = client.add_account_target_positions(
    account_uid,
    target_positions_date=target_time,
    positions=[
        {"target_type": "portfolio", "portfolio_uid": portfolio_a_uid, "weight_notional_exposure": 0.40},
        {"target_type": "portfolio", "portfolio_uid": portfolio_b_uid, "constant_notional_exposure": 300_000},
    ],
)
```

- One row per portfolio, with exactly one of `weight_notional_exposure` and
  `constant_notional_exposure`.
- Writing it creates the `VirtualFund` of that account and portfolio if it does not exist.
- An asset row is a direct target: a share, an amount, or `single_asset_quantity` in units.
- In-process code builds the same rows with `build_target_positions_frame(...)`.

## The Sync

A sync is one holdings snapshot of the account at time `T`, allocated to its funds:

1. publish the holdings at `T`;
2. size every exposure of the target into units, with the project's prices at `T`;
3. plan, then allocate, passing the units as `sized_targets`.

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
]
plan = client.plan_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
)
result = client.allocate_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
    plan_digest=plan.plan_digest,
)
```

- Every portfolio exposure must be sized, and every asset exposure stated as a share or an
  amount. An asset row stated as `single_asset_quantity` is not sized.
- An empty `positions` list is a target sized to nothing.
- A mismatch answers 400 `invalid_sized_targets` and lists every problem.
- A `quantity` is positive; `direction` is `1` or `-1`.

## A Sizing Rule

The project owns this function. It is an example, not an ms-markets API:

```python
import math


def size_fund(fund_notional: float, legs: list[dict]) -> list[dict]:
    positions = []
    for leg in legs:
        raw_units = fund_notional * leg["weight"] / (leg["price"] * leg["multiplier"])
        units = math.floor(raw_units / leg["lot"] + 0.5) * leg["lot"]
        if units == 0:
            continue
        positions.append(
            {
                "asset_uid": leg["asset_uid"],
                "quantity": abs(units),
                "direction": 1 if units > 0 else -1,
            }
        )
    return positions
```

- A stock: units are the notional divided by the price.
- A future: the weight is an exposure; the multiplier and the rounding to whole contracts
  are the project's rule.
- An option: whether the weight means premium or delta-adjusted exposure is the project's
  model.

## What The Sync Stores

- The allocation's lines in `AccountAllocationLinesStorage`: one row per sync, owner and
  asset, with `target_quantity`, `target_direction`, `assigned_quantity` and
  `assigned_direction`. The owner is a fund (`owner_type="fund"`) or the account itself
  (`owner_type="direct"`) for a direct asset target and for what no fund takes.
- One `VirtualFundHoldingsSet` per fund of the target, pointing at the account holdings
  snapshot of `T`, and one `VirtualFundHoldingsStorage` row per asset the fund was assigned.
- A fund the account holds nothing of has its lines with nothing assigned.
- The delta is read from a line: target minus assigned. Read a sync's lines with
  `client.account_virtual_fund_allocation(account_uid)`; without `valuation_time` it is the
  latest sync.

## Rules

- State exposure in the account target; send units only in `sized_targets`.
- Never send a price or a NAV to ms-markets.
- Size at every sync with that sync's prices; a stored target is valid for that sync only.
- An allocation is history: the same plan again writes nothing, a different allocation of
  the same snapshot is refused. Correct it with a new holdings snapshot.
- A shortfall is not refused. For all or nothing, allocate only when no delta is positive.
- Read the policies with `virtual_fund_allocation_policies()` and send the version you
  read. Never hand-write a policy's schema.
- Do not expect ms-markets to check that a sizing matches its portfolio's weights.

## Upgrading A Project To 3.7

1. Keep each account's exposure: revision 0024 deleted targets on deployments that ran 3.6,
   and revision 0025 deletes any portfolio target written in units.
2. Write the sizing step.
3. Write targets as exposure rows.
4. Pass `sized_targets` to the plan and allocate calls.
5. Upgrade, write every account's exposure again, then sync.

Search for what is left:

```bash
grep -rnE "valuation_resolver|AllocationPolicy\(|HoldingsSelectionPolicy|strict_feasible|plan\.status|nothing_to_apply|target_gap_signed_quantity|asset_count" src tests
```
