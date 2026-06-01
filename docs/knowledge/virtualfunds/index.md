# Virtual Funds

Virtual funds are portfolio-tracking entities that bind an account to a target
portfolio. They are not account identities. Accounts own custody or execution;
portfolios own target composition; funds connect the two for fund-level
holdings and workflow tracking.

## Scope

Virtual funds own:

- `FundTable` rows that link `target_account_uid` to `AccountTable.uid`.
- `FundTable` rows that link `target_portfolio_uid` to `PortfolioTable.uid`.
- `VirtualFundHoldings` DataNodes for fund-level holdings observations.
- `FundHoldingsStorage` as the storage contract for fund holdings history.

Virtual funds do not own account identity, account groups, account target
portfolio mandates, or account target-position sets.

## Fund MetaTable

```text
------------------+      target_account_uid FK       +----------------+
| AccountTable     |<-------------------------------+ | FundTable      |
| MetaTable        |                                  | MetaTable      |
| uid PK           |                                  | uid PK         |
+------------------+                                  | unique_id uniq |
                                                      | target_account |
+------------------+      target_portfolio_uid FK     | target_portf. |
| PortfolioTable   |<-------------------------------+ | metadata_json |
| MetaTable        |                                  +----------------+
| uid PK           |
+------------------+
```

The fund row API lives in `msm.api.portfolios` because funds are part of the
portfolio workflow:

```python
from msm.api.portfolios import Fund

fund = Fund.upsert(
    unique_identifier="fund-core",
    target_account_uid=account.uid,
    target_portfolio_uid=portfolio.uid,
)
```

## Fund Holdings DataNode

Fund holdings are time-series-like observations. They are not static fund rows.
`VirtualFundHoldings` writes to a table described by `FundHoldingsStorage`.

```text
                                    DataNode / PlatformTimeIndexMetaData
                                    ------------------------------------

+-------------------------------+       uses registered     +-----------------------------+
| VirtualFundHoldings           |-------------------------->| FundHoldingsStorage         |
| DataNode class                |                           | virtual_fund_historical...  |
|-------------------------------|                           |-----------------------------|
| identifier, index contract,   |                           | time_index_name=time_index  |
| and dtype contract derive     |                           | index_names:                |
| from FundHoldingsStorage.     |                           |  - time_index               |
|                               |                           |  - fund_uid                 |
| update() returns DataFrame    |                           |  - unique_identifier        |
+---------------+---------------+                           | records:                    |
                |                                           |  - holdings_set_uid uuid    |
                | publishes rows                            |  - is_trade_snapshot bool   |
                |                                           |  - unique_identifier string |
                v                                           |  - quantity float64         |
+-------------------------------+                           |  - target_weight float64    |
| Source table rows             |                           |  - target_trade_time        |
|-------------------------------|                           |    datetime64[ns, UTC]      |
| time_index                    |                           |  - extra_details jsonb      |
| fund_uid ---------------------+-------------------------->| FK -> FundTable.uid         |
| unique_identifier ------------+-------------------------->| FK -> AssetTable            |
| holdings_set_uid              |                           |       .unique_identifier    |
| quantity                      |                           +-----------------------------+
| target_weight                 |
| target_trade_time             |
| extra_details                 |
+-------------------------------+
```

The row grain is one asset position for one fund at one timestamp:

```text
unique row = (time_index, fund_uid, unique_identifier)
```

`unique_identifier` is the held asset's `AssetTable.unique_identifier`.
`FundHoldingsStorage` declares both `fund_uid -> FundTable.uid` and
`unique_identifier -> AssetTable.unique_identifier` as storage-level foreign
keys.

## Registration Order

Register parent tables before child tables:

```python
import msm

msm.start_engine(
    models=[
        "Asset",
        "Account",
        "Portfolio",
        "Fund",
        "FundHoldingsStorage",
    ]
)
```

The DataNode class itself does not need to be in the MetaTable model list. Its
storage class does. Register `FundHoldingsStorage` before constructing or
running `VirtualFundHoldings`.

## Related Concepts

- [Accounts](../accounts/index.md): account identity and account holdings.
- [Portfolios](../portfolios/index.md): portfolio configuration and canonical
  portfolio data.
- [Asset-Indexed DataNodes](../assets/asset_indexed_data_nodes.md): shared
  market DataNode conventions keyed by `AssetTable.unique_identifier`.
