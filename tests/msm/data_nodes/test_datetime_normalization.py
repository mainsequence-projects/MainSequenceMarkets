from __future__ import annotations

import datetime as dt
import os

import pandas as pd

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.accounts import AccountHoldings
from msm.data_nodes.assets import AssetSnapshot
from msm.data_nodes.execution import Orders
from msm.portfolios.data_nodes.portfolio_weights import PortfolioWeights

MICROSECOND_TIME = dt.datetime(2026, 5, 26, 18, 50, 19, 240235, tzinfo=dt.UTC)
EXPECTED_DTYPE = "datetime64[ns, UTC]"


def _dtype(frame: pd.DataFrame, column_name: str) -> str:
    return str(frame.reset_index()[column_name].dtype)


def test_asset_snapshot_time_index_is_datetime64_ns_utc() -> None:
    frame = AssetSnapshot.build_frame(
        {
            "time_index": MICROSECOND_TIME,
            "unique_identifier": "example-asset-btc",
            "ticker": "BTC",
        }
    )

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE


def test_execution_time_columns_are_datetime64_ns_utc() -> None:
    frame = Orders.build_schema_bootstrap_frame(time_index=MICROSECOND_TIME)

    assert _dtype(frame, "order_time") == EXPECTED_DTYPE
    assert _dtype(frame, "expires_time") == EXPECTED_DTYPE


def test_holdings_time_columns_are_datetime64_ns_utc() -> None:
    frame = AccountHoldings.build_schema_bootstrap_frame(time_index=MICROSECOND_TIME)

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE
    assert _dtype(frame, "target_trade_time") == EXPECTED_DTYPE


def test_portfolio_time_columns_are_datetime64_ns_utc() -> None:
    frame = PortfolioWeights.build_schema_bootstrap_frame(time_index=MICROSECOND_TIME)

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE
