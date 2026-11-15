# Upgrading To 3.6

ms-markets 3.6 stores account targets in units and allocates virtual funds without any
price ([ADR 0052](ADR/0052-account-targets-in-units.md),
[ADR 0053](ADR/0053-virtual-fund-allocation-routes-and-described-policies.md)). This page
lists what changes for a project that depends on ms-markets and the order to change it.

The release is breaking. Nothing from before 3.6 is kept under an old name.

## What Moves To Your Side

Before 3.6 a target said "this portfolio gets 40% of the account", and the allocation turned
that into units with prices on every run. From 3.6 your code sizes the target once, at a
sizing event, and writes units. ms-markets records and assigns them.

Read [Sizing Targets And Allocating](knowledge/msm/accounts/sizing_and_allocation.md) first.
It shows the whole flow and a sizing rule for stocks, futures and options.

## Data: Existing Targets Are Deleted

Migration 0024 deletes every `PositionSet` and its target rows. They hold shares of NAV and
notional amounts, which cannot be turned into units without prices.

- Account target allocations, holdings and applied virtual-fund holdings are kept.
- After the upgrade an account has no target until you write one.
- Keep each account's request (its shares or amounts) on your side before upgrading, so you
  can size and write its target again.

## What Changes

### Writing and reading a target

| Before 3.6 | From 3.6 |
| --- | --- |
| A portfolio row with `weight_notional_exposure` or `constant_notional_exposure` | One portfolio row per asset of the fund's basket, with `asset_uid`, `quantity` and `direction` |
| An asset row with `single_asset_quantity`, or a weight or notional | An asset row with `quantity` and `direction` |
| A negative quantity for a short | A positive `quantity` with `direction: -1` |
| Nothing for what the account keeps outside its funds | A direct target row for it, cash included |
| `expand_portfolio_target_positions(...)` | Removed: a target is already per asset |

This applies to `POST /api/v1/account/{account_uid}/add-target-positions/`,
`MarketsClient.add_account_target_positions` and `build_target_positions_frame`.
`GET .../target-positions/` answers the same fields.
`GET /api/v1/portfolio/{uid}/account-targets/` answers `asset_count` in place of the
exposure fields.

### Planning and applying an allocation

| Before 3.6 | From 3.6 |
| --- | --- |
| `plan_account_virtual_fund_allocations(position_set_uid, valuation_time, valuation_asset_uid, holdings_selection_policy, valuation_resolver, allocation_policy, portfolio_target_expander)` | `plan_account_virtual_fund_allocations(position_set_uid, valuation_time, policy=None)` |
| A valuation resolver that returns the NAV and quantities | Removed: you size the target before writing it |
| `AllocationPolicy(...)`, `AllocationPolicy.strict_feasible()` | `policy={"id": "proportional_attribution", "version": "1.0.0", "arguments": {...}}`, or nothing for the default |
| `plan.status`, `plan.virtual_fund_allocations`, `plan.residuals`, `plan.deficits` | `plan.lines` (each with `target`, `assigned`, `delta`) and `plan.account_deltas` |
| `strict_feasible` refusing a shortfall | Your check: allocate only when no account delta is positive |
| `apply_account_virtual_fund_allocation_plan(plan, updater=..., run=True)` returning a frame | `apply_account_virtual_fund_allocation_plan(plan)` returning a result with `applied`, `already_applied`, `funds` and `rows` |
| No Markets API route | `plan_account_virtual_funds` and `allocate_account_virtual_funds` on `MarketsClient` |
| Applying again overwrote the rows | The same plan again writes nothing; a different allocation of the same snapshot is refused |

A refusal raises `AllocationError`, which carries a `code` such as `not_found`,
`target_after_snapshot`, `plan_changed` or `allocation_exists`. It is still a `ValueError`.

### Removed names

`AllocationPolicy`, `HoldingsSelectionPolicy`, `ValuationResolver`, `ValuationPolicy`,
`AllocationValuation`, `ValuationMetricValue`, `ValuationMetricLine`,
`ValuationMetricResult`, `TargetNotionalDemand`, `TargetQuantityDemand`,
`HoldingValuationInput`, `ValuationDiagnostic`, `AccountVirtualHoldingLine`,
`AccountAllocationResidual`, `AccountAllocationDeficit`, `expand_portfolio_target_rows`,
`TARGET_POSITION_EXPOSURE_FIELDS` and the plan status constants.

## Order Of Work

1. **Save the requests.** Record each account's shares or amounts in your own tables.
2. **Write the sizing step.** Turn a request into unit rows with your prices and rules.
3. **Change the target writes** to send `asset_uid`, `quantity` and `direction`, and add a
   direct target for what each account keeps outside its funds.
4. **Change the allocation calls** to the new planner or to the Markets API methods, and
   read `lines` and `account_deltas`.
5. **Replace any strict mode** with your own check on the account deltas.
6. **Upgrade** ms-markets. Migration 0024 runs with it.
7. **Size and write every account's target again**, then allocate.

## Find What To Change

Search your project for the removed names and fields:

```bash
grep -rnE "weight_notional_exposure|constant_notional_exposure|single_asset_quantity|valuation_resolver|AllocationPolicy|HoldingsSelectionPolicy|strict_feasible|expand_portfolio_target|plan\.status" src tests
```
