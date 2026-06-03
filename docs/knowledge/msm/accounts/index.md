# Accounts

Accounts are the owner identity layer for holdings, account groups, model
portfolio tracking, target position sets, and execution routing.
The account registry and target-portfolio relationships are stored in markets
MetaTables. Account holdings history and target position rows are stored in
DataNode tables backed by registered `PlatformTimeIndexMetaData` storage
classes, because those rows are timestamped observations rather than static
reference records.

## What Is Stored Where

```text
MetaTable
  Row-oriented reference or configuration table registered from SQLAlchemy.
  AccountTable, AccountGroupTable, AccountModelPortfolioTable,
  AccountTargetPortfolioTable, and PositionSetTable are MetaTables.

PlatformTimeIndexMetaData
  SQLAlchemy storage class registered through the SDK migration/catalog lifecycle. It
  describes the published table shape: time index, dimension indexes, column
  dtypes, foreign keys, and storage identity. AccountHoldings and
  TargetPositionsStorage use registered storage classes; they do not create
  storage through `initialize_source_table`.
```

Do not confuse these layers. `Account.upsert(...)` writes one account registry
row. `AccountHoldings.run(...)` publishes timestamped holdings rows into a
DataNode table.

## API Surfaces

Use the typed row APIs for account MetaTable records:

```python
import datetime as dt

from msm.api.accounts import (
    Account,
    AccountGroup,
    AccountModelPortfolio,
    AccountTargetPortfolio,
    PositionSet,
)
from msm.services import build_target_positions_frame

model_portfolio = AccountModelPortfolio.upsert(
    model_portfolio_name="balanced-model",
    model_portfolio_description="Balanced model tracked by several accounts.",
)

account_group = AccountGroup.upsert(
    group_name="high-risk-accounts",
    group_description="Accounts grouped by risk bucket.",
)

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
    is_paper=True,
    account_is_active=True,
    account_group_uid=account_group.uid,
)

target_portfolio = AccountTargetPortfolio.upsert(
    unique_identifier="acct-main-balanced-target",
    account_uid=account.uid,
    account_model_portfolio_uid=model_portfolio.uid,
    display_name="Main account balanced target",
)

position_set = PositionSet.upsert(
    account_target_portfolio_uid=target_portfolio.uid,
    position_set_time=dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
)

target_positions = build_target_positions_frame(
    target_positions_date=position_set.position_set_time,
    position_set_uid=position_set.uid,
    positions=[
        {"asset_identifier": "BTC-USD", "weight_notional_exposure": 1.0},
    ],
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
            "asset_identifier": "BTC-USD",
            "quantity": 10.0,
            "extra_details": {"ticker": "BTC"},
        }
    ],
)
error_on_last_update, updated_frame = holdings_node.run(
    debug_mode=True,
    force_update=True,
)
if error_on_last_update:
    raise RuntimeError("Account holdings update failed.")
```

`Account.pretty_print_positions(...)` formats an account holdings frame into the
columns operators usually need for a position check:

```python
positions = account.pretty_print_positions(updated_frame)
```

The printed table has `asset_uid`, `ticker`, `position_type`, and
`position_value`. The method resolves `asset_uid` from the canonical `Asset`
row, reads `ticker` from row `extra_details` when present, and keeps holdings
reads explicit by requiring the caller to pass the holdings frame. Do not pass
the raw `AccountHoldings.run(...)` tuple; unpack it and pass the DataFrame.

The full workflow example is `examples/msm/accounts/account_workflow.py`. It creates
two crypto assets, publishes `AssetSnapshot` rows with canonical ticker and name
metadata, creates two accounts, assigns both to one account group, points both
account-specific target portfolio relationships at the same reusable
`AccountModelPortfolio`, publishes two-asset target position rows for each
`PositionSet`, publishes two-asset account holdings, and pretty-prints positions
for each account. It reuses the shared asset example payloads from
`examples/msm/assets/utils` and account-specific payloads from
`examples/msm/accounts/utils`.

