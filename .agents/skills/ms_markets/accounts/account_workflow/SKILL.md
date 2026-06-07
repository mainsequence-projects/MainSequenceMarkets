---
name: mainsequence-markets-account-workflow
description: Use this skill when creating, extending, reviewing, or documenting ms-markets account workflows, including Account, AccountGroup, AccountAllocationModel, AccountTargetAllocation, PositionSet, AccountHoldings, portfolio-aware TargetPositionsStorage, VirtualFund, VirtualFundHoldings, account holdings examples, and account position pretty-printing.
---

# Main Sequence Markets Account Workflow

Use this skill for account machinery in `msm`: account registry rows, account
groups, allocation-model tracking, account-owned target allocation links,
PositionSet snapshots, account holdings publication, and account target
allocation exposure rows that can reference either assets or portfolios.
Virtual funds are also core account-allocation state because they allocate real
account holdings into account-owned virtual portfolio views.

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
- Portfolio construction examples and portfolio calculation workflows:
  `.agents/skills/ms_markets/portfolios/portfolio_workflow/SKILL.md`
- Bootstrap/catalog registration:
  `.agents/skills/ms_markets/platform/bootstrap_registration/SKILL.md`

## Read First

Before changing account code, inspect:

1. `src/msm/models/accounts/core.py`
2. `src/msm/models/accounts/groups.py`
3. `src/msm/api/accounts.py`
4. `src/msm/data_nodes/accounts/__init__.py`
5. `src/msm/data_nodes/accounts/storage.py`
6. `src/msm/services/holdings.py`
7. `src/msm/services/target_positions.py`
8. `examples/msm/accounts/account_portfolio_full_workflow.py`
9. `examples/msm/accounts/account_virtual_fund_allocation_example.py`
10. `docs/knowledge/msm/accounts/index.md`
11. `docs/knowledge/msm/accounts/virtual_funds.md`
12. `docs/ADR/0029-account-holdings-virtual-fund-allocation-policy.md`

## Core Relationships

```text
AccountGroupTable
  <- AccountTable.account_group_uid

AccountAllocationModelTable
  <- AccountTargetAllocationTable.account_allocation_model_uid

AccountTable
  <- AccountTargetAllocationTable.account_uid
  <- AccountHoldingsStorage.account_uid

AccountTargetAllocationTable
  <- PositionSetTable.account_target_allocation_uid

PositionSetTable
  <- TargetPositionsStorage.position_set_uid

AssetTable.unique_identifier
  <- AccountHoldingsStorage.asset_identifier

AssetTable.uid
  <- TargetPositionsStorage.asset_uid

PortfolioTable.uid
  <- TargetPositionsStorage.portfolio_uid
```

Rules:

- `AccountGroup` is only a grouping of accounts. It has no relationship to
  `AccountAllocationModel`.
- `AccountAllocationModel` is a reusable allocation policy/model. Multiple
  accounts can track the same allocation model.
- `AccountTargetAllocation` is the account-specific relationship between one
  account and one allocation model. Do not model it as a shared row across
  accounts.
- `PositionSet` is a UTC timestamped target snapshot owned by one
  `AccountTargetAllocation`.
- `TargetPositionsStorage` is owned by core `msm` and stores actual target
  exposure rows for a `PositionSet`. Each row uses exactly one concrete target
  reference: `asset_uid` or `portfolio_uid`. `target_uid` must match the
  selected concrete UID. Exactly one exposure field must be present per row:
  `weight_notional_exposure`, `constant_notional_exposure`, or
  `single_asset_quantity`.
- `AccountHoldingsStorage` stores real holdings rows keyed by
  `(time_index, account_uid, asset_identifier)`.
- Account holdings use positive `quantity` plus `direction` (`1` long, `-1`
  short). Do not encode short exposure with negative quantities.
- `AccountHoldingsStorage.holdings_set_uid` must reference a real
  `AccountHoldingsSet` row. Do not invent anonymous holdings set UUIDs inside
  examples.
- `VirtualFundTable`, `VirtualFundHoldingsSetTable`, and
  `VirtualFundHoldingsStorage` are core `msm` account-allocation state, not
  `msm_portfolios` state.
