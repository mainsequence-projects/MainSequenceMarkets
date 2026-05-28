from __future__ import annotations

import datetime as dt
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


def main() -> None:
    """Demonstrate class-owned typed row APIs across markets MetaTables."""

    msm.start_engine(
        models=[
            "Asset",
            "AssetCategory",
            "AssetCategoryMembership",
            "Calendar",
            "Account",
            "Portfolio",
            "PortfolioAssetDetail",
            "Fund",
            "OrderManager",
            "OrderTargetQuantity",
            "Order",
            "OrderStatusEvent",
            "Trade",
            "ExecutionError",
        ],
    )

    from msm.api.accounts import Account
    from msm.api.assets import Asset, AssetCategory
    from msm.api.calendars import Calendar
    from msm.api.execution import OrderManager
    from msm.api.portfolios import Fund, Portfolio

    btc = Asset.upsert(unique_identifier="example-api-btc", asset_type="crypto")
    eth = Asset.upsert(unique_identifier="example-api-eth", asset_type="crypto")
    category = AssetCategory.upsert(
        unique_identifier="example-api-crypto",
        display_name="Example API Crypto",
    )
    memberships = AssetCategory.replace_memberships(
        category_uid=category.uid,
        asset_uids=[btc.uid, eth.uid],
    )
    calendar = Calendar.upsert(name="example-api-24-7", calendar_dates=[])
    account = Account.upsert(
        unique_identifier="example-api-account",
        account_name="Example API Account",
        is_paper=True,
    )
    portfolio = Portfolio.upsert(
        unique_identifier="example-api-portfolio",
        calendar_name=calendar.name,
        asset_detail={"asset_uid": btc.uid, "asset_unique_identifier": btc.unique_identifier},
    )
    fund = Fund.upsert(
        unique_identifier="example-api-fund",
        target_account_uid=account.uid,
        target_portfolio_uid=portfolio.uid,
    )
    order_manager = OrderManager.create_batch(
        unique_identifier="example-api-order-manager",
        target_account_uid=account.uid,
        target_time=dt.datetime.now(dt.UTC),
        status="created",
    )

    print(
        {
            "assets": [btc, eth],
            "category": category,
            "memberships": memberships,
            "calendar": calendar,
            "account": account,
            "portfolio": portfolio,
            "fund": fund,
            "order_manager": order_manager,
        }
    )


if __name__ == "__main__":
    main()
