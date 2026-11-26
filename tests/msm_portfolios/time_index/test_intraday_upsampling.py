"""Intraday bars upsampled to a coarser frequency (#117).

Each session's target intervals start at its open; the last ends at its close and may be
shorter. A source bar belongs to the interval its close falls in, so one bar comes out per
interval that has bars, stamped at the interval's end. The tests run the interpolator and
``InterpolatedPrices.update()`` with only their reads replaced.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from msm_portfolios.contrib.prices import updaters

OPEN, CLOSE = pd.Timestamp("2026-09-04T13:30Z"), pd.Timestamp("2026-09-04T20:00Z")
NEXT_OPEN, NEXT_CLOSE = pd.Timestamp("2026-09-08T13:30Z"), pd.Timestamp("2026-09-08T20:00Z")


def schedule(*sessions):
    frame = pd.DataFrame(
        {
            "market_open": pd.to_datetime([opens for opens, _ in sessions], utc=True),
            "market_close": pd.to_datetime([closes for _, closes in sessions], utc=True),
        },
        index=pd.Index([pd.Timestamp(opens).date() for opens, _ in sessions], name="local_date"),
    )
    return frame


ONE_DAY = schedule((OPEN, CLOSE))


def bars(minutes, *, opens=OPEN, closes=CLOSE, drop=()):
    times = pd.date_range(opens + pd.Timedelta(minutes=minutes), closes, freq=f"{minutes}min")
    times = times.delete([times.get_loc(pd.Timestamp(t)) for t in drop])
    step = np.arange(len(times), dtype=float)
    return pd.DataFrame(
        {
            "open_time": times - pd.Timedelta(minutes=minutes),
            "open": 100.0 + step,
            "high": 101.0 + step,
            "low": 99.0 + step,
            "close": 100.5 + step,
            "volume": 10.0,
            "vwap": 100.25 + step,
            "trade_count": 3.0,
            "asset_identifier": "A",
        },
        index=pd.DatetimeIndex(times),
    )


def upsampled(source, target, frame, sessions=ONE_DAY, last_observation=None):
    return updaters.UpsampleAndInterpolation(
        f"{source}m", f"{target}m", "ffill"
    ).get_interpolated_upsampled_bars(
        schedule=sessions, tmp_df=frame, last_observation=last_observation
    )


@pytest.mark.parametrize(
    ("source", "target"), [(1, 5), (1, 15), (1, 30), (5, 15), (5, 30), (5, 60), (15, 30), (15, 60), (30, 60)]
)
def test_one_bar_per_target_interval_of_the_session(source, target) -> None:
    result = upsampled(source, target, bars(source))

    step = pd.Timedelta(minutes=target)
    ends = pd.date_range(OPEN + step, CLOSE, freq=step)
    if ends[-1] != CLOSE:
        ends = ends.append(pd.DatetimeIndex([CLOSE]))  # the last interval ends at the close
    assert list(result.index) == list(ends)
    starts = [max(OPEN, end - step) if end != CLOSE else ends[-2] for end in ends]
    starts[0] = OPEN
    assert list(result["open_time"]) == starts
    # Every source bar is counted once.
    assert result["volume"].sum() == pytest.approx(10.0 * len(bars(source)))
    assert result["trade_count"].sum() == pytest.approx(3.0 * len(bars(source)))
    assert not result["interpolated"].any()


def test_an_interval_aggregates_its_bars() -> None:
    source = bars(5)
    result = upsampled(5, 15, source)

    first = result.loc[OPEN + pd.Timedelta(minutes=15)]
    window = source[(source.index > OPEN) & (source.index <= OPEN + pd.Timedelta(minutes=15))]
    assert first["open"] == window["open"].iloc[0]
    assert first["close"] == window["close"].iloc[-1]
    assert first["high"] == window["high"].max()
    assert first["low"] == window["low"].min()
    assert first["volume"] == window["volume"].sum()
    assert first["vwap"] == pytest.approx((window["vwap"] * window["volume"]).sum() / window["volume"].sum())


def test_an_interval_is_interpolated_only_when_all_its_bars_were() -> None:
    # 13:35-13:45 observed, 13:50-14:00 missing: the 14:00 bar is wholly filled forward.
    gap = ["2026-09-04T13:50Z", "2026-09-04T13:55Z", "2026-09-04T14:00Z", "2026-09-04T13:40Z"]
    result = upsampled(5, 15, bars(5, drop=gap))

    assert len(result) == 26
    # Two observed bars and one filled forward, which traded nothing.
    assert result.loc[pd.Timestamp("2026-09-04T13:45Z"), "volume"] == 20
    assert not result.loc[pd.Timestamp("2026-09-04T13:45Z"), "interpolated"]
    assert result.loc[pd.Timestamp("2026-09-04T14:00Z"), "interpolated"]
    assert result.loc[pd.Timestamp("2026-09-04T14:00Z"), "volume"] == 0
    assert not result.loc[pd.Timestamp("2026-09-04T14:15Z"), "interpolated"]


def test_sessions_are_aggregated_apart() -> None:
    sessions = schedule((OPEN, CLOSE), (NEXT_OPEN, NEXT_CLOSE))
    source = pd.concat([bars(15), bars(15, opens=NEXT_OPEN, closes=NEXT_CLOSE)])

    result = upsampled(15, 60, source, sessions=sessions)

    # Six whole hours and the half hour to the close, then the next session's first hour.
    assert result.index[6] == CLOSE
    assert result.index[7] == NEXT_OPEN + pd.Timedelta(hours=1)
    assert result.loc[NEXT_OPEN + pd.Timedelta(hours=1), "open_time"] == NEXT_OPEN
    assert len(result) == 14


@pytest.mark.parametrize(("source", "target"), [(1, 5), (5, 15), (15, 60)])
@pytest.mark.parametrize("later_run", [False, True])
def test_update_writes_the_target_bars(source, target, later_run) -> None:
    raw = (
        bars(source, drop=[OPEN + pd.Timedelta(minutes=source * 3)])
        .rename_axis("time_index")
        .set_index("asset_identifier", append=True)
    )
    calendar = SimpleNamespace(calendar=SimpleNamespace(uid="calendar"), schedule=lambda start, end: ONE_DAY)

    class Probe:
        """The real update(), with only its reads replaced."""

        update = updaters.InterpolatedPrices.update
        get_upsampled_data = updaters.InterpolatedPrices.get_upsampled_data
        _transform_raw_data_to_upsampled_df = updaters.InterpolatedPrices._transform_raw_data_to_upsampled_df
        _schedule_frames = updaters.InterpolatedPrices._schedule_frames
        update_statistics = SimpleNamespace(
            are_all_identities_on_fallback_date=not later_run,
            filter_df_by_latest_value=lambda frame: frame,
        )
        logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)

        def __init__(self):
            self.bars_ts = SimpleNamespace(get_df_between_dates=self.read_bars)
            self.bar_frequency_id = f"{source}m"
            self.interpolator = updaters.UpsampleAndInterpolation(f"{source}m", f"{target}m", "ffill")

        def read_bars(self, **kwargs):
            # One read shares one deadline: the bars come in the largest page there is.
            assert kwargs["page_size"] == 10_000
            return raw

        def get_update_asset_list(self):
            return ["A"]

        def get_asset_dimension_range_map_great_or_equal(self):
            return {}

        def get_df_between_dates(self, **kwargs):
            return pd.DataFrame()

    original = updaters._asset_schedule_map
    updaters._asset_schedule_map = lambda assets: {"A": calendar}
    try:
        result = Probe().update()
    finally:
        updaters._asset_schedule_map = original

    times = result.index.get_level_values("time_index")
    step = pd.Timedelta(minutes=target)
    assert times[0] == OPEN + step
    assert times[-1] == CLOSE
    steps = list(times.to_series().diff().dropna())
    # Every interval is whole but the last, which ends at the close.
    assert set(steps[:-1]) == {step}
    assert steps[-1] == ((CLOSE - OPEN) % step or step)
    assert (pd.DatetimeIndex(result["open_time"]) >= OPEN).all()
    assert list(result.columns) == [
        "open_time", "open", "high", "low", "close", "volume", "trade_count", "vwap", "interpolated",
    ]
