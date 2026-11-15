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

[Sizing Targets And Allocating](sizing_and_allocation.md) walks through every
step with a sizing rule for stocks, futures and options.

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
explicit publications use `explicit`; rows written by an allocation use the
policy id, such as `proportional_attribution`.

## Planner Flow

ADR 0053 defines the allocation of an account's holdings to its virtual funds.
The planner is a dry-run service: it computes a deterministic plan and performs
no writes.

Use the canonical account target snapshot path. Do not pass a raw account UID,
raw holdings-set UID, raw source holdings, or raw target rows into the public
planner.

```python
from msm.services.accounts import plan_account_virtual_fund_allocations

plan = plan_account_virtual_fund_allocations(
    position_set_uid=position_set.uid,
    valuation_time=workflow_time,
)
```

Without a `policy`, `proportional_attribution` runs with its default arguments.
To choose one, pass `policy={"id": ..., "version": ..., "arguments": {...}}`.

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

The holdings set is the one captured at exactly `valuation_time`. The target is
the `PositionSet` the caller passes, used as it is. A target is in force from
its own `position_set_time` on, so a capture taken after the target was written
is allocated against it: plan it with the later capture's `valuation_time` and
the earlier `position_set_uid`. A `PositionSet` written after `valuation_time`
is refused, since it cannot apply to holdings captured before it.

Core `msm` owns the account and virtual-fund allocation logic, and it does not
import `msm_portfolios`.

## What A Plan Answers

Every policy answers the same shape, in units. There is one line per owner and
asset, where the owner is a virtual fund or the direct account sleeve:

| Field | Meaning |
| --- | --- |
| `target` | What the owner should hold of the asset |
| `assigned` | What the owner gets |
| `delta` | `target - assigned`: positive when units are missing, negative when there are more than the target asks for |

Take an account that holds AAPL 1,100, MSFT 600, JNJ 750 and TSLA 1,100, with
fund A's basket at AAPL 1,000 and MSFT 500, and fund B's at MSFT 300 and JNJ 750:

| Owner | Asset | Target | Assigned | Delta |
| --- | --- | --- | --- | --- |
| Fund A | AAPL | 1,000 | 1,000 | 0 |
| Fund A | MSFT | 500 | 375 | +125 |
| Fund B | MSFT | 300 | 225 | +75 |
| Fund B | JNJ | 750 | 750 | 0 |
| Direct | AAPL | 0 | 100 | −100 |
| Direct | TSLA | 0 | 1,100 | −1,100 |

- Every unit the account holds appears once: for each asset, the `assigned` of
  its lines adds up to the holding.
- `account_deltas` has one row per asset: what is `held`, the total `target` and
  their difference. Here AAPL −100, MSFT +200, JNJ 0 and TSLA −1,100. No policy
  can change it; a policy only decides how a shortfall is spread between funds.
- The target is the full picture. An asset the account holds that no target
  names has a target of zero. Anything the account should keep outside its
  funds, cash included, is written as a direct target.
- A plan has no status and no deficits list. A shortfall is a positive account
  delta.
- A target with no fund is planned too: every holding goes to the direct sleeve.
- Deltas are computed, never stored. ms-markets reports them; acting on them is
  the provider's decision.

## Allocation Policies

Policies live in a registry. Each has an id, a version and an arguments class,
and its description is generated from that class, which also validates a
request's arguments. A change to an argument, a bound, a default or a behaviour
bumps the version, and a request built against another version is refused.

```python
from msm.services.accounts import ALLOCATION_POLICIES, describe_allocation_policy

for policy in ALLOCATION_POLICIES:
    print(describe_allocation_policy(policy)["arguments_schema"])
```

The registry has one policy, `proportional_attribution`. For each asset:

```text
capacity = abs(holding)
claims   = sum(abs(each fund's claim))
scale    = min(1, capacity / claims)
fill     = claim * scale
direct   = holding - sum(fills)
```

Every fund's claim on an asset gets the same scale; no fund has priority. Each
asset is handled on its own, so a fund short of one asset still gets all of
another. Direct targets do not compete with the funds; they are only measured
against what the funds leave.

Its one argument, `quantity_tolerance`, has a default of `1e-9`: a fill at or
below it is not written.

A shortfall is not refused. A provider that wants only a complete allocation
plans first and allocates only when no account delta is positive.

## Apply Flow

```python
from msm.services.accounts import apply_account_virtual_fund_allocation_plan

result = apply_account_virtual_fund_allocation_plan(plan)
result.applied          # True when this call wrote the allocation
result.already_applied  # True when the same plan was already written
result.funds            # each fund's virtual_fund_uid and holdings_set_uid
```

The apply step writes the virtual funds, one holdings set per fund and the
holdings rows in one transaction, so a holdings set never exists without its
rows. It writes one row per fund fill above the tolerance: a positive
`allocated_quantity`, a `direction`, and the policy id as `allocation_strategy`.
`extra_details` records the policy version, the position set and the plan's
digest.

An applied allocation is account history:

- the same plan again writes nothing and answers `already_applied`;
- a different allocation of the same snapshot is refused (`allocation_exists`);
- a correction is a new holdings snapshot.

No fund is written for a portfolio retired at or before the plan's time
(ADR 0049). A plan that gives no fund any units has nothing to write and is
refused (`nothing_to_apply`).

## Markets API

An application without grants on `mainsequence.markets` allocates through the
Markets API, and sends no market data to do so:

| Route | `MarketsClient` method |
| --- | --- |
| `GET /api/v1/account/virtual-fund-allocation-policies/` | `virtual_fund_allocation_policies()` |
| `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/` | `virtual_fund_allocation_policy(policy_id)` |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/` | `plan_account_virtual_funds(...)` |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/` | `allocate_account_virtual_funds(...)` |

The allocate route plans again from the same inputs and then writes. It never
accepts a plan from the client. Pass a plan's `plan_digest` to be sure nothing
changed since the caller saw it; a different recomputed plan answers 409
`plan_changed`.

See `examples/msm/accounts/account_portfolio_full_workflow.py` for the complete
end-to-end account workflow. Run it with `--with-virtual-fund-allocation` to
extend the account-plus-portfolio workflow with a dry-run allocation plan, or
with `--apply-virtual-fund-allocation` to write the allocation after the plan is
printed. The focused
`examples/msm/accounts/account_virtual_fund_allocation_example.py` script is a
thin wrapper around that same full workflow extension.

## Low-Level Publisher

`VirtualFund.allocate_from_account_holdings_set(...)` remains a low-level
explicit publisher. Use it only when the allocation quantities are already
known and policy-approved. It is not the allocation policy engine.
