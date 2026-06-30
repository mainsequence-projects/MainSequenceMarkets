# Accounts and Holdings

Publish and inspect account positions: account holdings, target positions, and
virtual-fund allocation. Target positions can reference either direct assets or
portfolio sleeves, which connects this chapter to
[Portfolios](04-portfolios.md).

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Accounts, virtual funds, and portfolios

```python
import msm

from msm.api.accounts import Account
from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio
from msm.api.virtual_funds import VirtualFund

msm.start_engine(
    models=["Account", "Calendar", "CalendarDate", "CalendarSession", "Portfolio", "VirtualFund"]
)

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
)
calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)
portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_uid=calendar.uid,
)
virtual_fund = VirtualFund.upsert(
    unique_identifier="vf-core",
    account_uid=account.uid,
    target_portfolio_uid=portfolio.uid,
)
```

## Account holdings workflow

Use this workflow when publishing and inspecting account positions:

1. Before runtime, run the admin migration flow with
   `mainsequence migrations upgrade --provider migrations:migration head`
   so the package schema is finalized.
2. Attach account holdings and target positions through `msm.start_engine(...)`.
   When target positions can reference portfolios, include `Portfolio` and
   `TargetPositionsStorage` in the core `msm` model list.
3. Create or upsert the account allocation model and account group, then create
   the account with `account_group_uid`.
4. Create the `AccountTargetAllocation` relation for the account and allocation
   model, then create a UTC `PositionSet` snapshot under that relation.
5. Build target-position rows with
   `msm.services.build_target_positions_frame(...)` using
   `position_set.uid` as `position_set_uid`, and use `asset_uid` for direct
   asset targets or `portfolio_uid` for portfolio sleeve targets.
6. Build holdings rows with `build_account_holdings_frame(...)` and attach the
   real combined frame to `AccountHoldings` with `set_frame(...)`. For a single
   account, `set_account_holdings_frame(...)` is the convenience path.
7. Run the node and unpack the SDK result:
   `error_on_last_update, holdings_frame = holdings_node.run(...)`.
8. Pass only `holdings_frame` to `Account.pretty_print_positions(...)`.

## Holdings and target positions

```python
from msm.api.accounts import (
    AccountAllocationModel,
    AccountHoldingsSet,
    AccountTargetAllocation,
    PositionSet,
)
from msm.api.assets import Asset
from msm.api.portfolios import Portfolio
from msm.services import build_account_holdings_frame
from msm.services import build_target_positions_frame

holdings_set = AccountHoldingsSet.upsert(
    account_uid=account.uid,
    time_index="2026-05-25T00:00:00Z",
)
holdings = build_account_holdings_frame(
    holdings_date="2026-05-25T00:00:00Z",
    account_uid=account.uid,
    holdings_set_uid=holdings_set.uid,
    positions=[
        {"asset_identifier": "BTC", "quantity": 1.0, "direction": 1},
        {"asset_identifier": "ETH", "quantity": 10.0, "direction": -1},
    ],
)

allocation_model = AccountAllocationModel.upsert(
    allocation_model_name="balanced-allocation-model"
)
account_target_allocation = AccountTargetAllocation.upsert(
    unique_identifier="account-main-balanced-target",
    account_uid=account.uid,
    account_allocation_model_uid=allocation_model.uid,
)
position_set = PositionSet.upsert(
    account_target_allocation_uid=account_target_allocation.uid,
    position_set_time="2026-05-25T00:00:00Z",
)
btc_asset = Asset.upsert(unique_identifier="BTC", asset_type="crypto")
portfolio_sleeve = Portfolio.upsert(
    unique_identifier="account-main-sleeve",
    calendar_uid=calendar.uid,
)

targets = build_target_positions_frame(
    target_positions_date="2026-05-25T00:00:00Z",
    position_set_uid=position_set.uid,
    positions=[
        {"asset_uid": btc_asset.uid, "weight_notional_exposure": 0.6},
        {"portfolio_uid": portfolio_sleeve.uid, "weight_notional_exposure": 0.4},
    ],
)
```

The DataNode frame helpers validate the dynamic-table contract locally. The
actual table provisioning and writes remain generic TDAG/DataNode behavior.

## Virtual-fund allocation

Virtual-fund allocation is a separate policy workflow. Start from the
`PositionSet.uid`, pass `valuation_time`, `valuation_asset_uid`,
`holdings_selection_policy`, `valuation_resolver`, and `allocation_policy`,
inspect the dry-run `AccountVirtualFundAllocationPlan`, and only then call
`apply_account_virtual_fund_allocation_plan(...)`. The full account workflow
supports this as an extension: run
`examples/msm/accounts/account_portfolio_full_workflow.py --with-virtual-fund-allocation`
for dry-run planning, or add `--apply-virtual-fund-allocation` to publish the
virtual-fund holdings after the plan is printed.

See `examples/msm/accounts/account_portfolio_full_workflow.py` for the full
account plus portfolio path. The default runner prepares only the contributed
interpolated-price output storage revision needed by the portfolio example,
upgrades it, chains
`examples/msm_portfolios/portfolio_equal_weights_example.py` to create a
reusable portfolio sleeve, assigns that sleeve to an example portfolio group,
then creates the account group, two accounts, canonical asset snapshots with
ticker/name metadata, one shared account allocation model, account-owned target
allocation relationships, direct asset plus portfolio `PositionSet` target-row
publication, holdings publication, and pretty-printed account positions. Use
`--skip-schema-prep` only when that
contributed interpolated-price output table has already been migrated.

**Next →** [Portfolios](04-portfolios.md)
