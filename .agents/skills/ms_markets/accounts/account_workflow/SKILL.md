---
name: mainsequence-markets-account-workflow
description: Use this skill when creating, extending, reviewing, or documenting ms-markets account workflows, including Account, AccountGroup, AccountModelPortfolio, AccountTargetPortfolio, PositionSet, AccountHoldings, TargetPositionsStorage, account holdings examples, and account position pretty-printing.
---

# Main Sequence Markets Account Workflow

Use this skill for account machinery in `msm`: account registry rows, account
groups, model portfolio tracking, account-owned target portfolio links, target
position snapshots, and account holdings publication.

## Route First

Use these adjacent skills when the task crosses their boundary:

- Generic MetaTable behavior:
  `.agents/skills/mainsequence/data_publishing/meta_tables/SKILL.md`
- Generic DataNode behavior:
  `.agents/skills/mainsequence/data_publishing/data_nodes/SKILL.md`
- Asset identity and asset detail rows:
  `.agents/skills/ms_markets/assets/asset_model_extension/SKILL.md`
- Asset-indexed DataNode conventions:
  `.agents/skills/ms_markets/assets/asset_indexed_data_nodes/SKILL.md`
- Bootstrap/catalog registration:
  `.agents/skills/ms_markets/platform/bootstrap_registration/SKILL.md`

## Read First

Before changing account code, inspect:

1. `src/msm/models/accounts/core.py`
2. `src/msm/models/accounts/groups.py`
3. `src/msm/api/accounts.py`
4. `src/msm/data_nodes/accounts.py`
5. `src/msm/data_nodes/storage.py`
6. `src/msm/services/holdings.py`
7. `src/msm/services/target_positions.py`
8. `examples/msm/accounts/account_workflow.py`
9. `docs/knowledge/msm/accounts/index.md`

## Core Relationships

```text
AccountGroupTable
  <- AccountTable.account_group_uid

AccountModelPortfolioTable
  <- AccountTargetPortfolioTable.account_model_portfolio_uid

AccountTable
  <- AccountTargetPortfolioTable.account_uid
  <- AccountHoldingsStorage.account_uid

AccountTargetPortfolioTable
  <- PositionSetTable.account_target_portfolio_uid

PositionSetTable
  <- TargetPositionsStorage.position_set_uid

AssetTable.unique_identifier
  <- AccountHoldingsStorage.asset_identifier
  <- TargetPositionsStorage.asset_identifier
```

Rules:

- `AccountGroup` is only a grouping of accounts. It has no relationship to
  `AccountModelPortfolio`.
- `AccountModelPortfolio` is a reusable reference model. Multiple accounts can
  track the same model portfolio.
- `AccountTargetPortfolio` is the account-specific relationship between one
  account and one model portfolio. Do not model it as a shared row across
  accounts.
- `PositionSet` is a UTC timestamped target snapshot owned by one
  `AccountTargetPortfolio`.
- `TargetPositionsStorage` stores the actual exposure rows for a `PositionSet`.
  Exactly one exposure field must be present per row:
  `weight_notional_exposure`, `constant_notional_exposure`, or
  `single_asset_quantity`.
- `AccountHoldingsStorage` stores real holdings rows keyed by
  `(time_index, account_uid, asset_identifier)`.
- DataNodes do not fabricate bootstrap rows. Attach a real frame or implement a
  real source-specific `update()`.

## Runtime Attachment

Examples and scripts must run after the SDK migration provider has registered
and cataloged the required MetaTables. Application startup then attaches the
markets runtime before row operations or DataNode writes:

```python
import msm

msm.start_engine(
    models=[
        "AssetType",
        "Asset",
        "AssetSnapshotsStorage",
        "AccountModelPortfolio",
        "AccountGroup",
        "Account",
        "AccountTargetPortfolio",
        "PositionSet",
        "AccountHoldingsStorage",
        "TargetPositionsStorage",
    ],
)
```

Create or upsert asset rows before holdings or target rows reference their
`unique_identifier`. When an account example needs display fields, publish
`AssetSnapshot` rows with canonical `ticker` and `name` metadata instead of
only putting display data in holdings `extra_details`.

## Full Workflow Pattern

Use public row APIs and service frame builders:

