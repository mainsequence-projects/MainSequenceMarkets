---
name: mainsequence-markets-account-target-sizing
description: Use this skill when a library or application that uses ms-markets sizes account targets or virtual-fund unit baskets, allocates holdings to virtual funds, or upgrades to ms-markets 3.6.
---

# Account Target Sizing

Use this skill when a workflow has to turn a request such as "40% of the account in
this portfolio" or "10,000 in this fund" into an ms-markets account target.

Account targets are stored in units (ADR 0052). ms-markets is a record library: it
stores the units and derives nothing. Prices, and the rules that turn a price into a
position size, belong to the caller.

## Owning Context

Read with:

1. `.agents/skills/ms_markets/accounts/account_workflow/SKILL.md`
2. `docs/knowledge/msm/accounts/sizing_and_allocation.md`: the step-by-step guide
3. `docs/upgrading-to-3-6.md`: what changes for existing code and data
4. `docs/ADR/0052-account-targets-in-units.md`
5. `docs/ADR/0053-virtual-fund-allocation-routes-and-described-policies.md`

## Who Does What

| Step | Who | Needs market data |
| --- | --- | --- |
| Take the request (a share, an amount, a risk budget) and keep it | The project | No |
| Size it into units, at a sizing event | The project | Yes |
| Record the target, the holdings and the fund holdings | ms-markets | No |
| Assign holdings to funds | ms-markets | No |
| Act on the deltas; value and report | The project | Yes |

Do not add pricing, a NAV calculation or a sizing rule to ms-markets, and do not ask
ms-markets to convert a share or an amount into units. That code belongs in the project
that owns the prices.

## What A Target Row Is

Every `TargetPositionsStorage` row is a positive `quantity` of one asset, in the
asset's own unit, with a `direction` (`1` long, `-1` short):

- shares for a stock, contracts for a future or an option, units for a currency;
- an asset row (`target_type="asset"`) is a direct target;
- the portfolio rows of one `portfolio_uid` are that virtual fund's unit basket,
  one row per asset.

There is no share of NAV and no notional amount on a row.

## The Sizing Event

A basket only needs to change when:

- the fund is sized: money goes into or out of the sleeve, or its share of the
  account changes;
- the portfolio rebalances: its composition changes.

At each event the caller:

1. keeps the request (a share, an amount, a risk budget) in its own tables;
2. values what it needs with its own market data;
3. turns the request into units with its own rules: contract multipliers, deltas,
   lot sizes, rounding to whole contracts, FX;
4. writes a new target snapshot in units.

Between events nothing is repriced, so a price change alone never changes a fund's
basket.

For a portfolio that has a unit book (`PortfolioStateStorage`), the basket is the
book scaled by one factor: the fund's size divided by the portfolio's size.

## Writing The Target

```python
from msm.client import MarketsClient

client = MarketsClient.from_environment()
client.add_account_target_positions(
    account_uid,
    target_positions_date=sized_at,
    positions=[
        # A direct target: 12 contracts of one future, short.
        {
            "target_type": "asset",
            "target_uid": future_uid,
            "asset_uid": future_uid,
            "quantity": 12,
            "direction": -1,
        },
        # One virtual fund's unit basket: one row per asset.
        {
            "target_type": "portfolio",
            "target_uid": portfolio_uid,
            "portfolio_uid": portfolio_uid,
            "asset_uid": stock_uid,
            "quantity": 1000,
            "metadata_json": {"scale_factor": 0.25, "mandate_share": 0.4},
        },
        {
            "target_type": "portfolio",
            "target_uid": portfolio_uid,
            "portfolio_uid": portfolio_uid,
            "asset_uid": option_uid,
            "quantity": 40,
        },
    ],
)
```

In-process code builds the same rows with `build_target_positions_frame(...)`.

`metadata_json` may record how a row was sized: the scale factor, the portfolio book
time, the mandate share and a source note. ms-markets stores it and never reads it.

## A Sizing Rule

The project owns this function. It is an example, not an ms-markets API:

```python
import math


def size_basket(fund_notional: float, legs: list[dict]) -> list[dict]:
    rows = []
    for leg in legs:
        exposure = fund_notional * leg["share"]
        raw_units = exposure / (leg["price"] * leg["multiplier"])
        units = math.floor(raw_units / leg["lot"] + 0.5) * leg["lot"]
        if units == 0:
            continue
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

- A stock: units are the notional divided by the price.
- A future: it has no market value to weigh, so the share is an exposure; the multiplier
  and the rounding to whole contracts are the project's rule.
- An option: whether the share means premium or delta-adjusted exposure is the project's
  model. ms-markets receives contracts and a side.

## After Sizing: Plan And Allocate

```python
plan = client.plan_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
)
result = client.allocate_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    plan_digest=plan.plan_digest,
)
```

- A plan writes nothing and takes no price. Each line has an owner (a fund or the direct
  sleeve), a `target`, what is `assigned` and `delta = target - assigned`.
- `plan.account_deltas` is each asset's total target minus what the account holds: what
  the account would trade to be on target. Trading it is the project's decision.
- The target is the full picture. Write a direct target for what the account keeps outside
  its funds, cash included; otherwise its delta says to reduce it.
- A shortfall is not refused. For all or nothing, allocate only when no account delta is
  positive. That check belongs to the project.
- An allocation is history. The same plan again writes nothing; a different allocation of
  the same snapshot is refused. Correct it with a new holdings snapshot.
- Read the policies with `virtual_fund_allocation_policies()` and send the version you
  read. Never hand-write a policy's schema.

## Upgrading A Project To 3.6

1. Save each account's request in the project's own tables. Migration 0024 deletes every
   existing target.
2. Write the sizing step.
3. Send `asset_uid`, `quantity` and `direction` on every target row.
4. Replace the planner's valuation resolver, `AllocationPolicy` and updater arguments.
5. Replace any strict mode with a check on the account deltas.
6. Upgrade, then size and write every account's target again.

Search for what is left:

```bash
grep -rnE "weight_notional_exposure|constant_notional_exposure|single_asset_quantity|valuation_resolver|AllocationPolicy|HoldingsSelectionPolicy|strict_feasible|expand_portfolio_target|plan\.status" src tests
```

## Rules

- Never send a share of NAV, a notional amount or a price to ms-markets.
- Never write a zero or negative `quantity`; use `direction` for the side, and leave
  out an asset that is no longer in a basket.
- Give every row its `asset_uid`. A portfolio row without one is refused.
- One asset appears at most once per basket. The same asset may be a direct target
  and sit in several baskets.
- Do not expect ms-markets to check that a basket matches its portfolio. Record the
  sizing inputs in `metadata_json` if they must be traceable.
- Write a new snapshot to resize; do not edit rows of an existing one.

## Where Market Data Is Needed

| Step | Needs market data | Who supplies it |
| --- | --- | --- |
| Portfolio construction and rebalance | Yes | Provided to the portfolio engine |
| Sizing a fund's basket | Yes | The caller, at the sizing event |
| Allocating holdings to funds | No | |
| Valuing a fund or the account | Yes | The caller, when it reports |
