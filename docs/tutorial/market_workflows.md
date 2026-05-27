# Market Workflows

These examples show the intended runtime boundary.

1. Use typed `msm.api` row APIs for market records.
2. Let row operations attach to already-registered MetaTables lazily.
3. Use explicit schema preflight only at application startup or when an example
   is demonstrating registration.
4. Use DataNode helpers for historical tables such as holdings and target
   positions.

## Runtime Setup

Production code normally assumes market MetaTables already exist. A row call
such as `Asset.upsert(...)` resolves the required registered table, caches the
runtime for the process, and then runs the operation. If the table is missing,
the error tells the caller to run explicit preflight or opt into development
auto-registration.

Explicit preflight remains available for applications that want startup-time
registration or verification:

```python
import msm

runtime = msm.create_schemas(models=["Asset"])
```

Schema creation does not take labels. Use `runtime.meta_tables`,
`runtime.meta_table_models`, and `runtime.data_nodes` after bootstrap when a
specific returned resource needs follow-up labeling or handling. The preflight
uses the Main Sequence logger at `info` level to report each MetaTable model
being registered, what context was created, and when a cached runtime is reused.

For externally managed tables, create/migrate the tables in application code and
call `register_markets_meta_tables(..., management_mode="external_registered")`.

Examples that should self-register use the platform namespace
`mainsequence.examples` through `MSM_AUTO_REGISTER_NAMESPACE` before importing
`msm.api`:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)
```

The returned runtime from explicit preflight still exposes table handles and
context for lower-level repository/service internals, but examples should not
pass those handles around for normal row CRUD.

## Assets And Categories

Start with assets before building reusable universes. Asset identity is the
stable contract consumed by holdings, target positions, pricing details, and
portfolio workflows.

```python
from msm.api.assets import Asset

btc = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)

btc_by_identifier = Asset.get_by_unique_identifier(
    unique_identifier="example-asset-btc",
)
btc_by_uid = Asset.get_by_uid(btc.uid)
crypto_assets = Asset.filter(
    unique_identifier_contains="example-asset-",
    asset_type="crypto",
    limit=20,
)
# Optional cleanup for temporary custom assets only:
# Asset.delete(btc.uid)
```

Do not delete assets during normal setup. Use cleanup only for temporary or
organization-owned custom assets. Shared public/mastered assets should remain
stable so downstream workflows do not lose their canonical identity.

See `examples/assets/asset_crud_workflow.py` for the focused workflow. It uses
example auto-registration for only the required `Asset` and `OpenFigiDetails`
MetaTables, creates temporary custom assets, resolves `BBG00FNFPQH4` through
OpenFIGI, writes an AssetSnapshot frame from the returned provider details, and
lists the created assets. Set the
Main Sequence secret `OPEN_FIGI_API_KEY` in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before running the
workflow. Cleanup is disabled by default.

## Asset Snapshots

`AssetSnapshot` is a DataNode, not a MetaTable. Build validated snapshot frames
or a configured node through `AssetSnapshot` methods. Construct the node first,
then bind rows whose payloads each carry their own `time_index`:

```python
from datetime import datetime, UTC

from msm.data_nodes.assets import AssetSnapshot

snapshot_node = AssetSnapshot().set_snapshots(
    {
        "time_index": datetime.now(UTC),
        "unique_identifier": "example-asset-btc",
        "ticker": "BTC",
    },
)
snapshot_frame = snapshot_node.run(debug_mode=True, force_update=True)
```

Markets DataNodes use the same identifier rule as MetaTables. With the default
markets namespace, logical identifiers stay bare, such as `Asset` and
`asset_snapshots`. With `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`,
the published identifiers become `mainsequence.examples.Asset` and
`mainsequence.examples.asset_snapshots`; the default DataNode `hash_namespace`
is also `mainsequence.examples`. Pass explicit `identifier` or `hash_namespace`
only when a test or experiment needs isolation.

Asset snapshot source tables have a canonical foreign key from
`unique_identifier` to `AssetTable.unique_identifier`, so the `Asset` MetaTable
must exist before a snapshot DataNode initializes its source table. In examples
that perform source-table initialization, run `msm.create_schemas(models=["Asset"])`
or use the example auto-registration namespace first.

Before the write path persists rows, `AssetSnapshot` checks the backend for the
incoming `(time_index, unique_identifier)` tuples and fails if any tuple already
exists. Publish corrections as a new timestamped snapshot instead of overwriting
the existing row.

See `examples/assets/asset_snapshot_workflow.py` for the focused DataNode
example.

When the universe itself should be a reusable platform object, create an asset
category and manage memberships separately:

```python
from msm.api.assets import Asset, AssetCategory

btc = Asset.upsert(unique_identifier="BTC", asset_type="crypto")
eth = Asset.upsert(unique_identifier="ETH", asset_type="crypto")
category = AssetCategory.upsert(
    unique_identifier="crypto-majors",
    display_name="Crypto Majors",
)
memberships = AssetCategory.replace_memberships(
    category_uid=category.uid,
    asset_uids=[btc.uid, eth.uid],
)
```

## Accounts, Funds, And Portfolios

```python
from msm.api.accounts import Account
from msm.api.portfolios import Fund, Portfolio

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
)
portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_name="24/7",
)
fund = Fund.upsert(
    unique_identifier="fund-core",
    target_account_uid=account.uid,
    target_portfolio_uid=portfolio.uid,
)
```

## Holdings And Target Positions

See `examples/api/typed_metatable_rows.py` for a compact example that uses the
typed row API across assets, categories, accounts, portfolios, funds,
instrument configuration, and an execution order manager.

```python
from uuid import uuid4

from msm.services import build_account_holdings_frame, build_target_positions_frame

holdings = build_account_holdings_frame(
    holdings_date="2026-05-25T00:00:00Z",
    account_uid=account.uid,
    positions=[
        {"unique_identifier": "BTC", "quantity": "1.0"},
        {"unique_identifier": "ETH", "quantity": "10.0"},
    ],
)

targets = build_target_positions_frame(
    target_positions_date="2026-05-25T00:00:00Z",
    position_set_uid=uuid4(),
    positions=[
        {"unique_identifier": "BTC", "weight_notional_exposure": "0.6"},
        {"unique_identifier": "ETH", "weight_notional_exposure": "0.4"},
    ],
)
```

The DataNode frame helpers validate the dynamic-table contract locally. The
actual table provisioning and writes remain generic TDAG/DataNode behavior.
