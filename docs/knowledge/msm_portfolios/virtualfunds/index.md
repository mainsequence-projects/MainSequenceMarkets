# Virtual Funds

Virtual funds are allocation views over real account holdings. They bind an
`Account` to a target `Portfolio`, then allocate part of one
`AccountHoldingsSet` into that portfolio workflow.

A virtual fund is not an `Asset`, not an account, and not custody. Account
holdings continue to store real asset rows only.

## Relationship

```text
+---------------------+        target_portfolio_uid        +---------------------+
| PortfolioTable      |<-----------------------------------| VirtualFundTable    |
| portfolio identity  |                                    | allocation identity |
+---------------------+                                    | account_uid         |
                                                           +----------+----------+
                                                                      |
                                                                      | account_uid
                                                                      v
+---------------------+        account_uid                +---------------------+
| AccountTable        |<-----------------------------------| AccountHoldingsSet |
| custody account     |                                    | source snapshot    |
+---------------------+                                    +----------+----------+
                                                                      |
                                                                      | source_account_holdings_set_uid
                                                                      v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsSetTable |
                                                           | allocation set identity     |
                                                           +-------------+---------------+
                                                                         |
                                                                         v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsStorage  |
                                                           | allocated_quantity          |
                                                           | direction                   |
                                                           | asset_identifier -> Asset   |
                                                           +-----------------------------+
```

`VirtualFundTable` stores identity only:

```text
+-------------------------------+
| VirtualFundTable              |
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_uid FK -> Account     |
| target_portfolio_uid FK       |
+-------------------------------+
```

`VirtualFundHoldingsSetTable` groups one allocation view from one source account
holdings set:

```text
+----------------------------------------------+
| VirtualFundHoldingsSetTable                  |
|----------------------------------------------|
| uid PK                                       |
| virtual_fund_uid FK -> VirtualFundTable.uid  |
| source_account_holdings_set_uid FK           |
| time_index                                   |
+----------------------------------------------+
```

`VirtualFundHoldingsStorage` stores the allocated exposure rows:

```text
unique row = (time_index, virtual_fund_uid, asset_identifier)
```

Records include:

- `virtual_fund_holdings_set_uid`
- `source_account_holdings_set_uid`
- `allocated_quantity`
- `direction`
- `target_trade_time`
- `extra_details`

`allocated_quantity` is a positive magnitude. `direction` is `1` for long and
`-1` for short. This mirrors account holdings, where `quantity` is positive and
`direction` carries the side.

## Allocation Bound

Before publishing virtual-fund allocation rows, the API validates the source
holdings set:

```text
sum(existing allocated_quantity)
+ sum(new allocated_quantity)
<= source account holdings quantity
```

The bound key is:

```text
(source_account_holdings_set_uid, asset_identifier, direction)
```

A short source holding only funds short virtual-fund allocations. A long source
holding only funds long virtual-fund allocations.

## API Flow

```python
from msm.api.accounts import AccountHoldingsSet
from msm_portfolios.api.virtual_funds import VirtualFund
from msm_portfolios.data_nodes import VirtualFundHoldings

holdings_set = AccountHoldingsSet.upsert(
    account_uid=account.uid,
    time_index=workflow_time,
)

virtual_fund = VirtualFund.upsert(
    unique_identifier="vf-core",
    account_uid=account.uid,
    target_portfolio_uid=portfolio.uid,
)

virtual_fund_node = VirtualFundHoldings()
allocation_frame = virtual_fund.allocate_from_account_holdings_set(
    source_account_holdings_set_uid=holdings_set.uid,
    allocation_time=workflow_time,
    allocations=[
        {
            "asset_identifier": "BTC",
            "allocated_quantity": 6,
            "direction": 1,
        },
    ],
    data_node=virtual_fund_node,
    run=True,
)
```

The helper creates a `VirtualFundHoldingsSetTable` row after validation, attaches
the allocation frame to the DataNode, and can run the DataNode when `run=True`.

## Registration Order

Register parent tables before child tables:

```python
import msm_portfolios

msm_portfolios.start_engine(
    models=[
        "AssetType",
        "Asset",
        "Account",
        "AccountHoldingsSet",
        "AccountHoldingsStorage",
        "Portfolio",
        "VirtualFund",
        "VirtualFundHoldingsSet",
        "VirtualFundHoldingsStorage",
    ]
)
```

The DataNode class itself does not need to be in the MetaTable model list. Its
storage class does. Register `VirtualFundHoldingsStorage` before constructing or
running `VirtualFundHoldings`.

## Related Concepts

- [Accounts](../../msm/accounts/index.md): account identity and account holdings.
- [Portfolios](../portfolios/index.md): portfolio configuration and canonical
  portfolio data.
- [Asset-Indexed DataNodes](../../msm/assets/asset_indexed_data_nodes.md):
  shared market DataNode conventions keyed by `AssetTable.unique_identifier`.
