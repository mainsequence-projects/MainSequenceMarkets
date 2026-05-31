# Accounts

Accounts are the owner identity layer for positions, target assignments,
execution routing, and fund tracking. The account registry itself is stored in
markets MetaTables. Account and fund holdings history is stored in DataNode
tables backed by registered `PlatformTimeIndexMetaData` storage classes, because
holdings are timestamped observations rather than static reference rows.

## What Is Stored Where

```text
MetaTable
  Row-oriented reference or configuration table registered from SQLAlchemy.
  AccountTable, AccountTargetPositionAssignmentTable, AccountGroupTable,
  AccountModelPortfolioTable, and FundTable are MetaTables.

PlatformTimeIndexMetaData
  SQLAlchemy storage class registered through the SDK/catalog bootstrap. It
  describes the published table shape: time index, dimension indexes, column
  dtypes, foreign keys, and storage identity. AccountHoldings and
  VirtualFundHoldings use registered storage classes; they do not create storage
  through `initialize_source_table`.
```

Do not confuse these layers. `Account.upsert(...)` writes one account registry
row. `AccountHoldings.run(...)` publishes timestamped holdings rows into a
DataNode table.

## API Surfaces

Use the typed row APIs for account MetaTable records:

```python
import datetime as dt

from msm.api.accounts import Account, AccountTargetPositionAssignment

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
    is_paper=True,
    account_is_active=True,
)

assignment = AccountTargetPositionAssignment.upsert(
    account_uid=account.uid,
    target_positions_time=dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
    position_set_uid="00000000-0000-0000-0000-000000000001",
)
```

Use the DataNode package for holdings:

```python
from msm.data_nodes.accounts import AccountHoldings

holdings_node = AccountHoldings(
    config=AccountHoldings.default_config(
        identifier="my_project.account_holdings",
    ),
)
holdings_node.set_account_holdings_frame(
    holdings_date="2026-05-28T00:00:00Z",
    account_uid=account.uid,
    positions=[
        {
            "unique_identifier": "BTC-USD",
            "quantity": 10.0,
            "extra_details": {"source": "example"},
        }
    ],
)
holdings_node.run(debug_mode=True, force_update=True)
```

`Account.pretty_print_positions(...)` formats an account holdings frame into the
columns operators usually need for a position check:

```python
positions = account.pretty_print_positions(updated_frame)
```

The printed table has `asset_uid`, `ticker`, `position_type`, and
`position_value`. The method resolves `asset_uid` from the canonical `Asset`
row, reads `ticker` from row `extra_details` when present, and keeps holdings
reads explicit by requiring the caller to pass the holdings frame.

The full workflow example is
`examples/accounts/create_and_insert_holdings.py`. It reuses the shared asset
example payloads from `examples/assets/utils` and account-specific payloads from
`examples/accounts/utils`.

There is no top-level `msm.accounts` shim. Import account rows from
`msm.api.accounts` and account holdings DataNodes from
`msm.data_nodes.accounts`.

## Account MetaTables

```text
                                      MetaTables
                                      ----------

+-------------------------------+
| AccountModelPortfolioTable    |  MetaTable: AccountModelPortfolio
|-------------------------------|
| uid PK                        |
| model_portfolio_name unique   |
| model_portfolio_description   |
| metadata_json                 |
+---------------+---------------+
                |
                | nullable FK from AccountGroupTable.account_model_portfolio_uid
                v
+-------------------------------+
| AccountGroupTable             |  MetaTable: AccountGroup
|-------------------------------|
| uid PK                        |
| group_name unique             |
| group_description             |
| account_model_portfolio_uid FK|
| metadata_json                 |
+-------------------------------+

+-------------------------------+
| AccountTable                  |  MetaTable: Account
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_name                  |
| is_paper                      |
| account_is_active             |
| holdings_data_node_uid        |
| metadata_json                 |
+---------------+---------------+
                |
                | account_uid FK, on delete cascade
                v
+-------------------------------+
| AccountTargetPositionAssign.  |  MetaTable: AccountTargetPositionAssignment
|-------------------------------|
| uid PK                        |
| account_uid FK -> Account.uid |
| target_positions_time UTC     |
| position_set_uid              |
| unique(account_uid,           |
|        target_positions_time) |
+-------------------------------+
```

`AccountTable.uid` is the canonical account identity used by other MetaTables and
DataNode rows. `unique_identifier` is the stable external business key used for
lookup and idempotent upserts. `holdings_data_node_uid` is optional metadata for
an account's associated holdings storage; it is not the account identity.

`AccountTargetPositionAssignmentTable` intentionally stays separate from
`AccountTable`. An account can be registered without a target-position binding,
and the binding can be replaced for a UTC `target_positions_time` without
rewriting the account row.

## Fund And Portfolio Relationship

Funds bind an account to a target portfolio. The account owns the execution or
custody side; the portfolio owns the target composition.

