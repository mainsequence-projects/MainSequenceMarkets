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

## Exposure, Sized Target And Holdings

Three different things describe a virtual fund (ADR 0054):

| What | Where | Unit | Who writes it |
| --- | --- | --- | --- |
| The exposure the account wants to a portfolio | `TargetPositionsStorage`, one row per portfolio | A share of NAV or an amount | The user, through the provider |
| The sized target: that exposure per asset | `AccountAllocationLinesStorage.target_quantity` | Units | The provider, at a sync |
| What each owner was assigned of the account's holdings | `AccountAllocationLinesStorage.assigned_quantity`, and `VirtualFundHoldingsStorage` for a fund | Units | ms-markets, at a sync |

A portfolio has weights, not units. So the account's target states exposure:

```text
PositionSetTable
  <- TargetPositionsStorage
       target_type = "portfolio"
       portfolio_uid -> PortfolioTable.uid
       weight_notional_exposure      a share of the account's NAV, or
       constant_notional_exposure    an amount
```

Writing an exposure to a portfolio creates the `VirtualFund` of that account and
portfolio, if it does not exist. A fund exists from the moment it is requested
and has no holdings until the first sync.

ms-markets reads no price and computes no NAV. Turning an exposure into units
needs prices, so it is the provider's work, and it sends the result with the
allocation. [Sizing Targets And Allocating](sizing_and_allocation.md) walks
through every step.

| Step | Needs prices | Who |
| --- | --- | --- |
| State the exposure | No | The user, through the provider |
| Record the exposure and create the fund | No | ms-markets |
| Publish the account's holdings | No | The provider |
| Size each fund into target units | Yes | The provider |
| Assign holdings to funds; record target and assigned units per owner | No | ms-markets |
| Read the deltas and trade them | Yes | The provider |

## Storage Shape

`VirtualFundTable` stores the account-owned allocation view:

```text
uid PK
unique_identifier unique
account_uid FK -> AccountTable.uid
target_portfolio_uid FK -> PortfolioTable.uid
```

`VirtualFundHoldingsSetTable` groups one allocation result. It points at the
account holdings snapshot it allocates, which makes it 1:1 with the sync:

```text
uid PK
virtual_fund_uid FK -> VirtualFundTable.uid
source_account_holdings_set_uid FK -> AccountHoldingsSetTable.uid
time_index
```

`VirtualFundHoldingsStorage` stores what each fund holds, keyed by:

```text
(time_index, virtual_fund_uid, asset_identifier)
```

The row stores a positive `allocated_quantity`, a first-class
`allocation_strategy`, and a signed `direction`. Short exposure is represented
with `direction = -1`, not a negative quantity. `allocation_strategy` is
`explicit` for a low-level publication and the policy id for an allocation.

`AccountAllocationLinesStorage` stores the record of each allocation: one row
per sync, owner and asset, keyed by:

```text
(time_index, holdings_set_uid, owner_type, owner_uid, asset_identifier)
```

| Column | Meaning |
| --- | --- |
| `time_index`, `holdings_set_uid` | The sync: the time and the `AccountHoldingsSet` that was allocated. One allocation per holdings snapshot |
| `owner_type`, `owner_uid` | Who the line belongs to: `fund` with the `VirtualFund` uid, or `direct` with the account's uid for what the account holds outside its funds |
| `asset_identifier` | The asset |
| `target_quantity`, `target_direction` | The owner's sized target, in units |
| `assigned_quantity`, `assigned_direction` | What the owner was assigned of the account's holdings |
| `allocation_strategy`, `extra_details` | The policy id; its version, the `PositionSet` and the plan digest |

The owner is general on purpose: a delta belongs to the sync, for a virtual fund
and for a direct asset target alike. The delta is not a column; it is read from
the row:

```text
delta = target_quantity * target_direction - assigned_quantity * assigned_direction
```

`GET /api/v1/account/{account_uid}/virtual-fund-allocations/` answers the lines
of one allocation, the latest by default, with `target`, `assigned` and `delta`.

## Planner Flow

ADR 0053 and ADR 0054 define the allocation of an account's holdings to its
virtual funds. The planner is a dry run: it computes a deterministic plan and
writes nothing.

```python
from msm.services.accounts import plan_account_virtual_fund_allocations

plan = plan_account_virtual_fund_allocations(
    position_set_uid=position_set.uid,
    valuation_time=holdings_time,
    sized_targets=[
        {
            "target_type": "portfolio",
            "target_uid": portfolio_a_uid,
            "positions": [
                {"asset_uid": aapl_uid, "quantity": 1_200, "direction": 1},
                {"asset_uid": msft_uid, "quantity": 400, "direction": 1},
            ],
        },
        {"target_type": "portfolio", "target_uid": portfolio_b_uid, "positions": [...]},
    ],
)
```

`sized_targets` gives the exposures of the `PositionSet` in units:

- every portfolio exposure must be sized, and so must an asset exposure stated
  as a share or an amount;
- an asset target stated as `single_asset_quantity` is already in units and is
  not sized;
