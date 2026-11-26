"""InterpolatedPrices reads its source bars in reads that each fit one MetaTables budget (#155).

MetaTables gives one read at most 100,000 rows. A first run of 45 new daily assets has more
bars than that, and one read of them all failed. The source here refuses a read over the
budget, as MetaTables does, and every bar must still arrive once.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pandas as pd
from metatables.client.transfer import DEFAULT_LIMITS
from metatables.contracts.transfer import TransferLimitError

from msm_portfolios.contrib.prices import updaters

UTC = datetime.UTC
OFFSET_START = updaters.InterpolatedPrices.OFFSET_START
NOW = datetime.datetime(2026, 11, 26, 15, tzinfo=UTC)


def asset_range(asset, start, **bounds):
    return {
        "coordinate": {"asset_identifier": asset},
        "start_date_operand": ">=",
        "start_date": start,
        **bounds,
    }


def in_range(times: pd.DatetimeIndex, entry) -> pd.DatetimeIndex:
    start = pd.Timestamp(entry["start_date"])
    keep = times > start if entry["start_date_operand"] == ">" else times >= start
    if "end_date" in entry:
        end = pd.Timestamp(entry["end_date"])
        keep &= times < end if entry["end_date_operand"] == "<" else times <= end
    return times[keep]


class BudgetedSource:
    """Daily bars at midnight for every asset, read as MetaTables reads them: all of one
    read's rows under one budget."""

    def __init__(self, now):
        self.times = pd.date_range(OFFSET_START, now, freq="1D")
        self.reads = []

    def get_df_between_dates(self, *, dimension_range_map, page_size):
        assert page_size == updaters.BARS_READ_PAGE_SIZE
        self.reads.append(dimension_range_map)
        frames = []
        for entry in dimension_range_map:
            times = in_range(self.times, entry)
            asset = entry["coordinate"]["asset_identifier"]
            frames.append(
                pd.DataFrame(
                    {"close": 1.0},
                    index=pd.MultiIndex.from_arrays(
                        [times, [asset] * len(times)], names=["time_index", "asset_identifier"]
                    ),
                )
            )
        frame = pd.concat(frames)
        if len(frame) > DEFAULT_LIMITS.collection_rows:
            raise TransferLimitError("Collection budget exceeded")
        return frame


def read_bars(ranges, now):
    """The real ``get_upsampled_data``, with the frame it would interpolate returned."""

    class Probe:
        get_upsampled_data = updaters.InterpolatedPrices.get_upsampled_data
        bar_frequency_id = "1d"
        logger = SimpleNamespace(info=lambda *a, **k: None)

        def __init__(self):
            self.bars_ts = BudgetedSource(now)

        def get_asset_dimension_range_map_great_or_equal(self):
            return ranges

        def _transform_raw_data_to_upsampled_df(self, raw):
            return raw

    probe = Probe()
    return probe.get_upsampled_data(), probe.bars_ts


def test_a_first_run_of_45_new_daily_assets_reads_every_bar() -> None:
    assets = [f"A{n:02d}" for n in range(45)]
    ranges = [asset_range(asset, OFFSET_START) for asset in assets]
    source = BudgetedSource(datetime.datetime.now(UTC))
    # One read of them all is over the budget.
    assert len(source.times) * len(assets) > DEFAULT_LIMITS.collection_rows

    raw, source = read_bars(ranges, datetime.datetime.now(UTC))

    assert len(source.reads) > 1
    assert len(raw) == len(source.times) * len(assets)
    assert not raw.reset_index().duplicated(subset=["time_index", "asset_identifier"]).any()
    assert set(raw.groupby("asset_identifier").size()) == {len(source.times)}


def test_reads_stay_inside_the_planned_bars_and_assets() -> None:
    interval = datetime.timedelta(days=1)
    ranges = [asset_range(f"A{n}", OFFSET_START) for n in range(45)]
    ranges += [asset_range(f"B{n}", NOW - interval) for n in range(1_000)]

    reads = updaters._bars_reads(ranges, interval=interval, now=NOW)

    for read in reads:
        assert len(read) <= updaters.BARS_READ_ASSETS
        assert sum((NOW - entry["start_date"]) // interval + 1 for entry in read) <= (
            updaters.BARS_READ_ROWS
        )
    # Every range is read once, unchanged and in order.
    assert [entry for read in reads for entry in read] == ranges


def test_an_asset_with_more_bars_than_a_read_is_read_in_windows() -> None:
    interval = datetime.timedelta(minutes=1)
    start = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    ranges = [asset_range("A", start, start_date_operand=">"), asset_range("B", NOW - interval)]

    reads = updaters._bars_reads(ranges, interval=interval, now=NOW)

    windows = [
        entry for read in reads for entry in read if entry["coordinate"]["asset_identifier"] == "A"
    ]
    assert len(windows) > 1
    # Only the first window keeps the range's own start operand; each window ends where the
    # next starts, and the last is open-ended.
    assert [w["start_date_operand"] for w in windows] == [">"] + [">="] * (len(windows) - 1)
    assert windows[0]["start_date"] == start
    for window, following in zip(windows, windows[1:], strict=False):
        assert window["end_date_operand"] == "<"
        assert window["end_date"] == following["start_date"]
    assert "end_date" not in windows[-1]
    # Every minute after the start is in exactly one window, and no read is over its bars.
    minutes = pd.date_range(start, NOW, freq="1min")
    parts = [in_range(minutes, window) for window in windows]
    assert parts[0].append(parts[1:]).equals(minutes[1:])
    for read in reads:
        assert sum(len(in_range(minutes, entry)) for entry in read) <= updaters.BARS_READ_ROWS
    # The small asset shares the last window's read.
    assert reads[-1] == [windows[-1], ranges[1]]
