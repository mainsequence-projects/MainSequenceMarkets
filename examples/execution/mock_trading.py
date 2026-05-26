from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)


def create_mock_execution() -> dict:
    """Create a small execution lifecycle through the typed row API."""

    from msm.api.accounts import Account
    from msm.api.assets import Asset
    from msm.api.execution import Order, OrderManager, OrderTargetQuantity, Trade
    from msm.api.portfolios import Fund, Portfolio

    asset = Asset.upsert(
        unique_identifier="example-execution-btc",
        asset_type="crypto",
    )
    account = Account.upsert(
        unique_identifier="example-execution-account",
        account_name="Example Execution Account",
        is_paper=True,
    )
    portfolio = Portfolio.upsert(
        unique_identifier="example-execution-portfolio",
        calendar_name="24/7",
        asset_detail={
            "asset_uid": asset.uid,
            "asset_unique_identifier": asset.unique_identifier,
        },
    )
    fund = Fund.upsert(
        unique_identifier="example-execution-fund",
        target_account_uid=account.uid,
        target_portfolio_uid=portfolio.uid,
    )

    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    order_manager = OrderManager.create_batch(
        unique_identifier="example-execution-batch",
        target_account_uid=account.uid,
        target_time=now,
        order_received_time=now,
        status="created",
    )
    target_quantity = OrderTargetQuantity.upsert(
        order_manager_uid=order_manager.uid,
        asset_uid=asset.uid,
        quantity=Decimal("1.25"),
    )
    order = Order.upsert(
        order_remote_id=f"example-{int(now.timestamp())}",
        client_order_id=f"{order_manager.uid}:{asset.unique_identifier}",
        order_type="market",
        order_time=now,
        order_side=1,
        quantity=Decimal("1.25"),
        status="partially_filled",
        filled_quantity=Decimal("1.00"),
        filled_price=Decimal("65000.00"),
        order_manager_uid=order_manager.uid,
        asset_uid=asset.uid,
        asset_unique_identifier=asset.unique_identifier,
        related_fund_uid=fund.uid,
        related_account_uid=account.uid,
        time_in_force="gtc",
        comments="Example typed API order.",
    )
    status_event = Order.record_status(
        order_uid=order.uid,
        order_status="partially_filled",
        event_time=now,
        extra_info={"source": "example"},
    )
    trade = Trade.upsert(
        trade_time=now,
        trade_side=1,
        asset_uid=asset.uid,
        asset_unique_identifier=asset.unique_identifier,
        quantity=Decimal("1.00"),
        price=Decimal("65000.00"),
        related_fund_uid=fund.uid,
        related_account_uid=account.uid,
        related_order_uid=order.uid,
        commission=Decimal("0"),
        settlement_cost=Decimal("65000.00"),
        settlement_asset_unique_identifier="USD",
        comments="Example typed API fill.",
    )

    return {
        "asset": asset,
        "account": account,
        "portfolio": portfolio,
        "fund": fund,
        "order_manager": order_manager,
        "target_quantity": target_quantity,
        "order": order,
        "status_event": status_event,
        "trade": trade,
    }


def main() -> None:
    result = create_mock_execution()
    print(result)


if __name__ == "__main__":
    main()
