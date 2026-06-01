from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm


def create_account_fund_portfolio_workflow() -> dict:
    """Create typed MetaTable records and build DataNode-ready frames."""

    msm.start_engine(
        models=[
            "Asset",
            "AccountModelPortfolio",
            "Account",
            "AccountTargetPortfolio",
            "PositionSet",
            "Portfolio",
            "PortfolioAssetDetail",
            "Fund",
            "TargetPositionsStorage",
        ],
    )

    from msm.api.accounts import Account, AccountModelPortfolio, AccountTargetPortfolio, PositionSet
    from msm.api.portfolios import Fund, Portfolio
    from msm.services import (
        build_account_holdings_frame,
        build_target_positions_frame,
    )

    model_portfolio = AccountModelPortfolio.upsert(
        model_portfolio_name="Core Account Model",
        model_portfolio_description="Example model portfolio tracked by one account.",
    )
    account = Account.upsert(
        unique_identifier="account-main",
        account_name="Main Account",
        metadata_json={"venue": "example"},
    )
    portfolio = Portfolio.upsert(
        unique_identifier="portfolio-btc-eth",
        calendar_name="24/7",
        portfolio_index_asset_unique_identifier="portfolio-btc-eth",
    )
    fund = Fund.upsert(
        unique_identifier="fund-core",
        target_account_uid=account.uid,
        target_portfolio_uid=portfolio.uid,
    )
    account_target_portfolio = AccountTargetPortfolio.upsert(
        unique_identifier="account-main-core-model-target",
        account_uid=account.uid,
        account_model_portfolio_uid=model_portfolio.uid,
        display_name="Main Account Core Model Target",
    )
    position_set = PositionSet.upsert(
        account_target_portfolio_uid=account_target_portfolio.uid,
        position_set_time="2026-05-25T00:00:00Z",
    )

    holdings = build_account_holdings_frame(
        holdings_date="2026-05-25T00:00:00Z",
        account_uid=account.uid,
        positions=[
            {"unique_identifier": "BTC", "quantity": 1.0},
            {"unique_identifier": "ETH", "quantity": 10.0},
        ],
    )
    target_positions = build_target_positions_frame(
        target_positions_date="2026-05-25T00:00:00Z",
        position_set_uid=position_set.uid,
        positions=[
            {"unique_identifier": "BTC", "weight_notional_exposure": 0.60},
            {"unique_identifier": "ETH", "weight_notional_exposure": 0.40},
        ],
    )
    return {
        "model_portfolio": model_portfolio,
        "account": account,
        "account_target_portfolio": account_target_portfolio,
        "position_set": position_set,
        "portfolio": portfolio,
        "fund": fund,
        "holdings_frame": holdings,
        "target_positions_frame": target_positions,
    }


def main() -> None:
    result = create_account_fund_portfolio_workflow()
    print(result)


if __name__ == "__main__":
    main()
