---
name: mainsequence-markets-account-target-sizing
description: Use this skill when writing, reviewing, or documenting how a caller sizes ms-markets account targets and virtual-fund unit baskets in units.
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
2. `docs/ADR/0052-account-targets-in-units.md`
3. `docs/knowledge/msm/accounts/virtual_funds.md`
4. `src/msm/services/target_positions.py`

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