```text
                      MetaTables
                      ----------

+------------------+      target_account_uid FK       +----------------+
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

The account API lives in `msm.api.accounts`. Fund row APIs live in
`msm.api.portfolios` because funds are part of the portfolio workflow.

## Holdings DataNodes

Holdings are time-series-like observations. They are not MetaTables. A holdings
DataNode writes to a table described by a registered `PlatformTimeIndexMetaData`
storage class with a fixed index and column contract.

```text
                                    DataNode / PlatformTimeIndexMetaData
                                    ------------------------------------

+-------------------------------+       uses registered     +-----------------------------+
| AccountHoldings               |-------------------------->| AccountHoldingsStorage      |
| DataNode class                |                           | account_historical_holdings |
|-------------------------------|                           |-----------------------------|
| identifier, index contract,   |                           | time_index_name=time_index  |
| and dtype contract derive     |                           | index_names:                |
| from AccountHoldingsStorage.  |                           |  - time_index               |
|                               |                           |  - account_uid              |
| update() returns DataFrame    |                           |  - unique_identifier        |
+---------------+---------------+                           | records:                   |
                |                                           |  - holdings_set_uid uuid    |
                | publishes rows                            |  - is_trade_snapshot bool   |
                |                                           |  - unique_identifier string |
                v                                           |  - quantity float64         |
+-------------------------------+                           |  - target_trade_time        |
| Source table rows             |                           |    datetime64[ns, UTC]      |
|-------------------------------|                           |  - extra_details jsonb      |
| time_index                    |                           +-----------------------------+
| account_uid                   |
| unique_identifier             |
| holdings_set_uid              |
| quantity                      |
| target_trade_time             |
| extra_details                 |
+-------------------------------+
```

The row grain is one asset position for one account at one timestamp:

```text
unique row = (time_index, account_uid, unique_identifier)
```

`unique_identifier` is the held asset's `Asset.unique_identifier`. The holdings
table uses account ownership and asset identity as dimensions so callers can
query history by account, date range, and asset.

The holdings DataNode configuration does not carry `time_index_name`,
`index_names`, nullable columns, or dtype declarations. Those are storage
MetaTable fields on `AccountHoldingsStorage` / `FundHoldingsStorage`.

`VirtualFundHoldings` follows the same pattern for fund-level observations:

```text
+-------------------------------+       uses registered     +-----------------------------+
| VirtualFundHoldings           |-------------------------->| FundHoldingsStorage        |
| DataNode class                |                           | virtual_fund_historical...  |
|-------------------------------|                           |-----------------------------|
| identifier, index contract,   |                           | time_index_name=time_index  |
| and dtype contract derive     |                           | index_names:                |
| from FundHoldingsStorage.     |                           |  - time_index               |
|                               |                           |  - fund_uid                 |
|                               |                           |  - unique_identifier        |
+-------------------------------+                           | extra measure: target_weight|
                                                            +-----------------------------+
```

## End-To-End Flow

```text
1. Register account reference data

   Account.upsert(...)
     -> Account API row
     -> AccountTable MetaTable

2. Register assets held by the account

   Asset.upsert(...)
     -> AssetTable MetaTable

3. Build account holdings frame

   AccountHoldings.set_account_holdings_frame(...)
     -> build_account_holdings_frame(...)
     -> validates required columns and dtypes

4. Publish holdings

   AccountHoldings.run(...)
     -> uses registered PlatformTimeIndexMetaData storage
     -> writes rows to the DataNode source table

5. Read holdings

   AccountHoldings.get_holdings_history(...)
     -> queries by account_uid plus date filters
```

The registry and the historical observations stay separate:

```text
AccountTable MetaTable
  one row per account identity

AccountHoldings PlatformTimeIndexMetaData-backed source table
  many rows per account over time
```

## Registration Order

Register parent MetaTables before child MetaTables. A minimal account workflow
uses:

```python
import msm

msm.start_engine(models=["Asset", "Account"])
```

For target assignments, include the child table:

```python
msm.start_engine(models=["Account", "AccountTargetPositionAssignment"])
```

For funds, register account and portfolio dependencies first:

```python
msm.start_engine(models=["Account", "Portfolio", "Fund"])
```

The DataNode class itself does not need to be in the MetaTable model list. Its
storage class does. Register holdings storage through catalog/bootstrap before
constructing or running the DataNode. The registration path is
`PlatformTimeIndexMetaData.register(...)`; do not manually bind by UID or call
`initialize_source_table`.

## Extension Rules

Add static account reference data as MetaTables under `msm.models` and expose it
through typed rows under `msm.api`.

Add timestamped account or fund observations as DataNodes under
`msm.data_nodes.accounts`. Define the table contract with a
`PlatformTimeIndexMetaData` storage class in `msm.data_nodes.storage` and keep
the published row grain explicit.

Do not put holdings rows into `AccountTable`. Do not add static account fields to
`AccountHoldings`. The split is what keeps account identity stable while
holdings history grows over time.

## Related Concepts

- [Assets](../assets/index.md)
- [DataNodes](../assets/asset_indexed_data_nodes.md)
- [Portfolios](../portfolios/index.md)
- [Repositories](../repositories/index.md)
- [Services](../services/index.md)
