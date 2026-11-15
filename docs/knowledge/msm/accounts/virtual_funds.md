# Account Virtual Funds

Virtual funds are core `msm` account-allocation views over real account
holdings. They are not assets, not custody accounts, and not portfolio
construction objects.

The canonical custody record remains:

```text
AccountTable
  <- AccountHoldingsSetTable
       <- AccountHoldingsStorage
```

Virtual funds derive allocation views from that custody record:

```text
AccountTable
  <- VirtualFundTable
       target_portfolio_uid -> PortfolioTable.uid

VirtualFundTable
  <- VirtualFundHoldingsSetTable
       source_account_holdings_set_uid -> AccountHoldingsSetTable.uid

VirtualFundHoldingsSetTable
  <- VirtualFundHoldingsStorage
       asset_identifier -> AssetTable.unique_identifier
```

`msm_portfolios` remains the portfolio construction engine. It can provide
portfolio weights or run portfolio updaters, but it does not own virtual-fund
identity or holdings storage.

## Targets In Units

A virtual fund's target is a unit basket (ADR 0052). It is stored in the
account's target snapshot, as the `TargetPositionsStorage` rows of one portfolio:
one row per asset, each a positive `quantity` in the asset's own unit with a
`direction`.

```text
PositionSetTable
  <- TargetPositionsStorage
       target_type = "portfolio"
       portfolio_uid -> PortfolioTable.uid      the virtual fund's portfolio
       asset_uid     -> AssetTable.uid          one asset of the basket
       quantity > 0, direction 1 / -1
```

Account holdings, fund targets and fund holdings are all in units, so the
allocation needs no price. A share, a futures contract and an option contract
are handled the same way.

### Sizing a basket

ms-markets is a record library: it stores the basket and derives nothing. The
caller sizes it, with its own prices and rules, at a sizing event:

- the fund is sized: money goes into or out of the sleeve, or its share of the
  account changes;
- the portfolio rebalances: its composition changes.

A request such as "10,000 in this fund" or "40% of the account" belongs to the
provider that takes it. The provider stores the request, turns it into units
(multipliers, deltas, lot sizes, rounding, FX) and writes a new target. For a
portfolio with a unit book (`PortfolioStateStorage`), the basket is the book
scaled by one factor.

A row's `metadata_json` may record how it was sized: the scale factor, the
portfolio book time, the mandate share and a source note. ms-markets never
reads it.

| Step | Needs market data | Who supplies it |
| --- | --- | --- |
| Portfolio construction and rebalance | Yes | Provided to the portfolio engine |
| Sizing a fund's basket | Yes | The caller, at the sizing event |
| Allocating holdings to funds | No | |
| Valuing a fund or the account | Yes | The caller, when it reports |

## Storage Shape

`VirtualFundTable` stores the account-owned allocation view:

```text
uid PK
unique_identifier unique
account_uid FK -> AccountTable.uid
target_portfolio_uid FK -> PortfolioTable.uid
```

`VirtualFundHoldingsSetTable` groups one allocation result:

```text
uid PK
virtual_fund_uid FK -> VirtualFundTable.uid
source_account_holdings_set_uid FK -> AccountHoldingsSetTable.uid
time_index
```

`VirtualFundHoldingsStorage` stores timestamped allocation rows keyed by:

```text
(time_index, virtual_fund_uid, asset_identifier)
```

The row stores a positive `allocated_quantity`, a first-class
`allocation_strategy`, and a signed `direction`. Short exposure is represented
with `direction = -1`, not a negative quantity.

`allocation_strategy` records the strategy used to create the row. Low-level
explicit publications use `explicit`; rows published from
`apply_account_virtual_fund_allocation_plan(...)` use the allocation policy
mode, such as `proportional_attribution` or `strict_feasible`.

## Planner Flow

ADR 0029 defines the account holdings to virtual-fund allocation planner. The
planner is a dry-run service: it computes a deterministic plan and performs no
writes.

