from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.accounts.utils import (
    EXAMPLE_ACCOUNT_GROUP,
    EXAMPLE_ACCOUNT_MODEL_PORTFOLIO,
    EXAMPLE_ACCOUNT_TARGET_PORTFOLIO,
    EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO,
    EXAMPLE_ACCOUNT_WORKFLOW_SOURCE,
    EXAMPLE_ACCOUNTS,
    example_account_holdings_positions,
    example_account_target_positions,
)
from examples.msm.assets.utils import (
    EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_BTC_TICKER,
    EXAMPLE_CRYPTO_ASSETS,
    EXAMPLE_CRYPTO_ASSET_TYPE,
    EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_ETH_TICKER,
)

import msm_portfolios

ACCOUNT_WORKFLOW_RUNTIME_MODELS = [
    "IndexType",
    "Index",
    "AssetType",
    "Asset",
    "Calendar",
    "CalendarDate",
    "CalendarSession",
    "AssetSnapshotsStorage",
    "AccountModelPortfolio",
    "AccountGroup",
    "Account",
    "AccountHoldingsSet",
    "AccountTargetPortfolio",
    "PositionSet",
    "AccountHoldingsStorage",
    "Portfolio",
    "VirtualFund",
    "VirtualFundHoldingsSet",
    "VirtualFundHoldingsStorage",
    "SignalMetadata",
    "RebalanceStrategyMetadata",
    "ExternalPricesStorage",
    "PortfolioWeightsStorage",
    "SignalWeightsStorage",
    "PortfoliosStorage",
    "TargetPositionsStorage",
]


