"""Frames shared by the storage-copy tests of core and of ``msm_portfolios``."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

INDEX = ["time_index", "portfolio_identifier", "asset_identifier"]
DAY = [dt.datetime(2026, 1, day, tzinfo=dt.UTC) for day in (1, 2, 3)]


def _frame(rows: list[tuple[Any, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=[*INDEX, "weight"])
    return frame.set_index(INDEX)
