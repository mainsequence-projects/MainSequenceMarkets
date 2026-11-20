from __future__ import annotations

import pandas as pd

from msm.analytics.indices import (
    build_pair_history_frame as core_build_pair_history_frame,
    estimate_hedge_ratio as core_estimate_hedge_ratio,
    spread_zscore as core_spread_zscore,
)
from msm_pricing.analytics.spreads import (
    build_pair_history_frame as pricing_build_pair_history_frame,
    estimate_hedge_ratio as pricing_estimate_hedge_ratio,
    spread_zscore as pricing_spread_zscore,
)


def test_msm_pricing_generic_spread_imports_delegate_to_core_implementations() -> None:
    assert pricing_build_pair_history_frame is core_build_pair_history_frame
    assert pricing_estimate_hedge_ratio is core_estimate_hedge_ratio
    assert pricing_spread_zscore is core_spread_zscore


def test_existing_two_leg_results_have_exact_core_parity() -> None:
    index = pd.date_range("2025-01-01", periods=5, tz="UTC")
    left = pd.Series([10.0, 11.0, 13.0, 12.0, 14.0], index=index)
    right = pd.Series([4.0, 4.5, 5.0, 5.5, 6.0], index=index)

    pd.testing.assert_frame_equal(
        pricing_build_pair_history_frame(left, right, hedge_ratio=1.5),
        core_build_pair_history_frame(left, right, hedge_ratio=1.5),
    )
    assert pricing_estimate_hedge_ratio(left, right) == core_estimate_hedge_ratio(left, right)
    assert pricing_spread_zscore(left - right) == core_spread_zscore(left - right)