def run_account_workflow(
    *,
    use_portfolio_example: bool = True,
    run_portfolio_data_nodes: bool = True,
) -> dict[str, Any]:
    """Create the account registry rows and publish account holdings."""

    portfolio_example_result: dict[str, Any] | None = None
    if use_portfolio_example:
        print(
            "0. Building the reusable portfolio example so account targets can "
            "reference its Portfolio row."
        )
        from examples.msm_portfolios.portfolio_equal_weights_example import (
            EXAMPLE_INTERPOLATED_PRICES_STORAGE,
            build_equal_weight_portfolio,
        )

        portfolio_example_result = build_equal_weight_portfolio(
            run_data_nodes=run_portfolio_data_nodes,
            runtime_models=[*ACCOUNT_WORKFLOW_RUNTIME_MODELS, EXAMPLE_INTERPOLATED_PRICES_STORAGE],
        )
        print(
            "   Portfolio example ready: "
            f"portfolio_uid={portfolio_example_result['portfolio'].uid} "
            f"portfolio_identifier="
            f"{portfolio_example_result['portfolio'].unique_identifier}"
        )
    else:
        print("0. Starting the markets engine with the standalone account schema.")
        msm_portfolios.start_engine(models=ACCOUNT_WORKFLOW_RUNTIME_MODELS)
        print("   Markets engine ready.")

    from msm.api.accounts import (
        Account,
        AccountGroup,
        AccountHoldingsSet,
        AccountModelPortfolio,
        AccountTargetPortfolio,
        PositionSet,
    )
    from msm.api.assets import Asset, AssetType
    from msm.data_nodes.accounts import AccountHoldings
    from msm.data_nodes.assets import AssetSnapshot
    from msm.services import build_account_holdings_frame
    from msm_portfolios.api.portfolios import Portfolio
    from msm_portfolios.data_nodes import TargetPositions
    from msm_portfolios.services import build_target_positions_frame

    if portfolio_example_result is None:
        print("1. Registering the crypto AssetType used by the account example.")
    else:
        print("1. Reusing the crypto AssetType and assets from the portfolio example.")
    asset_type = AssetType.upsert(**EXAMPLE_CRYPTO_ASSET_TYPE)
    print(f"   AssetType uid={asset_type.uid} asset_type={asset_type.asset_type}")

    if portfolio_example_result is None:
        print("2. Registering the BTC and ETH Assets that holdings and targets reference.")
        assets = [Asset.upsert(**asset_payload) for asset_payload in EXAMPLE_CRYPTO_ASSETS]
    else:
        print("2. Using the BTC and ETH Assets created by the portfolio example.")
        assets = list(portfolio_example_result["assets"])
    assets_by_identifier = {asset.unique_identifier: asset for asset in assets}
    for asset in assets:
        print(f"   Asset uid={asset.uid} unique_identifier={asset.unique_identifier}")

    workflow_time = dt.datetime.now(dt.UTC).replace(microsecond=0)
    print(f"3. Using one UTC workflow timestamp: {workflow_time.isoformat()}")

    print("4. Publishing AssetSnapshot rows with canonical ticker and name metadata.")
    asset_snapshot_node = AssetSnapshot().set_snapshots(
        [
            {
                "time_index": workflow_time,
                "asset_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
                "name": "Bitcoin",
                "ticker": EXAMPLE_BTC_TICKER,
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
            },
            {
                "time_index": workflow_time,
                "asset_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
                "name": "Ethereum",
                "ticker": EXAMPLE_ETH_TICKER,
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
            },
        ]
    )
    asset_snapshot_error, asset_snapshot_frame = asset_snapshot_node.run(
        debug_mode=True,
        force_update=True,
    )
    if asset_snapshot_error:
        raise RuntimeError("AssetSnapshot update failed; inspect the DataNode run logs.")
    print(
        "   AssetSnapshot rows persisted: "
        f"rows={len(asset_snapshot_frame)} identifier={asset_snapshot_node._default_identifier()}"
    )

    print("5. Registering one reusable AccountModelPortfolio.")
    model_portfolio = AccountModelPortfolio.upsert(**EXAMPLE_ACCOUNT_MODEL_PORTFOLIO)
    print(
        "   AccountModelPortfolio "
        f"uid={model_portfolio.uid} name={model_portfolio.model_portfolio_name}"
    )

    print("6. Registering the AccountGroup that groups both accounts.")
    account_group = AccountGroup.upsert(**EXAMPLE_ACCOUNT_GROUP)
    print(f"   AccountGroup uid={account_group.uid} name={account_group.group_name}")

    print("7. Creating two accounts and assigning both to the group.")
    accounts = [
        Account.upsert({**payload, "account_group_uid": account_group.uid})
        for payload in EXAMPLE_ACCOUNTS
    ]
    for account in accounts:
        print(
            "   Account "
            f"uid={account.uid} unique_identifier={account.unique_identifier} "
            f"group_uid={account.account_group_uid}"
        )

    if portfolio_example_result is None:
        print("8. Creating a portfolio sleeve that account targets can reference.")
        target_sleeve_portfolio = Portfolio.upsert(
            **EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO
        )
    else:
        print("8. Reusing the portfolio created by the portfolio example as a target sleeve.")
        target_sleeve_portfolio = portfolio_example_result["portfolio"]
    print(
        "   Portfolio "
        f"uid={target_sleeve_portfolio.uid} "
        f"unique_identifier={target_sleeve_portfolio.unique_identifier}"
    )

    print("9. Creating the AccountHoldings DataNode instance.")
    holdings_node = AccountHoldings(config=AccountHoldings.default_config())
    print(f"   AccountHoldings identifier={holdings_node._default_identifier()}")

    print(
        "10. Creating account-owned target portfolio relationships that both "
        "point to the same AccountModelPortfolio."
    )
    target_records: list[dict[str, Any]] = []
    target_position_frames: list[pd.DataFrame] = []
    for account in accounts:
        target_portfolio = AccountTargetPortfolio.upsert(
            {
                **EXAMPLE_ACCOUNT_TARGET_PORTFOLIO,
                "unique_identifier": f"{account.unique_identifier}-target",
                "display_name": f"{account.account_name} Target",
                "account_uid": account.uid,
                "account_model_portfolio_uid": model_portfolio.uid,
                "metadata_json": {
                    **(EXAMPLE_ACCOUNT_TARGET_PORTFOLIO.get("metadata_json") or {}),
                    "account_identifier": account.unique_identifier,
                },
            }
        )
        print(
            "   AccountTargetPortfolio "
            f"uid={target_portfolio.uid} account_uid={target_portfolio.account_uid} "
            f"model_portfolio_uid={target_portfolio.account_model_portfolio_uid}"
        )

        position_set = PositionSet.upsert(
            account_target_portfolio_uid=target_portfolio.uid,
            position_set_time=workflow_time,
            source=EXAMPLE_ACCOUNT_WORKFLOW_SOURCE,
            metadata_json={"account_identifier": account.unique_identifier},
        )
        print(
            "   PositionSet "
            f"uid={position_set.uid} target_portfolio_uid="
            f"{position_set.account_target_portfolio_uid}"
        )

        target_positions_frame = build_target_positions_frame(
            target_positions_date=workflow_time,
            position_set_uid=position_set.uid,
            positions=example_account_target_positions(
                asset_uid=assets_by_identifier[EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER].uid,
                portfolio_uid=target_sleeve_portfolio.uid,
            ),
        )
        print(
            "   TargetPositionsStorage rows built for "
            f"{account.unique_identifier}: rows={len(target_positions_frame)}"
        )

        target_records.append(
            {
                "account": account,
                "target_portfolio": target_portfolio,
                "position_set": position_set,
            }
        )
        target_position_frames.append(target_positions_frame)

    combined_target_positions_frame = pd.concat(target_position_frames).sort_index()
    print(f"   Combined target-position rows ready: rows={len(combined_target_positions_frame)}")

    print("11. Running the TargetPositions DataNode update.")
    target_positions_node = TargetPositions(config=TargetPositions.default_config())
    target_positions_node.set_frame(combined_target_positions_frame)
    target_positions_error, persisted_target_positions_frame = target_positions_node.run(
        debug_mode=True,
        force_update=True,
    )
    if target_positions_error:
        raise RuntimeError("TargetPositions update failed; inspect the DataNode run logs.")
    print(
        "    Persisted target-position rows="
        f"{len(persisted_target_positions_frame)} identifier="
        f"{target_positions_node._default_identifier()}"
    )

    print("12. Building two-asset holdings rows for both accounts.")
    holdings_frames = []
    account_quantities = (
        {"btc_quantity": 10.0, "eth_quantity": 25.0, "eth_direction": 1},
        {"btc_quantity": 5.0, "eth_quantity": 12.5, "eth_direction": -1},
    )
    for account, quantities in zip(accounts, account_quantities, strict=True):
        holdings_set = AccountHoldingsSet.upsert(
            account_uid=account.uid,
            time_index=workflow_time,
        )
        holdings_frame = build_account_holdings_frame(
            holdings_date=workflow_time,
            account_uid=account.uid,
            holdings_set_uid=holdings_set.uid,
            positions=example_account_holdings_positions(
                target_trade_time=workflow_time,
                **quantities,
            ),
        )
        print(
            "   AccountHoldingsStorage rows built for "
            f"{account.unique_identifier}: "
            f"holdings_set_uid={holdings_set.uid} "
            f"btc_quantity={quantities['btc_quantity']} "
            f"eth_quantity={quantities['eth_quantity']} "
            f"eth_direction={quantities['eth_direction']} "
            f"eth_signed_quantity="
            f"{quantities['eth_quantity'] * quantities['eth_direction']} "
            f"rows={len(holdings_frame)}"
        )
        holdings_frames.append(holdings_frame)

    combined_holdings_frame = pd.concat(holdings_frames).sort_index()
    holdings_node.set_frame(combined_holdings_frame)
    print(f"   Combined holdings rows attached: rows={len(combined_holdings_frame)}")

    print("13. Running the AccountHoldings DataNode update.")
    error_on_last_update, holdings_frame = holdings_node.run(debug_mode=True, force_update=True)
    if error_on_last_update:
        raise RuntimeError("Account holdings update failed; inspect the DataNode run logs.")
    print(f"    Persisted holdings rows={len(holdings_frame)}")

    print("14. Pretty-printing resolved positions for each account.")
    pretty_positions_by_account = {}
    for account in accounts:
        print(f"    Positions for {account.unique_identifier}:")
        pretty_positions_by_account[account.unique_identifier] = account.pretty_print_positions(
            holdings_frame
        )

    return {
        "use_portfolio_example": use_portfolio_example,
        "portfolio_example_result": portfolio_example_result,
        "asset_type": asset_type,
        "assets": assets,
        "asset_snapshot_node_identifier": asset_snapshot_node._default_identifier(),
        "asset_snapshot_frame": asset_snapshot_frame,
        "model_portfolio": model_portfolio,
        "target_sleeve_portfolio": target_sleeve_portfolio,
        "account_group": account_group,
        "accounts": accounts,
        "target_records": target_records,
        "target_positions_frame": combined_target_positions_frame,
        "target_positions_data_node_identifier": target_positions_node._default_identifier(),
        "persisted_target_positions_frame": persisted_target_positions_frame,
        "holdings_data_node_identifier": holdings_node._default_identifier(),
        "holdings_date": workflow_time,
        "pretty_positions_by_account": pretty_positions_by_account,
        "updated_frame": holdings_frame,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--standalone-target-portfolio",
        action="store_true",
        help=(
            "Create a standalone Portfolio row instead of reusing the portfolio "
            "example output."
        ),
    )
    parser.add_argument(
        "--no-run-portfolio-data-nodes",
        action="store_true",
        help=(
            "When chaining the portfolio example, skip its DataNode publication; "
            "by default the full dependency tree is published."
        ),
    )
    args = parser.parse_args()

    result = run_account_workflow(
        use_portfolio_example=not args.standalone_target_portfolio,
        run_portfolio_data_nodes=not args.no_run_portfolio_data_nodes,
    )
    print("Workflow complete.")
    print("Used portfolio example:", result["use_portfolio_example"])
    print("Account group UID:", result["account_group"].uid)
    print("Shared account model portfolio UID:", result["model_portfolio"].uid)
    print("Referenced target sleeve Portfolio UID:", result["target_sleeve_portfolio"].uid)
    for target_record in result["target_records"]:
        account = target_record["account"]
        target_portfolio = target_record["target_portfolio"]
        position_set = target_record["position_set"]
        print(
            "Account workflow row:",
            {
                "account_uid": account.uid,
                "account_identifier": account.unique_identifier,
                "target_portfolio_uid": target_portfolio.uid,
                "position_set_uid": position_set.uid,
            },
        )
    print(
        "Asset unique_identifiers:",
        [asset.unique_identifier for asset in result["assets"]],
    )
    print("AssetSnapshot DataNode identifier:", result["asset_snapshot_node_identifier"])
    print("TargetPositions DataNode identifier:", result["target_positions_data_node_identifier"])
    print("Holdings DataNode identifier:", result["holdings_data_node_identifier"])
    print("Holdings date:", result["holdings_date"].isoformat())


if __name__ == "__main__":
    main()
