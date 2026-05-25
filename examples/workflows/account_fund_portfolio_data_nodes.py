from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from examples.platform.bootstrap import start_examples_runtime

if TYPE_CHECKING:
    from msm.repositories.base import MarketsRepositoryContext


def create_account_fund_portfolio_workflow(context: "MarketsRepositoryContext") -> dict:
    """Create core records and build DataNode-ready frames."""

    from msm.services import (
        build_account_holdings_frame,
        build_target_positions_frame,
        create_account,
        create_fund,
        create_portfolio,
    )

    account = create_account(
        context,
        unique_identifier="account-main",
        display_name="Main Account",
        metadata_json={"venue": "example"},
    )
    portfolio = create_portfolio(
        context,
        unique_identifier="portfolio-btc-eth",
        calendar_name="24/7",
        portfolio_index_asset_unique_identifier="portfolio-btc-eth",
    )
    fund = create_fund(
        context,
        unique_identifier="fund-core",
        account_uid=_uid(account),
        portfolio_uid=_uid(portfolio),
        display_name="Core Fund",
    )

    holdings = build_account_holdings_frame(
        holdings_date="2026-05-25T00:00:00Z",
        account_uid=_uid(account),
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


def _uid(result: dict) -> str:
    if "uid" in result:
        return str(result["uid"])
    for key in ("row", "data"):
        row = result.get(key)
        if isinstance(row, dict) and "uid" in row:
            return str(row["uid"])
    rows = result.get("rows") or result.get("results")
    if isinstance(rows, list) and rows and "uid" in rows[0]:
        return str(rows[0]["uid"])
    raise KeyError("Could not resolve uid from MetaTable operation result.")


def main() -> None:
    runtime = start_examples_runtime(
        labels=["account-fund-portfolio-example"],
    )
    result = create_account_fund_portfolio_workflow(runtime.context)
    print(result)


if __name__ == "__main__":
    main()
