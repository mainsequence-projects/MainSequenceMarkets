# Market Workflows

These examples show the intended runtime boundary.

1. Register the markets SQLAlchemy models as MetaTables.
2. Build a `MarketsRepositoryContext` from the returned MetaTable UID mapping.
3. Use services for market records.
4. Use DataNode helpers for historical tables such as holdings and target
   positions.

## Register Tables

```python
import msm

runtime = msm.start(
    labels=["markets"],
)

context = runtime.context
```

`msm.start(...)` is intended to run once per Python process, before importing
MetaTable-backed `msm.models`, repositories, or services. It performs the table
registration preflight and caches the resulting runtime. Repeating the same call
returns the cached runtime; changing startup arguments later raises because the
MetaTable namespace and SQLAlchemy table mapping are already fixed.

For externally managed tables, create/migrate the tables in application code and
call `register_markets_meta_tables(..., management_mode="external_registered")`.

Examples that register MetaTables use the platform namespace
`mainsequence.examples`:

```python
from examples.platform.bootstrap import start_examples_runtime

runtime = start_examples_runtime(labels=["asset-crud-example"])
```

## Assets And Categories

Start with assets before building reusable universes. Asset identity is the
stable contract consumed by holdings, target positions, pricing details, and
portfolio workflows.

```python
from msm.services import (
    delete_asset,
    get_asset_by_uid,
    get_asset_by_unique_identifier,
    search_assets,
    upsert_asset,
)

btc = upsert_asset(
    context,
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)

btc_by_identifier = get_asset_by_unique_identifier(
    context,
    unique_identifier="example-asset-btc",
)
btc_by_uid = get_asset_by_uid(context, uid=btc["uid"])
crypto_assets = search_assets(
    context,
    unique_identifier_contains="example-asset-",
    asset_type="crypto",
    limit=20,
)

delete_asset(context, uid=btc["uid"])
```

Use deletion for temporary or organization-owned custom assets only. Shared
public/mastered assets should remain stable so downstream workflows do not lose
their canonical identity.

See `examples/assets/asset_crud_workflow.py` for the focused asset CRUD example.

## Asset Snapshots

`AssetSnapshot` is a DataNode, not a MetaTable. Build validated snapshot frames
or a configured node through the service entrypoints:

```python
from msm.services import build_asset_snapshot_node

snapshot_node = build_asset_snapshot_node(
    {
        "unique_identifier": "example-asset-btc",
        "ticker": "BTC",
        "venue_specific_properties": {"source": "example"},
    },
    identifier="examples.mainsequence.markets.asset_snapshots",
    hash_namespace="examples",
)
snapshot_frame = snapshot_node.update()
```

See `examples/assets/asset_snapshot_workflow.py` for the focused DataNode
example.

When the universe itself should be a reusable platform object, create an asset
category and manage memberships separately:

```python
from msm.services import (
    create_asset_category,
    replace_asset_category_memberships,
    upsert_asset,
)

btc = upsert_asset(context, unique_identifier="BTC", asset_type="crypto")
eth = upsert_asset(context, unique_identifier="ETH", asset_type="crypto")
category = create_asset_category(
    context,
    unique_identifier="crypto-majors",
    display_name="Crypto Majors",
)

replace_asset_category_memberships(
    context,
    category_uid=category["uid"],
    asset_uids=[btc["uid"], eth["uid"]],
)
```

## Accounts, Funds, And Portfolios

```python
from msm.services import create_account, create_fund, create_portfolio

account = create_account(
    context,
    unique_identifier="acct-main",
    display_name="Main Account",
)
portfolio = create_portfolio(
    context,
    unique_identifier="btc-eth-target",
    calendar_name="24/7",
)
fund = create_fund(
    context,
    unique_identifier="fund-core",
    account_uid=account["uid"],
    portfolio_uid=portfolio["uid"],
)
```

## Holdings And Target Positions

```python
from uuid import uuid4

from msm.services import build_account_holdings_frame, build_target_positions_frame

holdings = build_account_holdings_frame(
    holdings_date="2026-05-25T00:00:00Z",
    account_uid=account["uid"],
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
