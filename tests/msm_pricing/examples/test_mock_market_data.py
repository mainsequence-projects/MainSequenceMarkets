from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_PROJECT_ROOT)]

from examples.msm_pricing.utils import (  # noqa: E402
    DEFAULT_FIXING_LOOKBACK_DAYS,
    EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
    EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
    build_flat_forward_key_nodes,
    build_mock_fixings_frame,
)
from examples.msm_pricing.pricing_valuation_context import (  # noqa: E402
    build_mock_context_workflow,
)


def test_mock_fixings_default_to_one_month_window() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    frame = build_mock_fixings_frame(
        index_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
        valuation_date=valuation_date,
        fixing_rate=0.0525,
    )

    assert 0 < len(frame) < 40
    assert frame["index_identifier"].unique().tolist() == [EXAMPLE_INDEX_UNIQUE_IDENTIFIER]
    assert frame["rate"].unique().tolist() == [0.0525]
    assert frame["time_index"].min() >= pd.Timestamp(
        valuation_date - dt.timedelta(days=DEFAULT_FIXING_LOOKBACK_DAYS)
    )
    assert frame["time_index"].max() <= pd.Timestamp(valuation_date)


def test_mock_curve_key_nodes_use_recommended_yield_shape() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    key_nodes = build_flat_forward_key_nodes(
        valuation_date=valuation_date,
        zero_rate=0.0525,
        sampling_days=(30,),
    )

    assert key_nodes == [
        {
            "maturity_date": "2026-06-26",
            "instrument_type": "direct_zero_rate",
            "quote": 0.0525,
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
            "quote_side": "mid",
            "yield": 0.0525,
        }
    ]


def test_pricing_valuation_context_example_runs_with_mock_market_data() -> None:
    result = build_mock_context_workflow()

    assert result["cached_curve_identifier"] == EXAMPLE_CURVE_UNIQUE_IDENTIFIER
    assert result["cached_index_family"] == "ibor"
    assert result["mock_curve_nodes"] > 1
    assert result["mock_fixing_rows"] > 1
    assert result["original_valuation_date"] is None
    assert result["prepared_valuation_date"] == "2026-05-27T00:00:00+00:00"
    assert result["unit_price"] > 0
    assert result["market_value"] == result["unit_price"] * 4.0
    assert result["prepared_analytics"]["unit_price"] == result["unit_price"]
    assert result["prepared_analytics"]["one_year_zero_rate"] > 0