Use the canonical account target snapshot path. Do not pass a raw account UID,
raw holdings-set UID, raw source holdings, or raw target demand rows into the
public planner.

```python
from msm.services.accounts import (
    AllocationPolicy,
    HoldingsSelectionPolicy,
    plan_account_virtual_fund_allocations,
)

plan = plan_account_virtual_fund_allocations(
    position_set_uid=position_set.uid,
    valuation_time=workflow_time,
    holdings_selection_policy=HoldingsSelectionPolicy(),
    allocation_policy=AllocationPolicy(),
)
```

The planner follows one deterministic path:

```text
PositionSetTable.uid
  -> AccountTargetAllocationTable.uid
  -> AccountHoldingsSetTable(account_uid, valuation_time)
  -> AccountHoldingsStorage rows        units held
  -> TargetPositionsStorage rows        unit targets and unit baskets
  -> AssetTable identity rows
```

It reads no price, NAV or portfolio weight.

The holdings set is the one captured at `valuation_time`: the capture is the
valuation. The target is the `PositionSet` the caller passes, used as it is.
A target is in force from its own `position_set_time` on, so a capture taken
after the target was written is attributed against it: plan it with the later
capture's `valuation_time` and the earlier `position_set_uid`. A `PositionSet`
written after `valuation_time` is refused, since it cannot apply to holdings
captured before it.

The Markets API has no allocation route. The route 3.1.0 added valued holdings
at their target portfolios' weights prices and was removed in 3.5.0
([#68](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/68)).

Core `msm` owns the account and virtual-fund allocation logic, and it does not
import `msm_portfolios`.

## Allocation Policy

The default policy is `proportional_attribution`.

For each asset, the planner allocates virtual-fund claims first, using a
vectorized per-asset scale factor:

```text
source_capacity = abs(account signed holding)
virtual_demand  = sum(abs(requested virtual-fund signed quantity))
scale           = min(1, source_capacity / virtual_demand)
```

Each virtual fund receives:

```text
allocated_signed_quantity = requested_signed_quantity * scale
```

The direct account sleeve is the balancing residual:

```text
direct_account_sleeve = signed_account_holding - sum(virtual_fund_allocations)
```

The direct target is diagnostic intent. It is not included in the virtual-fund
fill denominator. This keeps opposite-signed direct targets from incorrectly
reducing virtual-fund allocations.

`strict_feasible` is a validation mode. If virtual-fund gross demand exceeds
available source capacity for any asset, the plan is marked infeasible and
must not be applied.

## Apply Flow

Apply only after inspecting a feasible or attributed plan:

```python
from msm.time_index.accounts import VirtualFundHoldings
from msm.services.accounts import apply_account_virtual_fund_allocation_plan

node = VirtualFundHoldings(config=VirtualFundHoldings.default_config())
frame = apply_account_virtual_fund_allocation_plan(
    plan,
    updater=node,
    run=True,
)
```

The apply step may create or reuse `VirtualFundTable` rows, creates the
holdings-set row, builds the `VirtualFundHoldingsStorage` frame, and optionally
publishes it through the TimeIndexTableUpdater.

See
`examples/msm/accounts/account_portfolio_full_workflow.py` for the complete
end-to-end account workflow. Run it with `--with-virtual-fund-allocation` to
extend the account-plus-portfolio workflow with a dry-run allocation plan, or
with `--apply-virtual-fund-allocation` to publish the resulting
`VirtualFundHoldings` rows after the dry-run plan is printed. The focused
`examples/msm/accounts/account_virtual_fund_allocation_example.py` script is a
thin wrapper around that same full workflow extension.

## Low-Level Publisher

`VirtualFund.allocate_from_account_holdings_set(...)` remains a low-level
explicit publisher. Use it only when the allocation quantities are already
known and policy-approved. It is not the allocation policy engine.
