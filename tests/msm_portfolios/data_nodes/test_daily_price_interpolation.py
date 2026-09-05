from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from msm_portfolios.contrib.prices.data_nodes import interpolate_daily_bars


def test_daily_interpolation_derives_open_time_when_source_omits_it() -> None:
    market_open = pd.Timestamp("2026-09-04T13:30:00Z")
    market_close = pd.Timestamp("2026-09-04T20:00:00Z")
    source = pd.DataFrame(
        {
            "asset_identifier": ["ALPACA::asset"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1_000.0],
        },
        index=pd.DatetimeIndex([market_close]),
    )
    schedule = pd.DataFrame(
        {
            "market_open": [market_open],
            "market_close": [market_close],
        },
        index=pd.Index([pd.Timestamp("2026-09-04")], name="session"),
    )

    with patch(
        "msm_portfolios.contrib.prices.data_nodes._get_schedule_cached",
        return_value=schedule,
    ):
        result = interpolate_daily_bars(
            bars_df=source,
            interpolation_rule="ffill",
            calendar="NYSE",
        )

    assert list(result.index) == [market_close]
    assert result.loc[market_close, "open_time"] == market_open
