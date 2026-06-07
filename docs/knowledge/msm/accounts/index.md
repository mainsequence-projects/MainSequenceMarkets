# Accounts

Accounts are the owner identity layer for holdings, account groups, allocation
model tracking, target position sets, and execution routing.
The account registry and target-allocation relationships are stored in markets
MetaTables. Account holdings history and target position rows are stored in
DataNode tables backed by registered `PlatformTimeIndexMetaTable` storage
classes, because those rows are timestamped observations rather than static
reference records.

## What Is Stored Where

```text
MetaTable
  Row-oriented reference or configuration table registered from SQLAlchemy.
  AccountTable, AccountGroupTable, AccountAllocationModelTable,
  AccountTargetAllocationTable, and PositionSetTable are MetaTables.

PlatformTimeIndexMetaTable
  SQLAlchemy storage class registered through the SDK migration/catalog lifecycle. It
  describes the published table shape: time index, dimension indexes, column
  dtypes, foreign keys, and storage identity. AccountHoldings use registered
  core `msm` storage classes. Account target-allocation exposure rows also use
  a core `msm` storage class, even when one target references a portfolio sleeve.
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
    AccountAllocationModel,
    AccountTargetAllocation,
    PositionSet,
)
from msm.api.assets import Asset
from msm.api.portfolios import Portfolio
from msm.services import build_target_positions_frame

allocation_model = AccountAllocationModel.upsert(
    allocation_model_name="balanced-model",
    allocation_model_description="Balanced model tracked by several accounts.",
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

btc_asset = Asset.upsert(unique_identifier="BTC-USD", asset_type="crypto")

target_allocation = AccountTargetAllocation.upsert(
    unique_identifier="acct-main-balanced-target",
    account_uid=account.uid,
    account_allocation_model_uid=allocation_model.uid,
    display_name="Main account balanced target",
)

position_set = PositionSet.upsert(
    account_target_allocation_uid=target_allocation.uid,
    position_set_time=dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
)

portfolio_sleeve = Portfolio.upsert(unique_identifier="btc-eth-sleeve")

target_positions = build_target_positions_frame(
    target_positions_date=position_set.position_set_time,
    position_set_uid=position_set.uid,
    positions=[
        {
            "target_type": "asset",
            "target_uid": btc_asset.uid,
            "asset_uid": btc_asset.uid,
            "weight_notional_exposure": 0.6,
        },
        {
            "target_type": "portfolio",
            "target_uid": portfolio_sleeve.uid,
            "portfolio_uid": portfolio_sleeve.uid,
            "weight_notional_exposure": 0.4,
        },
    ],
)
```

Use the DataNode package for holdings:

```python
from msm.data_nodes.accounts import AccountHoldings

holdings_node = AccountHoldings(
    config=AccountHoldings.default_config(),
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
row, reads `ticker` from row `extra_details` when present, and reports quantity
positions as signed exposure (`quantity * direction`). Holdings reads remain
explicit by requiring the caller to pass the holdings frame. Do not pass the raw
`AccountHoldings.run(...)` tuple; unpack it and pass the DataFrame.

The full workflow example is
`examples/msm/accounts/account_portfolio_full_workflow.py`. By default it first
prepares the reusable portfolio interpolation schema, then chains the reusable
equal-weight portfolio workflow. The account example reuses the resulting
`Portfolio` row as a target sleeve, publishes `AssetSnapshot` rows with
canonical ticker and name metadata, creates two accounts, assigns both to one
account group, and adds target allocations for those accounts plus the portfolio
example's allocation account. Each account-owned target relationship points at
the same reusable `AccountAllocationModel`, and each `PositionSet` publishes one
direct asset target row with `target_type="asset"` plus one portfolio target row
with `target_type="portfolio"`. The example then publishes two-asset account
holdings and pretty-prints positions for each standalone account. Pass
`--skip-schema-prep` only when the configured portfolio interpolation table has
already been migrated. Pass
`--standalone-target-sleeve` or call
`run_account_portfolio_full_workflow(use_portfolio_example=False)` only when
testing the account path without chaining the portfolio example.

There is no top-level `msm.accounts` shim. Import account rows from
`msm.api.accounts` and account holdings DataNodes from
`msm.data_nodes.accounts`.

## Account MetaTables

```text
                         Account Reference MetaTables
                         ---------------------------

+-------------------------------+          +-------------------------------+
| AccountGroupTable             |          | AccountAllocationModelTable    |
| MetaTable: AccountGroup       |          | MetaTable: AccountAllocation  |
|                               |          | Model                         |
|-------------------------------|          |-------------------------------|
| uid PK                        |          | uid PK                        |
| group_name unique             |          | allocation_model_name unique   |
| group_description             |          | allocation_model_description   |
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
+-------------------------------+      account_allocation_model_uid FK
| AccountTargetAllocationTable   |<----------------------------------+
| MetaTable: AccountTarget      |
| Allocation                    |
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_uid FK -> Account.uid |
| account_allocation_model_uid   |
| display_name                  |
| is_active                     |
| source                        |
| metadata_json                 |
+---------------+---------------+
                |
                | account_target_allocation_uid FK, on delete cascade
                v
+-------------------------------+
| PositionSetTable              |
| MetaTable: PositionSet        |
|-------------------------------|
| uid PK                        |
| account_target_allocation_uid  |
| position_set_time UTC         |
| names one target snapshot;    |
| exposure rows are below       |
| source                        |
| metadata_json                 |
| unique(account_target_alloc., |
|        position_set_time)     |
+---------------+---------------+
                |
                | position_set_uid FK
                v
+-------------------------------+
| TargetPositionsStorage        |
| DynamicTableMetaData /        |
| PlatformTimeIndexMetaTable     |
| owner: msm                    |
|-------------------------------|
| time_index                    |
| position_set_uid              |
| target_type asset/portfolio   |
| target_uid                    |
| asset_uid nullable FK         |
| portfolio_uid nullable FK     |
| weight_notional_exposure      |
| constant_notional_exposure    |
| single_asset_quantity         |
| exactly one exposure required |
+------------+------------------+
             |                  |
             | asset_uid FK     | portfolio_uid FK
             v                  v
+-------------------------------+        +-------------------------------+
| AssetTable                    |        | PortfolioTable                |
| MetaTable: Asset              |        | MetaTable: Portfolio          |
| owner: msm                    |        | owner: msm                    |
|-------------------------------|        |-------------------------------|
| uid PK                        |        | uid PK                        |
| unique_identifier unique      |        | unique_identifier unique      |
+-------------------------------+        +-------------------------------+
```

`AccountTable.uid` is the canonical account identity used by other MetaTables and
DataNode rows. `unique_identifier` is the stable external business key used for
lookup and idempotent upserts. `account_group_uid` is optional membership in one
account group. `holdings_data_node_uid` is optional metadata for an account's
associated holdings storage; it is not the account identity. Account allocation
model tracking does not live on `AccountTable`; it lives on
`AccountTargetAllocationTable`.

`AccountGroupTable` and `AccountAllocationModelTable` are independent registries.
An account group does not point to an account allocation model. Group membership
lives on `AccountTable`; allocation-model tracking lives on
`AccountTargetAllocationTable`.

`AccountAllocationModelTable` is the reusable reference model an account can
track. It does not itself store timestamped positions. Concrete target positions
are versioned through `AccountTargetAllocationTable` and `PositionSetTable`:

1. `AccountTargetAllocationTable` says which account is tracking which account
   allocation model.
2. `PositionSetTable` names one concrete target snapshot for that account target
   allocation at a UTC `position_set_time`.
3. `TargetPositionsStorage` stores actual target exposure rows in
   core `msm`, points back to `PositionSetTable.uid` with
   `position_set_uid`, and references exactly one concrete target:
   `asset_uid -> AssetTable.uid` for direct asset exposure or
   `portfolio_uid -> PortfolioTable.uid` for portfolio-sleeve exposure.

This keeps account identity, account grouping, allocation-model intent, and
timestamped target rows in separate places.

## Holdings DataNodes

Holdings are time-series-like observations. They are not MetaTables. A holdings
DataNode writes to a table described by a registered `PlatformTimeIndexMetaTable`
storage class with a fixed index and column contract.

```text
                                    DataNode / PlatformTimeIndexMetaTable
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

   AccountAllocationModel.upsert(...)
     -> AccountAllocationModel API row
     -> AccountAllocationModelTable MetaTable

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
     -> uses registered PlatformTimeIndexMetaTable storage
     -> writes rows to the DataNode source table

5. Read holdings

   AccountHoldings.get_holdings_history(...)
     -> queries by account_uid plus date filters
```

The registry and the historical observations stay separate:

```text
AccountTable MetaTable
  one row per account identity

AccountHoldings PlatformTimeIndexMetaTable-backed source table
  many rows per account over time
```

## Registration Order

Register parent MetaTables before child MetaTables. A minimal account workflow
uses:

```python
import msm

msm.start_engine(models=["Asset", "AccountAllocationModel", "AccountGroup", "Account"])
```

Target portfolios and target position storage attach through core
`msm.start_engine(...)` because `PortfolioTable` is core portfolio identity and
`TargetPositionsStorage` is account target-allocation storage:

```python
import msm

msm.start_engine(
    models=[
        "AccountAllocationModel",
        "AccountGroup",
        "Account",
        "AccountTargetAllocation",
        "PositionSet",
        "Portfolio",
        "TargetPositionsStorage",
    ]
)
```

The DataNode class itself does not need to be in the MetaTable model list. Its
storage class does. Add holdings storage to the migration model registry, run
the SDK migration flow, and attach runtime with `msm.start_engine(...)` before
constructing or running the DataNode. Do not call
`PlatformTimeIndexMetaTable.register(...)`, manually bind by UID, or call
`initialize_source_table`.

## Extension Rules

Add static account reference data as MetaTables under `msm.models` and expose it
through typed rows under `msm.api`.

Add timestamped account or fund observations as DataNodes under
`msm.data_nodes.accounts`. Define the table contract with a
`PlatformTimeIndexMetaTable` storage class in a concept-owned `msm.data_nodes.*.storage`
module and keep
the published row grain explicit.

Add account target-position exposure rows that can point at portfolios under
core `msm`. Core `msm` owns the account registry, `PositionSetTable`,
`PortfolioTable`, `TargetPositionsStorage`, and the target-position frame
builders. Portfolio workflows can consume these rows, but they do not own the
account allocation table.

Do not put holdings rows into `AccountTable`. Do not add static account fields to
`AccountHoldings`. The split is what keeps account identity stable while
holdings history grows over time.

## Related Concepts

- [Assets](../assets/index.md)
- [DataNodes](../assets/asset_indexed_data_nodes.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
- [Repositories](../repositories/index.md)
- [Services](../services/index.md)