- an empty `positions` list is a target sized to nothing;
- a target the `PositionSet` does not name is refused.

Any mismatch raises `AllocationError` `invalid_sized_targets` and lists every
problem.

The planner follows one deterministic path:

```text
PositionSetTable.uid
  -> AccountTargetAllocationTable.uid
  -> AccountHoldingsSetTable(account_uid, valuation_time)
  -> AccountHoldingsStorage rows
  -> TargetPositionsStorage rows        the exposures, matched with sized_targets
  -> AssetTable identity rows
```

The holdings set is the one captured at exactly `valuation_time`. The target is
the `PositionSet` the caller passes, used as it is. A target is in force from
its own `position_set_time` on, so a capture taken after the target was written
is allocated against it. A `PositionSet` written after `valuation_time` is
refused.

Without a `policy`, `proportional_attribution` runs with its default arguments.
To choose one, pass `policy={"id": ..., "version": ..., "arguments": {...}}`.

## What A Plan Answers

Every policy answers the same shape, in units. There is one line per owner and
asset, where the owner is a virtual fund or the direct account sleeve:

| Field | Meaning |
| --- | --- |
| `target` | What the owner should hold of the asset |
| `assigned` | What the owner gets |
| `delta` | `target - assigned`: positive when units are missing, negative when there are more than the target asks for |

Take an account that holds AAPL 1,000, MSFT 600, JNJ 1,000 and TSLA 1,640. It
wants 40% of its NAV in portfolio A (60% AAPL, 40% MSFT) and 300,000 in
portfolio B (50% MSFT, 50% JNJ). At the provider's prices the account is worth
1,000,000, and the provider sizes fund A at AAPL 1,200 and MSFT 400, and fund B
at MSFT 375 and JNJ 1,000:

| Owner | Asset | Target | Assigned | Delta |
| --- | --- | --- | --- | --- |
| Fund A | AAPL | 1,200 | 1,000 | +200 |
| Fund A | MSFT | 400 | 309.68 | +90.32 |
| Fund B | MSFT | 375 | 290.32 | +84.68 |
| Fund B | JNJ | 1,000 | 1,000 | 0 |
| Direct | TSLA | 0 | 1,640 | −1,640 |

- Every unit the account holds appears once: for each asset, the `assigned` of
  its lines adds up to the holding.
- `account_deltas` has one row per asset: what is `held`, the total `target` and
  their difference.
- A plan has no status and no deficits list. A shortfall is a positive delta.
- A target with no fund is planned too: every holding goes to the direct sleeve.

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
claims   = sum(abs(each fund's sized target))
scale    = min(1, capacity / claims)
fill     = target * scale
direct   = holding - sum(fills)
```

Every fund's claim on an asset gets the same scale; no fund has priority. Each
asset is handled on its own, so a fund short of one asset still gets all of
another. Direct targets do not compete with the funds; they are only measured
against what the funds leave.

Its one argument, `quantity_tolerance`, has a default of `1e-9`: a fill at or
below it counts as nothing assigned.

A shortfall is not refused. A provider that wants only a complete allocation
plans first and allocates only when no delta is positive.

## Apply Flow

```python
from msm.services.accounts import apply_account_virtual_fund_allocation_plan

result = apply_account_virtual_fund_allocation_plan(plan)
result.applied          # True when this call wrote the allocation
result.already_applied  # True when the same plan was already written
result.funds            # each fund's virtual_fund_uid and holdings_set_uid
```

The apply step writes, in one transaction:

- one holdings set for **every** fund of the target, pointing at the account
  holdings snapshot;
- one holdings row per fund and asset the fund was assigned;
- the allocation's lines: one per owner and asset, with the sized target and the
  assigned units, for every fund and for the account's direct part. A fund the
  account holds nothing of has its lines with nothing assigned, so its whole
  target reads as the delta. A target with no fund is recorded too.

`extra_details` records the policy version, the position set and the plan's
digest.

An applied allocation is account history:

- the same plan again writes nothing and answers `already_applied`;
- a different allocation of the same snapshot is refused (`allocation_exists`);
- a correction is a new holdings snapshot.

No fund is written for a portfolio retired at or before the plan's time
(ADR 0049).

## Markets API

An application without grants on `mainsequence.markets` allocates through the
Markets API. It sends the sized targets and no price:

| Route | `MarketsClient` method |
| --- | --- |
| `GET /api/v1/account/virtual-fund-allocation-policies/` | `virtual_fund_allocation_policies()` |
| `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/` | `virtual_fund_allocation_policy(policy_id)` |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/` | `plan_account_virtual_funds(...)` |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/` | `allocate_account_virtual_funds(...)` |
| `GET /api/v1/account/{account_uid}/virtual-fund-allocations/` | `account_virtual_fund_allocation(...)` |

The allocate route plans again from the same inputs and then writes. It never
accepts a plan from the client. Pass a plan's `plan_digest` to be sure nothing
changed since the caller saw it. The digest covers the sized targets, so other
targets than the plan's answer 409 `plan_changed`.

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
