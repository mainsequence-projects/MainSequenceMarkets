"""Compatibility exports for generic spread analytics.

The canonical implementations live in :mod:`msm.analytics.indices.spreads`.
This module remains import-compatible for callers that used the former
``msm_pricing`` path; pricing-specific adapters may continue to import it.
"""

from msm.analytics.indices.spreads import (
    HedgeRatioMethod,
    NumericSeriesInput,
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

__all__ = [
    "HedgeRatioMethod",
    "NumericSeriesInput",
    "PairSpreadMetrics",
    "SpreadSeries",
    "build_pair_history_frame",
    "build_spread_series",
    "estimate_hedge_ratio",
    "ornstein_uhlenbeck_forecast_cone",
    "pair_spread_metrics",
    "require_optional_dependency",
    "rolling_spread_zscore",
    "spread_zscore",
    "spread_zscore_matrix",
]