```python
import datetime as dt
import pandas as pd

from msm.api.accounts import (
    Account,
    AccountGroup,
    AccountModelPortfolio,
    AccountTargetPortfolio,
    PositionSet,
)
from msm.api.assets import Asset, AssetType
from msm.data_nodes.accounts import AccountHoldings, TargetPositions
from msm.data_nodes.assets import AssetSnapshot
from msm.services import build_account_holdings_frame, build_target_positions_frame

workflow_time = dt.datetime.now(dt.UTC).replace(microsecond=0)

asset_type = AssetType.upsert(...)
assets = [
    Asset.upsert(unique_identifier="example-asset-btc", asset_type=asset_type.asset_type),
    Asset.upsert(unique_identifier="example-asset-eth", asset_type=asset_type.asset_type),
]

asset_snapshot_node = AssetSnapshot().set_snapshots(
    [
        {
            "time_index": workflow_time,
            "asset_identifier": assets[0].unique_identifier,
            "name": "Bitcoin",
            "ticker": "BTC",
        },
        {
            "time_index": workflow_time,
            "asset_identifier": assets[1].unique_identifier,
            "name": "Ethereum",
            "ticker": "ETH",
        },
    ]
)
snapshot_error, snapshot_frame = asset_snapshot_node.run(debug_mode=True, force_update=True)
if snapshot_error:
    raise RuntimeError("AssetSnapshot update failed.")

model_portfolio = AccountModelPortfolio.upsert(
    model_portfolio_name="Example Balanced Account Model",
)
account_group = AccountGroup.upsert(group_name="Example High Risk Accounts")

accounts = [
    Account.upsert(
        unique_identifier="example-account-alpha",
        account_name="Example Account Alpha",
        is_paper=True,
        account_is_active=True,
        account_group_uid=account_group.uid,
    ),
    Account.upsert(
        unique_identifier="example-account-beta",
        account_name="Example Account Beta",
        is_paper=True,
        account_is_active=True,
        account_group_uid=account_group.uid,
    ),
]

target_position_frames = []
for account in accounts:
    target_portfolio = AccountTargetPortfolio.upsert(
        unique_identifier=f"{account.unique_identifier}-target",
        account_uid=account.uid,
        account_model_portfolio_uid=model_portfolio.uid,
        display_name=f"{account.account_name} Target",
        is_active=True,
    )
    position_set = PositionSet.upsert(
        account_target_portfolio_uid=target_portfolio.uid,
        position_set_time=workflow_time,
    )
    target_position_frames.append(
        build_target_positions_frame(
            target_positions_date=workflow_time,
            position_set_uid=position_set.uid,
            positions=[
                {
                    "asset_identifier": assets[0].unique_identifier,
                    "weight_notional_exposure": 0.6,
                },
                {
                    "asset_identifier": assets[1].unique_identifier,
                    "weight_notional_exposure": 0.4,
                }
            ],
        )
    )

holdings_frames = []
target_positions_node = TargetPositions(config=TargetPositions.default_config())
target_positions_node.set_frame(pd.concat(target_position_frames).sort_index())
target_error, target_positions_frame = target_positions_node.run(
    debug_mode=True,
    force_update=True,
)
if target_error:
    raise RuntimeError("TargetPositions update failed.")

for account, quantities in zip(
    accounts,
    ({"btc": 10.0, "eth": 25.0}, {"btc": 5.0, "eth": 12.5}),
    strict=True,
):
    holdings_frames.append(
        build_account_holdings_frame(
            holdings_date=workflow_time,
            account_uid=account.uid,
            positions=[
                {
                    "asset_identifier": assets[0].unique_identifier,
                    "quantity": quantities["btc"],
                    "target_trade_time": workflow_time,
                    "extra_details": {"ticker": "BTC", "name": "Bitcoin"},
                },
                {
                    "asset_identifier": assets[1].unique_identifier,
                    "quantity": quantities["eth"],
                    "target_trade_time": workflow_time,
                    "extra_details": {"ticker": "ETH", "name": "Ethereum"},
                }
            ],
        )
    )

holdings_node = AccountHoldings(config=AccountHoldings.default_config())
holdings_node.set_frame(pd.concat(holdings_frames).sort_index())
error_on_last_update, holdings_frame = holdings_node.run(debug_mode=True, force_update=True)
if error_on_last_update:
    raise RuntimeError("Account holdings update failed.")

for account in accounts:
    account.pretty_print_positions(holdings_frame)
```

Prefer `set_account_holdings_frame(...)` only for a single-account frame. For
multi-account examples, build frames with `build_account_holdings_frame(...)`,
concatenate them, and call `AccountHoldings.set_frame(...)`.

Target positions follow the same rule: build concrete rows with
`build_target_positions_frame(...)`, concatenate the real frames, attach them to
`TargetPositions.set_frame(...)`, and run the node. Do not stop at creating
`AccountTargetPortfolio` or `PositionSet`; those rows only define the target
relationship and snapshot identity.

## Timestamp And Dtype Rules

- `position_set_time` is a timezone-aware UTC timestamp, not an `"eod"` string.
- `target_trade_time` is a timezone-aware UTC datetime when present.
- Holdings builders normalize timestamp columns to SDK-compatible
  `datetime64[ns, UTC]`.
- Quantities and exposure values must be numeric, not strings.
- `asset_identifier` stores `Asset.unique_identifier`, not ticker, FIGI, ISIN,
  or a platform UID.

## Pretty-Printing Positions

`Account.pretty_print_positions(holdings_frame)` expects a DataFrame, not the
raw tuple returned by `AccountHoldings.run(...)`. Always unpack first:

```python
error_on_last_update, holdings_frame = holdings_node.run(...)
positions = account.pretty_print_positions(holdings_frame)
```

The printed table contains `asset_uid`, `ticker`, `position_type`, and
`position_value`. It resolves `asset_uid` through `Asset.get_by_unique_identifier`
and uses `extra_details["ticker"]` when available.

## Do Not Reintroduce

- `msm.accounts` compatibility shims.
- `AccountTargetPositionAssignmentTable`.
- Account-model-portfolio references directly on `AccountTable`.
- Fake schema-bootstrap rows or placeholder holdings.
- DataNode-side dtype, nullable, index-name, or FK mirrors.
- User-provided DataNode table identifiers in examples when storage-derived
  defaults are enough.

## Validation

For account changes, run at least:

```bash
uv run --extra dev ruff check src/msm/api/accounts.py src/msm/models/accounts src/msm/data_nodes/accounts.py src/msm/services/holdings.py src/msm/services/target_positions.py examples/msm/accounts
uv run --extra dev pytest tests/msm/api/test_rows.py tests/msm/data_nodes/test_contracts.py tests/msm/models/test_metatable_models.py
uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
git diff --check
```

Do not run live examples unless the user wants platform writes.
