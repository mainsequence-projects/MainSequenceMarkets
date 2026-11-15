# Upgrading To 3.7

ms-markets 3.7 restores the account's exposure to a portfolio as a share of NAV or an amount,
and records each sync's lines: the sized target and the assigned units of every owner
([ADR 0054](ADR/0054-account-exposure-and-sized-fund-targets.md)). This page lists what
changes for a project that depends on ms-markets, coming from 3.5 or from 3.6.

The release is breaking. 3.6.0 stored account targets in units; that is withdrawn.

## The Model

| What | Where | Unit | Who writes it |
| --- | --- | --- | --- |
| The exposure the account wants to a portfolio | A portfolio row of the account target | A share of NAV or an amount | The user, through your code |
| The sized target of each owner per asset | The allocation's lines (`AccountAllocationLinesStorage`) | Units | Your code, at a sync |
| What each owner was assigned | The allocation's lines, and the fund's holdings rows | Units | ms-markets, at a sync |

Read [Sizing Targets And Allocating](knowledge/msm/accounts/sizing_and_allocation.md) first.
It shows the whole flow with an example.

## Data

- **Targets deleted by 3.6 are not restored.** Revision 0024 deleted every `PositionSet` and
  its target rows on any deployment that ran 3.6. Write each account's exposure again.
- **Targets written under 3.6.** Revision 0025 keeps a `PositionSet` of asset rows and turns
  each into `single_asset_quantity`. It deletes a `PositionSet` that has a portfolio row in
  units, with its rows: units per asset cannot be turned back into a share or an amount.
- **Allocations written before 3.7** keep their fund holdings. They have no lines, so
  `getAccountVirtualFundAllocation` answers no line for those snapshots.

## Coming From 3.5

### Writing a target

Nothing changes. A portfolio row holds `weight_notional_exposure` or
`constant_notional_exposure`; an asset row holds one of those or `single_asset_quantity`.

New: writing an exposure to a portfolio creates the `VirtualFund` of that account and
portfolio, if it does not exist.

### Allocating

| 3.5 | 3.7 |
| --- | --- |
| `plan_account_virtual_fund_allocations(position_set_uid, valuation_time, valuation_asset_uid, holdings_selection_policy, valuation_resolver, allocation_policy, portfolio_target_expander)` | `plan_account_virtual_fund_allocations(position_set_uid, valuation_time, sized_targets, policy=None)` |
| A valuation resolver, called by the planner, returns the NAV and the quantities | You size the target before the call and pass the units as `sized_targets` |
| `AllocationPolicy(...)`, `AllocationPolicy.strict_feasible()` | `policy={"id": "proportional_attribution", "version": "1.0.0", "arguments": {...}}`, or nothing for the default |
| `plan.status`, `plan.virtual_fund_allocations`, `plan.residuals`, `plan.deficits` | `plan.lines` (each with `target`, `assigned`, `delta`) and `plan.account_deltas` |
| `strict_feasible` refusing a shortfall | Your check: allocate only when no delta is positive |
| `apply_account_virtual_fund_allocation_plan(plan, updater=..., run=True)` returning a frame | `apply_account_virtual_fund_allocation_plan(plan)` returning a result with `applied`, `already_applied`, `funds` and `rows` |
| No Markets API route (removed in 3.5.0) | `plan_account_virtual_funds` and `allocate_account_virtual_funds` on `MarketsClient` |
| Applying again overwrote the rows | The same plan again writes nothing; a different allocation of the same snapshot is refused |
| Nothing records what an allocation was measured against | The allocation's lines record the sized target and the assigned units per owner; `account_virtual_fund_allocation` reads them with the delta |

A refusal raises `AllocationError`, which carries a `code` such as `not_found`,
`target_after_snapshot`, `invalid_sized_targets`, `plan_changed` or `allocation_exists`. It is
still a `ValueError`.

Removed names: `AllocationPolicy`, `HoldingsSelectionPolicy`, `ValuationResolver`,
`ValuationPolicy`, `AllocationValuation`, `ValuationMetricValue`, `ValuationMetricLine`,
`ValuationMetricResult`, `TargetNotionalDemand`, `TargetQuantityDemand`,
`HoldingValuationInput`, `ValuationDiagnostic`, `AccountVirtualHoldingLine`,
`AccountAllocationResidual`, `AccountAllocationDeficit` and the plan status constants.

## Coming From 3.6

| 3.6 | 3.7 |
| --- | --- |
| A portfolio target is one row per asset with `asset_uid`, `quantity` and `direction` | A portfolio target is one row per portfolio with `weight_notional_exposure` or `constant_notional_exposure`, and no `asset_uid` |
| An asset target is `quantity` and `direction` | An asset target is `single_asset_quantity` (signed), or a share or an amount |
| You size the target and write the units as the target | You write the exposure as the target, size it at the sync, and pass the units as `sized_targets` |
| `plan_account_virtual_funds(account_uid, position_set_uid, valuation_time)` | The same, plus `sized_targets` |
| A fund the account holds nothing of was not written; an allocation with no fill was refused (`nothing_to_apply`) | Every fund of the target gets its holdings set and its lines; `nothing_to_apply` is gone |
| Deltas were in the response of the call only | The lines of every sync are stored, for funds and for direct targets, and read back with `GET .../virtual-fund-allocations/` |
| A fund was created by its first allocation with a fill | A fund is created when its exposure is written |
| `GET /api/v1/portfolio/{uid}/account-targets/` answers `asset_count` | It answers the exposure fields again |

## Order Of Work

1. **Keep each account's exposure.** You need the share or the amount per portfolio to write
   the target again.
2. **Write the sizing step.** Turn an exposure into units per asset with your prices and
   rules.
3. **Change the target writes** to exposure rows.
4. **Change the allocation calls** to pass `sized_targets`, and read `lines` or the stored
   rows for the deltas.
5. **Upgrade** ms-markets. Revision 0025 runs with it.
6. **Write every account's exposure again**, then sync.

## Find What To Change

```bash
grep -rnE "valuation_resolver|AllocationPolicy\(|HoldingsSelectionPolicy|strict_feasible|plan\.status|nothing_to_apply|asset_count" src tests
```
