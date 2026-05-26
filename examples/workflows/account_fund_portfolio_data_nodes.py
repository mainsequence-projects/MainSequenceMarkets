from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)


def create_account_fund_portfolio_workflow() -> dict:
    """Create typed MetaTable records and build DataNode-ready frames."""

    from msm.api.accounts import Account
    from msm.api.portfolios import Fund, Portfolio
    from msm.services import (
        build_account_holdings_frame,
        build_target_positions_frame,
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

    holdings = build_account_holdings_frame(
        holdings_date="2026-05-25T00:00:00Z",
        account_uid=account.uid,
        positions=[
            {"unique_identifier": "BTC", "quantity": "1.0"},
            {"unique_identifier": "ETH", "quantity": "10.0"},
        ],
    )
    target_positions = build_target_positions_frame(
        target_positions_date="2026-05-25T00:00:00Z",
        position_set_uid=uuid4(),
        positions=[
            {"unique_identifier": "BTC", "weight_notional_exposure": "0.60"},
            {"unique_identifier": "ETH", "weight_notional_exposure": "0.40"},
        ],
    )
    return {
        "account": account,
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
