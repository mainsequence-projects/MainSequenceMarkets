from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from msm_portfolios.contrib.prices.data_nodes import (
    UpsampleAndInterpolation,
    interpolate_daily_bars,
)


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


def test_daily_interpolation_preserves_microsecond_timestamp_columns() -> None:
    market_open = pd.Timestamp("2026-09-04T13:30:00Z")
    market_close = pd.Timestamp("2026-09-04T20:00:00Z")
    timestamp_dtype = "datetime64[us, UTC]"
    source = pd.DataFrame(
        {
            "asset_identifier": ["ALPACA::asset"],
            "open_time": pd.array([market_open], dtype=timestamp_dtype),
            "first_trade_time": pd.array([market_open], dtype=timestamp_dtype),
            "last_trade_time": pd.array([market_close], dtype=timestamp_dtype),
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1_000.0],
            "trade_count": [10.0],
            "vwap": [100.5],
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
        result = UpsampleAndInterpolation(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
        ).get_interpolated_upsampled_bars(
            calendar="NYSE",
            tmp_df=source,
        )

    expected = {
        "open_time": market_open,
        "first_trade_time": market_open,
        "last_trade_time": market_close,
    }
    for column_name, expected_timestamp in expected.items():
        assert str(result[column_name].dtype) == "datetime64[ns, UTC]"
        assert result.loc[market_close, column_name] == expected_timestamp


def test_intraday_interpolation_preserves_microsecond_timestamp_columns() -> None:
    market_open = pd.Timestamp("2026-09-04T13:30:00Z")
    first_close = pd.Timestamp("2026-09-04T13:35:00Z")
    second_close = pd.Timestamp("2026-09-04T13:40:00Z")
    timestamp_dtype = "datetime64[us, UTC]"
    source = pd.DataFrame(
        {
            "asset_identifier": ["ALPACA::asset", "ALPACA::asset"],
            "open_time": pd.array(
                [market_open, first_close],
                dtype=timestamp_dtype,
            ),
            "first_trade_time": pd.array(
                [market_open, first_close],
                dtype=timestamp_dtype,
            ),
            "last_trade_time": pd.array(
                [first_close, second_close],
                dtype=timestamp_dtype,
            ),
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1_000.0, 1_100.0],
            "trade_count": [10.0, 11.0],
            "vwap": [100.5, 101.5],
        },
        index=pd.DatetimeIndex([first_close, second_close]),
    )

    result = UpsampleAndInterpolation(
        bar_frequency_id="5m",
        upsample_frequency_id="5m",
        intraday_bar_interpolation_rule="ffill",
    ).get_interpolated_upsampled_bars(
        calendar=SimpleNamespace(name="NYSE"),
        tmp_df=source,
    )

    expected = {
        "open_time": market_open,
        "first_trade_time": market_open,
        "last_trade_time": first_close,
    }
    for column_name, expected_timestamp in expected.items():
        assert str(result[column_name].dtype) == "datetime64[ns, UTC]"
        assert result.loc[first_close, column_name] == expected_timestamp
    assert str(result["trade_day"].dtype) == "datetime64[ns, UTC]"
    assert result.loc[first_close, "trade_day"] == market_open.normalize()