There is no top-level `msm.accounts` shim. Import account rows from
`msm.api.accounts` and account holdings DataNodes from
`msm.data_nodes.accounts`.

## Account MetaTables

```text
                         Account Reference MetaTables
                         ---------------------------

+-------------------------------+          +-------------------------------+
| AccountGroupTable             |          | AccountModelPortfolioTable    |
| MetaTable: AccountGroup       |          | MetaTable: AccountModelPortf. |
|-------------------------------|          |-------------------------------|
| uid PK                        |          | uid PK                        |
| group_name unique             |          | model_portfolio_name unique   |
| group_description             |          | model_portfolio_description   |
| metadata_json                 |          | metadata_json                 |
+---------------+---------------+          +---------------+---------------+
                ^
                | nullable account_group_uid FK
                |
+---------------+---------------+
| AccountTable                  |
| MetaTable: Account            |
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_name                  |
| is_paper                      |
| account_is_active             |
| account_group_uid FK          |
| holdings_data_node_uid        |
| metadata_json                 |
+---------------+---------------+
                                |
                                | account_uid FK, on delete cascade
                                v
+-------------------------------+      account_model_portfolio_uid FK
| AccountTargetPortfolioTable   |<----------------------------------+
| MetaTable: AccountTargetPortf.|
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_uid FK -> Account.uid |
| account_model_portfolio_uid   |
| display_name                  |
| is_active                     |
| source                        |
| metadata_json                 |
+---------------+---------------+
                |
                | account_target_portfolio_uid FK, on delete cascade
                v
+-------------------------------+
| PositionSetTable              |
| MetaTable: PositionSet        |
|-------------------------------|
| uid PK                        |
| account_target_portfolio_uid  |
| position_set_time UTC         |
| names one target snapshot;    |
| exposure rows are below       |
| source                        |
| metadata_json                 |
| unique(account_target_portf., |
|        position_set_time)     |
+---------------+---------------+
                |
                | position_set_uid FK
                v
+-------------------------------+
| TargetPositionsStorage        |
| DynamicTableMetaData /        |
| PlatformTimeIndexMetaData     |
|-------------------------------|
| time_index                    |
| position_set_uid              |
| asset_identifier FK           |
|  -> Asset.unique_identifier   |
| weight_notional_exposure      |
| constant_notional_exposure    |
| single_asset_quantity         |
| exactly one exposure required |
+-------------------------------+
                |
                | asset_identifier FK
                v
+-------------------------------+
| AssetTable                    |
| MetaTable: Asset              |
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
+-------------------------------+
```

`AccountTable.uid` is the canonical account identity used by other MetaTables and
DataNode rows. `unique_identifier` is the stable external business key used for
lookup and idempotent upserts. `account_group_uid` is optional membership in one
account group. `holdings_data_node_uid` is optional metadata for an account's
associated holdings storage; it is not the account identity. Account model
portfolio tracking does not live on `AccountTable`; it lives on
`AccountTargetPortfolioTable`.

`AccountGroupTable` and `AccountModelPortfolioTable` are independent registries.
An account group does not point to an account model portfolio. Group membership
lives on `AccountTable`; model-portfolio tracking lives on
`AccountTargetPortfolioTable`.

`AccountModelPortfolioTable` is the reusable reference model an account can
track. It does not itself store timestamped positions. Concrete target positions
are versioned through `AccountTargetPortfolioTable` and `PositionSetTable`:

1. `AccountTargetPortfolioTable` says which account is tracking which account
   model portfolio.
2. `PositionSetTable` names one concrete target snapshot for that account target
   portfolio at a UTC `position_set_time`.
3. `TargetPositionsStorage` stores the actual asset exposure rows, points back
   to `PositionSetTable.uid` with `position_set_uid`, and points to
   `AssetTable.unique_identifier` with `asset_identifier`.

This keeps account identity, account grouping, model-portfolio intent, and
timestamped target rows in separate places.

## Holdings DataNodes

