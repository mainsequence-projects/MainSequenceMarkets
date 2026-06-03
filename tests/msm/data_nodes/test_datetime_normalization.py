from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.assets import AssetSnapshot
from msm.data_nodes.execution import Orders
from msm.services.holdings import build_account_holdings_frame

MICROSECOND_TIME = dt.datetime(2026, 5, 26, 18, 50, 19, 240235, tzinfo=dt.UTC)
EXPECTED_DTYPE = "datetime64[ns, UTC]"


def _dtype(frame: pd.DataFrame, column_name: str) -> str:
    return str(frame.reset_index()[column_name].dtype)


def test_asset_snapshot_time_index_is_datetime64_ns_utc() -> None:
    frame = AssetSnapshot.build_frame(
        {
            "time_index": MICROSECOND_TIME,
            "asset_identifier": "example-asset-btc",
            "ticker": "BTC",
        }
    )

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE


def test_execution_time_columns_are_datetime64_ns_utc() -> None:
    frame = Orders.validate_frame(
        pd.DataFrame(
            [
                {
                    "order_time": MICROSECOND_TIME,
                    "order_identifier": "order-1",
                    "account_identifier": "account-1",
                    "fund_identifier": "",
                    "order_manager_identifier": "",
                    "asset_identifier": "asset-1",
                    "order_remote_id": "",
                    "client_order_id": "",
                    "order_type": "market",
                    "order_side": 1,
                    "quantity": 1.0,
                    "status": "open",
                    "filled_quantity": 0.0,
                    "filled_price": 0.0,
                    "expires_time": MICROSECOND_TIME,
                    "limit_price": 0.0,
                    "time_in_force": "",
                    "comments": "",
                    "venue_metadata": {},
                }
            ]
        )
    )

    assert _dtype(frame, "order_time") == EXPECTED_DTYPE
    assert _dtype(frame, "expires_time") == EXPECTED_DTYPE


def test_holdings_time_columns_are_datetime64_ns_utc() -> None:
    frame = build_account_holdings_frame(
        holdings_date=MICROSECOND_TIME,
        account_uid=uuid.uuid4(),
        holdings_set_uid=uuid.uuid4(),
        positions=[
            {
                "asset_identifier": "asset-1",
                "quantity": 1,
                "target_trade_time": MICROSECOND_TIME,
            }
        ],
    )

    assert _dtype(frame, "time_index") == EXPECTED_DTYPE
    assert _dtype(frame, "target_trade_time") == EXPECTED_DTYPE
    target_trade_time = frame.reset_index()["target_trade_time"].iloc[0]
    assert target_trade_time.tzinfo is not None
    assert target_trade_time.utcoffset() == dt.timedelta(0)
