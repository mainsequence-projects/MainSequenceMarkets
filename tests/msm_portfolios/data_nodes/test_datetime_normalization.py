from __future__ import annotations

import datetime as dt

import pandas as pd

from msm_portfolios.data_nodes.portfolios.weights import PortfolioWeights

MICROSECOND_TIME = dt.datetime(2026, 5, 26, 18, 50, 19, 240235, tzinfo=dt.UTC)
EXPECTED_DTYPE = "datetime64[ns, UTC]"


def _dtype(frame: pd.DataFrame, column_name: str) -> str:
    return str(frame.reset_index()[column_name].dtype)


def test_portfolio_time_columns_are_datetime64_ns_utc() -> None:
    frame = PortfolioWeights.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": MICROSECOND_TIME,
                    "portfolio_index_identifier": "portfolio-1",
                    "asset_identifier": "asset-1",
                    "weight": 1.0,
                    "weight_before": 0.0,
                    "price_current": 100.0,
                    "price_before": 99.0,
                    "volume_current": 1000.0,
                    "volume_before": 900.0,
                }
            ]
        )
    )

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE
