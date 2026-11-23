from __future__ import annotations

import datetime as dt

import pandas as pd

from msm_portfolios.contrib.prices.updaters import (
    UpsampleAndInterpolation,
    interpolate_daily_bars,
    interpolate_intraday_bars,
)


def schedule_frame(sessions: list[tuple[str, str, str]]) -> pd.DataFrame:
    """A stored calendar's computed sessions: local date, open and close in UTC."""

    return pd.DataFrame(
        {
            "market_open": pd.to_datetime([opens for _, opens, _ in sessions], utc=True),
            "market_close": pd.to_datetime([closes for _, _, closes in sessions], utc=True),
        },
        index=pd.Index([dt.date.fromisoformat(day) for day, _, _ in sessions], name="local_date"),
    )


def always_open(first: str, days: int) -> pd.DataFrame:
    """A stored 24/7 calendar: every day runs from midnight to the next midnight."""

    starts = pd.date_range(first, periods=days, freq="D", tz="UTC")
    return schedule_frame(
        [
            (start.date().isoformat(), start.isoformat(), (start + pd.Timedelta(days=1)).isoformat())
            for start in starts
        ]
    )


def daily_bars(closes: dict[str, float]) -> pd.DataFrame:
    """Daily source bars, each stamped at its time of observation."""

    index = pd.to_datetime(list(closes), utc=True)
    values = list(closes.values())
    return pd.DataFrame(
        {
            "asset_identifier": "PROVIDER::asset",
            "open": [value - 1.0 for value in values],
            "high": [value + 0.5 for value in values],
            "low": [value - 1.5 for value in values],
            "close": values,
            "volume": 10.0,
            "vwap": values,
        },
        index=pd.DatetimeIndex(index),
    )


NYSE_SESSION = ("2026-09-04", "2026-09-04T13:30:00Z", "2026-09-04T20:00:00Z")


def test_daily_interpolation_derives_open_time_when_source_omits_it() -> None:
    market_open = pd.Timestamp("2026-09-04T13:30:00Z")
    market_close = pd.Timestamp("2026-09-04T20:00:00Z")
    source = pd.DataFrame(
        {
            "asset_identifier": ["PROVIDER::asset"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1_000.0],
        },
        index=pd.DatetimeIndex([market_close]),
    )

    result = interpolate_daily_bars(
        bars_df=source,
        interpolation_rule="ffill",
        schedule=schedule_frame([NYSE_SESSION]),
    )

    assert list(result.index) == [market_close]
    assert result.loc[market_close, "open_time"] == market_open


def test_daily_interpolation_preserves_microsecond_timestamp_columns() -> None:
    market_open = pd.Timestamp("2026-09-04T13:30:00Z")
    market_close = pd.Timestamp("2026-09-04T20:00:00Z")
    timestamp_dtype = "datetime64[us, UTC]"
    source = pd.DataFrame(
        {
            "asset_identifier": ["PROVIDER::asset"],
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

    result = UpsampleAndInterpolation(
        bar_frequency_id="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    ).get_interpolated_upsampled_bars(
        schedule=schedule_frame([NYSE_SESSION]),
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


def test_a_24_7_daily_bar_stays_at_its_midnight_close() -> None:
    """ADR 0056 4a: the window is chosen by close instant, not by date.

    Monday's bar is observed at Tuesday 00:00, where Monday's session closes. No
    bar is dropped at the start, moved a day, or invented after the last one.
    """

    source = daily_bars(
        {
            "2026-03-03T00:00:00Z": 101.0,  # Monday's close
            "2026-03-04T00:00:00Z": 102.0,
            "2026-03-05T00:00:00Z": 103.0,
            "2026-03-06T00:00:00Z": 104.0,  # Thursday's close
        }
    )

    result = interpolate_daily_bars(
        bars_df=source,
        interpolation_rule="ffill",
        # A day wider at both ends, as the updater asks for it.
        schedule=always_open("2026-03-01", 7),
    )

    assert list(result.index) == list(source.index)
    assert result["close"].tolist() == [101.0, 102.0, 103.0, 104.0]
    assert not result["interpolated"].any()
    # Monday's session opened at Monday 00:00.
    assert result["open_time"].iloc[0] == pd.Timestamp("2026-03-02T00:00:00Z")


def test_no_daily_bar_is_written_after_the_last_source_bar() -> None:
    source = daily_bars({"2026-09-03T20:00:00Z": 100.0, "2026-09-04T20:00:00Z": 101.0})
    schedule = schedule_frame(
        [
            ("2026-09-03", "2026-09-03T13:30:00Z", "2026-09-03T20:00:00Z"),
            NYSE_SESSION,
            ("2026-09-08", "2026-09-08T13:30:00Z", "2026-09-08T20:00:00Z"),
        ]
    )

    result = interpolate_daily_bars(bars_df=source, interpolation_rule="ffill", schedule=schedule)

    assert list(result.index) == list(source.index)


def test_a_session_the_source_missed_is_filled_and_flagged() -> None:
    """A hand-corrected calendar: the session closes later than the source's bar."""

    source = daily_bars(
        {
            "2024-12-23T21:00:00Z": 100.0,
            "2024-12-24T18:00:00Z": 101.0,  # the exchange's early close
            "2024-12-26T21:00:00Z": 102.0,
        }
    )
    schedule = schedule_frame(
        [
            ("2024-12-23", "2024-12-23T14:30:00Z", "2024-12-23T21:00:00Z"),
            ("2024-12-24", "2024-12-24T14:30:00Z", "2024-12-24T21:00:00Z"),  # a user's full day
            ("2024-12-26", "2024-12-26T14:30:00Z", "2024-12-26T21:00:00Z"),
        ]
    )

    result = interpolate_daily_bars(
        bars_df=source,
        interpolation_rule="ffill",
        schedule=schedule,
        last_observation=None,
    )

    filled = pd.Timestamp("2024-12-24T21:00:00Z")
    assert list(result.index) == [
        pd.Timestamp("2024-12-23T21:00:00Z"),
        filled,
        pd.Timestamp("2024-12-26T21:00:00Z"),
    ]
    assert result.loc[filled, "close"] == 101.0
    assert bool(result.loc[filled, "interpolated"])
    assert not bool(result.loc[pd.Timestamp("2024-12-26T21:00:00Z"), "interpolated"])


def test_intraday_interpolation_reads_sessions_from_the_schedule() -> None:
    """The intraday path takes computed sessions; a date with no session is skipped."""

    def minute_bars(day: str, times: list[str]) -> pd.DataFrame:
        index = pd.to_datetime([f"{day}T{time}:00Z" for time in times], utc=True)
        return pd.DataFrame(
            {
                "asset_identifier": "PROVIDER::asset",
                "open_time": index - pd.Timedelta(minutes=30),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 5.0,
                "vwap": 100.2,
            },
            index=pd.DatetimeIndex(index),
        )

    source = pd.concat(
        [
            minute_bars("2026-09-03", ["14:00", "15:00"]),
            minute_bars("2026-09-05", ["14:00"]),  # a Saturday: the calendar has no session
        ]
    )
    schedule = schedule_frame(
        [
            ("2026-09-03", "2026-09-03T13:30:00Z", "2026-09-03T15:00:00Z"),
            NYSE_SESSION,
        ]
    )

    result = interpolate_intraday_bars(
        bars_df=source,
        interpolation_rule="ffill",
        bars_frequency_min=30,
        schedule=schedule,
    )

    assert set(result["trade_day"]) == {pd.Timestamp("2026-09-03T00:00:00Z")}
    assert list(result.index) == list(
        pd.date_range("2026-09-03T13:30:00Z", "2026-09-03T15:00:00Z", freq="30min")
    )
    # 14:30 had no source bar: it is filled from 14:00 and flagged.
    assert bool(result.loc[pd.Timestamp("2026-09-03T14:30:00Z"), "interpolated"])
