"""The portfolio updaters write nothing dated at or after ``retired_at`` (ADR 0049).

Each updater clamps the end of its update window to the last instant before the
boundary, so a run after retirement reads only the window up to it, and drops any
row dated at or after it from its output. The storage tables do not enforce the
boundary; a direct table write bypasses it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import pandas as pd

TIME_INDEX = "time_index"


def retirement_boundary(portfolio: Any) -> pd.Timestamp | None:
    """Return the portfolio's ``retired_at`` as a UTC timestamp, or ``None`` while live."""

    if portfolio is None:
        return None
    if isinstance(portfolio, Mapping):
        retired_at = portfolio.get("retired_at")
    else:
        retired_at = getattr(portfolio, "retired_at", None)
    if retired_at in (None, ""):
        return None
    timestamp = pd.Timestamp(retired_at)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def end_before_retirement(end: Any, boundary: pd.Timestamp | None) -> Any:
    """Clamp a window end to the last instant before ``boundary``, keeping its type."""

    if boundary is None:
        return end
    if isinstance(end, pd.Timestamp):
        return min(end, boundary - pd.Timedelta(1, unit="ns"))
    if isinstance(end, dt.datetime):
        last = (boundary - pd.Timedelta(1, unit="us")).to_pydatetime()
        return min(end, last)
    return end


def window_is_empty(start: Any, end: Any) -> bool:
    return pd.Timestamp(start) >= pd.Timestamp(end)


def drop_retired_rows(frame: pd.DataFrame, boundary: pd.Timestamp | None) -> pd.DataFrame:
    """Drop the rows dated at or after ``boundary`` from an updater's output."""

    if boundary is None or frame is None or frame.empty:
        return frame
    if TIME_INDEX in (frame.index.names or []):
        times = pd.to_datetime(frame.index.get_level_values(TIME_INDEX), utc=True)
    elif TIME_INDEX in frame.columns:
        times = pd.to_datetime(frame[TIME_INDEX], utc=True)
    else:
        return frame
    keep = pd.Series(times < boundary, index=frame.index).to_numpy()
    return frame[keep]


__all__ = [
    "drop_retired_rows",
    "end_before_retirement",
    "retirement_boundary",
    "window_is_empty",
]