- The account holdings to virtual-fund allocation planner is dry-run first. It
  produces an `AccountVirtualFundAllocationPlan`; only a separate apply step
  writes virtual-fund holdings rows.
- `VirtualFund.allocate_from_account_holdings_set(...)` is a low-level explicit
  publisher. It is not the allocation policy engine.
- DataNodes do not fabricate bootstrap rows. Attach a real frame or implement a
  real source-specific `update()`.

## Runtime Attachment

Examples and scripts must run after the SDK migration provider has registered
the required MetaTables. Application startup then attaches the
markets runtime before row operations or DataNode writes:

```python
import msm

msm.start_engine(
    models=[
        "AssetType",
        "Asset",
        "Calendar",
        "CalendarDate",
        "CalendarSession",
        "IndexType",
        "Index",
        "AssetSnapshotsStorage",
        "AccountAllocationModel",
        "AccountGroup",
        "Account",
        "AccountHoldingsSet",
        "AccountTargetAllocation",
        "PositionSet",
        "AccountHoldingsStorage",
        "Portfolio",
        "VirtualFund",
        "VirtualFundHoldingsSet",
        "VirtualFundHoldingsStorage",
        "SignalMetadata",
        "RebalanceStrategyMetadata",
        "PortfolioWeightsStorage",
        "SignalWeightsStorage",
        "PortfoliosStorage",
        "TargetPositionsStorage",
    ],
)
```

Create or upsert asset rows before holdings rows reference their
`unique_identifier`, and create or upsert portfolio rows before target rows
reference `portfolio_uid`. When an account example needs display fields, publish
`AssetSnapshot` rows with canonical `ticker` and `name` metadata instead of
only putting display data in holdings `extra_details`.

The full account example is intentionally chainable. By default,
`examples/msm/accounts/account_portfolio_full_workflow.py` prepares the
equal-weight portfolio interpolation schema, chains the reusable portfolio
workflow, reuses the resulting `Portfolio` row, and assigns that portfolio UID
as one of the account target positions. The same full workflow can be extended
with a dry-run account virtual-fund allocation plan using
`--with-virtual-fund-allocation`; use `--apply-virtual-fund-allocation` only
when the example should publish `VirtualFundHoldings` rows after printing the
plan. Use
`run_account_portfolio_full_workflow(use_portfolio_example=False)` or the
example CLI flag `--standalone-target-sleeve` only when testing the account
path without the portfolio example. Use `--skip-schema-prep` only when the
configured portfolio interpolation table has already been migrated.

## Virtual-Fund Allocation Pattern

Use `plan_account_virtual_fund_allocations(...)` to compute allocation before
writing. The canonical workflow takes exactly the service inputs from ADR 0029:
`position_set_uid`, `valuation_time`, `valuation_asset_uid`,
`holdings_selection_policy`, `valuation_resolver`, and `allocation_policy`.
Do not expose repository context, raw account UID, raw holdings-set UID, raw
source holdings, raw target demands, scan limits, or input-resolver callbacks
as public planner arguments. Internal vector helpers may use already-resolved
frames for tests, but examples and user workflows must use the canonical
planner inputs.

The default policy is `proportional_attribution`: virtual-fund claims consume
the asset-level gross source capacity first, and the direct account sleeve is
the residual. `strict_feasible` is a validation mode that fails when
virtual-fund demand exceeds source capacity.

Valuation is supplied through a valuation resolver protocol. The resolver uses
`valuation_asset_uid` as an `AssetTable.uid`, receives
`requested_metrics=("nav",)`, and returns totals plus optional
per-line valuation output. For notional target rows, it must also return
`target_quantity_demands` so the planner can allocate by signed quantities. Do
not pass ISO codes, tickers, or hidden global pricing state into the planner.

Use `virtual_fund_unique_identifier_for_target(...)` for deterministic
VirtualFund business keys. The key must be based on account, target portfolio,
and account target allocation identity.

## Full Workflow Pattern

Use public row APIs and service frame builders:

