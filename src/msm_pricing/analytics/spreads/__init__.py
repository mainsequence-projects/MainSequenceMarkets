"""Cross-asset and asset-class-specific spread analytics.

`msm_pricing.analytics.spreads.base` owns cross-asset spread primitives such as
spread construction, z-scores, pair metrics, hedge-ratio estimation, and
forecast cones. Asset-class modules such as `fixed_income` add interpretation
that depends on domain units like DV01, carry, roll-down, or downside.
"""

from __future__ import annotations

from .base import (
    PairSpreadMetrics,
    SpreadSeries,
    build_pair_history_frame,
    build_spread_series,
    estimate_hedge_ratio,
    ornstein_uhlenbeck_forecast_cone,
    pair_spread_metrics,
    require_optional_dependency,
    rolling_spread_zscore,
    spread_zscore,
    spread_zscore_matrix,
)
from .fixed_income import (
    FixedIncomeLegMetrics,
    FixedIncomeSpreadMetrics,
    dv01_hedge_ratio,
    fixed_income_spread_metrics,
)

__all__ = [
    "FixedIncomeLegMetrics",
    "FixedIncomeSpreadMetrics",
    "PairSpreadMetrics",
    "SpreadSeries",
    "build_pair_history_frame",
    "build_spread_series",
    "dv01_hedge_ratio",
    "estimate_hedge_ratio",
    "fixed_income_spread_metrics",
    "ornstein_uhlenbeck_forecast_cone",
    "pair_spread_metrics",
    "require_optional_dependency",
    "rolling_spread_zscore",
    "spread_zscore",
    "spread_zscore_matrix",
]
