from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_PROJECT_ROOT)]

from examples.msm_pricing.utils import (  # noqa: E402
    DEFAULT_FIXING_LOOKBACK_DAYS,
    EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
    build_mock_fixings_frame,
)


def test_mock_fixings_default_to_one_month_window() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    frame = build_mock_fixings_frame(
        unique_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
        valuation_date=valuation_date,
        fixing_rate=0.0525,
    )

    assert 0 < len(frame) < 40
    assert frame["unique_identifier"].unique().tolist() == [EXAMPLE_INDEX_UNIQUE_IDENTIFIER]
    assert frame["rate"].unique().tolist() == [0.0525]
    assert frame["time_index"].min() >= pd.Timestamp(
        valuation_date - dt.timedelta(days=DEFAULT_FIXING_LOOKBACK_DAYS)
    )
    assert frame["time_index"].max() <= pd.Timestamp(valuation_date)