```python
import datetime as dt
import pandas as pd

from msm.api.accounts import (
    Account,
    AccountGroup,
    AccountHoldingsSet,
    AccountAllocationModel,
    AccountTargetAllocation,
    PositionSet,
)
from msm.api.assets import Asset, AssetType
from msm.data_nodes.accounts import AccountHoldings
from msm.data_nodes.accounts import TargetPositions
from msm.data_nodes.assets import AssetSnapshot
from msm.services import build_account_holdings_frame
from msm.services import build_target_positions_frame
from msm.api.portfolios import Portfolio

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

allocation_model = AccountAllocationModel.upsert(
    allocation_model_name="Example Balanced Account Model",
)
account_group = AccountGroup.upsert(group_name="Example High Risk Accounts")
target_sleeve = Portfolio.upsert(unique_identifier="example-target-sleeve")

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
    target_allocation = AccountTargetAllocation.upsert(
        unique_identifier=f"{account.unique_identifier}-target",
        account_uid=account.uid,
        account_allocation_model_uid=allocation_model.uid,
        display_name=f"{account.account_name} Target",
        is_active=True,
    )
    position_set = PositionSet.upsert(
        account_target_allocation_uid=target_allocation.uid,
        position_set_time=workflow_time,
    )
    target_position_frames.append(
        build_target_positions_frame(
            target_positions_date=workflow_time,
            position_set_uid=position_set.uid,
            positions=[
                {
                    "target_type": "asset",
                    "target_uid": assets[0].uid,
                    "asset_uid": assets[0].uid,
                    "weight_notional_exposure": 0.6,
                },
                {
                    "target_type": "portfolio",
                    "target_uid": target_sleeve.uid,
                    "portfolio_uid": target_sleeve.uid,
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
    holdings_set = AccountHoldingsSet.upsert(
        account_uid=account.uid,
        time_index=workflow_time,
    )
    holdings_frames.append(
        build_account_holdings_frame(
            holdings_date=workflow_time,
            account_uid=account.uid,
            holdings_set_uid=holdings_set.uid,
            positions=[
                {
                    "asset_identifier": assets[0].unique_identifier,
                    "quantity": quantities["btc"],
                    "direction": 1,
                    "target_trade_time": workflow_time,
                    "extra_details": {"ticker": "BTC", "name": "Bitcoin"},
                },
                {
                    "asset_identifier": assets[1].unique_identifier,
                    "quantity": quantities["eth"],
                    "direction": 1,
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
`AccountTargetAllocation` or `PositionSet`; those rows only define the target
relationship and snapshot identity.

## Timestamp And Dtype Rules

- `position_set_time` is a timezone-aware UTC timestamp, not an `"eod"` string.
- `target_trade_time` is a timezone-aware UTC datetime when present.
- Holdings builders normalize timestamp columns to SDK-compatible
  `datetime64[ns, UTC]`.
- Quantities and exposure values must be numeric, not strings.
- `asset_identifier` stores `Asset.unique_identifier`, not ticker, FIGI, ISIN,
  or a platform UID.
- Target positions never use `asset_identifier`; they use `target_type`,
  `target_uid`, and exactly one concrete reference: `asset_uid` for direct asset
  targets or `portfolio_uid` for portfolio sleeve targets.

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
- Account allocation-model references directly on `AccountTable`.
- Fake schema-bootstrap rows or placeholder holdings.
- DataNode-side dtype, nullable, index-name, or FK mirrors.
- User-provided DataNode table identifiers in examples when storage-derived
  defaults are enough.

## Validation

For account changes, run at least:

```bash
uv run --extra dev ruff check src/msm/api/accounts.py src/msm/models/accounts src/msm/data_nodes/accounts src/msm/services/holdings.py src/msm/services/target_positions.py examples/msm/accounts
uv run --extra dev pytest tests/msm/api/test_rows.py tests/msm/data_nodes/test_contracts.py tests/msm/data_nodes/test_target_positions_contracts.py tests/msm/models/test_metatable_models.py
uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
git diff --check
```

Do not run live examples unless the user wants platform writes.
