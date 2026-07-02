from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm.data_nodes.assets.storage import AssetSnapshotsStorage  # noqa: E402
from msm.models import AssetTable, PortfolioTable  # noqa: E402
from msm.services.assets import asset_reference_details  # noqa: E402
from msm_portfolios.data_nodes.portfolios.storage import (  # noqa: E402
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.services import latest_portfolio_weights, portfolio_values  # noqa: E402


def build_portfolio_read_services_example() -> dict[str, Any]:
    portfolio_identifier = "example-target-portfolio"
    snapshot_time = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    def portfolio_executor(_statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        if models == (PortfolioTable, PortfolioWeightsStorage):
            return {
                "rows": [
                    {
                        "portfolio_uid": "portfolio-row-uid",
                        "portfolio_identifier": portfolio_identifier,
                        "time_index": snapshot_time,
                        "asset_identifier": "BBG000B9XRY4",
                        "weight": 0.6,
                    },
                    {
                        "portfolio_uid": "portfolio-row-uid",
                        "portfolio_identifier": portfolio_identifier,
                        "time_index": snapshot_time,
                        "asset_identifier": "BBG000BVPV84",
                        "weight": 0.4,
                    },
                ]
            }
        if models == (PortfolioTable, PortfoliosStorage):
            return {
                "rows": [
                    {
                        "portfolio_uid": "portfolio-row-uid",
                        "portfolio_identifier": portfolio_identifier,
                        "time_index": snapshot_time,
                        "close": 101.25,
                        "return": 0.0125,
                    }
                ]
            }
        raise AssertionError(f"unexpected portfolio models: {models!r}")

    def asset_executor(_statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        if models != (AssetTable, AssetSnapshotsStorage):
            raise AssertionError(f"unexpected asset models: {models!r}")
        return {
            "rows": [
                {
                    "asset_uid": "apple-row-uid",
                    "asset_identifier": "BBG000B9XRY4",
                    "asset_type": "equity",
                    "snapshot_time": snapshot_time,
                    "name": "APPLE INC",
                    "ticker": "AAPL",
                    "exchange_code": "US",
                },
                {
                    "asset_uid": "microsoft-row-uid",
                    "asset_identifier": "BBG000BVPV84",
                    "asset_type": "equity",
                    "snapshot_time": snapshot_time,
                    "name": "MICROSOFT CORP",
                    "ticker": "MSFT",
                    "exchange_code": "US",
                },
            ]
        }

    weights = latest_portfolio_weights(
        portfolio_identifier,
        weights_date=snapshot_time,
        executor=portfolio_executor,
    )
    values = portfolio_values(
        portfolio_identifier,
        latest_only=True,
        executor=portfolio_executor,
    )
    assets = asset_reference_details(
        [row["asset_identifier"] for row in weights],
        executor=asset_executor,
    )

    return {
        "portfolio_identifier": portfolio_identifier,
        "weights": weights,
        "values": values,
        "assets": assets,
    }


if __name__ == "__main__":
    print(json.dumps(build_portfolio_read_services_example(), default=str, indent=2))