Holdings are time-series-like observations. They are not MetaTables. A holdings
DataNode writes to a table described by a registered `PlatformTimeIndexMetaData`
storage class with a fixed index and column contract.

```text
                                    DataNode / PlatformTimeIndexMetaData
                                    ------------------------------------

+-------------------------------+       uses registered     +-----------------------------+
| AccountHoldings               |-------------------------->| AccountHoldingsStorage      |
| DataNode class                |                           | AccountHoldingsTS           |
|-------------------------------|                           |-----------------------------|
| identifier, index contract,   |                           | time_index_name=time_index  |
| and dtype contract derive     |                           | index_names:                |
| from AccountHoldingsStorage.  |                           |  - time_index               |
|                               |                           |  - account_uid              |
| update() returns DataFrame    |                           |  - asset_identifier         |
+---------------+---------------+                           | records:                   |
                |                                           |  - holdings_set_uid uuid    |
                | publishes rows                            |  - is_trade_snapshot bool   |
                |                                           |  - asset_identifier string  |
                v                                           |  - quantity float64         |
                                                            |  - direction int16          |
+-------------------------------+                           |  - target_trade_time        |
| Source table rows             |                           |    datetime64[ns, UTC]      |
|-------------------------------|                           |  - extra_details jsonb      |
| time_index                    |                           |-----------------------------|
| account_uid ------------------+-------------------------->| FK -> AccountTable.uid      |
| asset_identifier -------------+-------------------------->| FK -> AssetTable            |
| holdings_set_uid -------------+-------------------------->| FK -> AccountHoldingsSet    |
| quantity                      |                           +-----------------------------+
| direction                     |
| target_trade_time             |
| extra_details                 |
+-------------------------------+
```

The row grain is one asset position for one account at one timestamp:

```text
unique row = (time_index, account_uid, asset_identifier)
```

`asset_identifier` is the held asset's `Asset.unique_identifier`.
`holdings_set_uid` references `AccountHoldingsSetTable.uid`, which names the
source account snapshot. `quantity` is always a positive magnitude and
`direction` carries side: `1` for long, `-1` for short. The signed exposure is
`quantity * direction`.

The holdings storage MetaTable declares `account_uid -> AccountTable.uid`,
`asset_identifier -> AssetTable.unique_identifier`, and
`holdings_set_uid -> AccountHoldingsSetTable.uid` as storage-level foreign keys
so callers can query history by account, date range, holdings set, and asset
without duplicating relationship metadata on the DataNode configuration.

The holdings DataNode configuration does not carry `time_index_name`,
`index_names`, nullable columns, or dtype declarations. Those are storage
MetaTable fields on `AccountHoldingsStorage`.

Virtual-fund allocation holdings belong to the
[Virtual Funds](../../msm_portfolios/virtualfunds/index.md) knowledge page.

## End-To-End Flow

```text
1. Register account reference data

   AccountModelPortfolio.upsert(...)
     -> AccountModelPortfolio API row
     -> AccountModelPortfolioTable MetaTable

   AccountGroup.upsert(...)
     -> AccountGroup API row
     -> AccountGroupTable MetaTable

   Account.upsert(...)
     -> Account API row
     -> links to group by UID when provided
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

msm.start_engine(models=["Asset", "AccountModelPortfolio", "AccountGroup", "Account"])
```

For target portfolios and target position sets, include the child tables and
the target-position storage contract:

```python
msm.start_engine(
    models=[
        "AccountModelPortfolio",
        "AccountGroup",
        "Account",
        "AccountTargetPortfolio",
        "PositionSet",
        "TargetPositionsStorage",
    ]
)
```

The DataNode class itself does not need to be in the MetaTable model list. Its
storage class does. Add holdings storage to the migration model registry, run
the SDK migration flow, and attach runtime with `msm.start_engine(...)` before
constructing or running the DataNode. Do not call
`PlatformTimeIndexMetaData.register(...)`, manually bind by UID, or call
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
- [Portfolios](../../msm_portfolios/portfolios/index.md)
- [Repositories](../repositories/index.md)
- [Services](../services/index.md)
