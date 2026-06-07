# Virtual Funds

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
portfolio weights or run portfolio DataNodes, but it does not own virtual-fund
identity or holdings storage.

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

The row stores a positive `allocated_quantity` and a signed `direction`.
Short exposure is represented with `direction = -1`, not a negative quantity.

## Planner Flow

ADR 0029 defines the account holdings to virtual-fund allocation planner. The
planner is a dry-run service: it computes a deterministic plan and performs no
writes.

```python
from msm.services.accounts import (
    AllocationPolicy,
    HoldingValuationInput,
    TargetQuantityDemand,
    plan_account_virtual_fund_allocations,
)

plan = plan_account_virtual_fund_allocations(
    position_set_uid=position_set.uid,
    source_account_holdings_set_uid=holdings_set.uid,
    account_uid=account.uid,
    valuation_time=workflow_time,
    valuation_asset_uid=usd_asset.uid,
    account_nav=640_000.0,
    source_holdings=[
        HoldingValuationInput(
            asset_uid=btc_asset.uid,
            asset_identifier=btc_asset.unique_identifier,
            quantity=10.0,
            direction=1,
        ),
    ],
    virtual_fund_demands=[
        TargetQuantityDemand(
            target_row_key="target-portfolio-btc",
            asset_uid=btc_asset.uid,
            asset_identifier=btc_asset.unique_identifier,
            requested_signed_quantity=5.0,
            direction=1,
            claim_uid="acct-main-model-vf",
            target_portfolio_uid=portfolio.uid,
        ),
    ],
    allocation_policy=AllocationPolicy(),
)
```

The production workflow resolves `source_holdings` and
`virtual_fund_demands` from `PositionSetTable`, `TargetPositionsStorage`,
portfolio weights, and valuation output before calling the pure planner.

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

## Valuation Resolver

The planner does not own pricing, derivative valuation, FX conversion, or NAV
calculation. A valuation resolver supplies valuation metrics and target
quantity demand when the workflow starts from notional targets.

The resolver is called with:

```text
requested_metrics = [{"name": "nav"}]
source_holdings
target_notional_demands
valuation_time
valuation_asset_uid
valuation_policy
```

`valuation_asset_uid` is an `AssetTable.uid`, not an ISO code or ticker. Any
currency mapping or provider-specific logic belongs inside the resolver.

The resolver returns totals and optional lines per asset, source row, or target
row. For account virtual-fund allocation, `nav` is the required metric.

## Apply Flow

Apply only after inspecting a feasible or attributed plan:

```python
from msm.data_nodes.accounts import VirtualFundHoldings
from msm.services.accounts import apply_account_virtual_fund_allocation_plan

node = VirtualFundHoldings(config=VirtualFundHoldings.default_config())
frame = apply_account_virtual_fund_allocation_plan(
    plan,
    data_node=node,
    run=True,
)
```

The apply step may create or reuse `VirtualFundTable` rows, creates the
holdings-set row, builds the `VirtualFundHoldingsStorage` frame, and optionally
publishes it through the DataNode.

## Low-Level Publisher

`VirtualFund.allocate_from_account_holdings_set(...)` remains a low-level
explicit publisher. Use it only when the allocation quantities are already
known and policy-approved. It is not the allocation policy engine.

