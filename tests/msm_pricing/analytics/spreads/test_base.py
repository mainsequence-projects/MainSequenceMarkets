from __future__ import annotations

import math

import pandas as pd
import pytest

from msm_pricing.analytics.spreads import (
    build_pair_history_frame,
    build_spread_series,
    estimate_hedge_ratio,
    ornstein_uhlenbeck_forecast_cone,
    pair_spread_metrics,
    require_optional_dependency,
    rolling_spread_zscore,
    spread_zscore_matrix,
)


def test_build_spread_series_aligns_by_index_and_does_not_mutate_inputs() -> None:
    leg_a = pd.Series(
        [10.0, 11.0, 12.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        name="submitted_a",
    )
    leg_b = pd.Series(
        [8.0, 9.0, 10.0],
        index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        name="submitted_b",
    )

    spread = build_spread_series(
        leg_a,
        leg_b,
        hedge_ratio=2.0,
        name="rv_spread",
        leg_a_name="bond_a",
        leg_b_name="bond_b",
    )

    assert spread.name == "rv_spread"
    assert spread.leg_a_name == "bond_a"
    assert spread.leg_b_name == "bond_b"
    assert spread.hedge_ratio == 2.0
    assert spread.values.to_list() == [-5.0, -6.0]
    assert leg_a.name == "submitted_a"
    assert leg_b.name == "submitted_b"


def test_pair_history_frame_has_stable_columns_and_attrs() -> None:
    frame = build_pair_history_frame([10.0, 11.0], [7.0, 8.0], hedge_ratio=0.5)

    assert frame.columns.to_list() == ["leg_a", "leg_b", "spread"]
    assert frame["spread"].to_list() == [6.5, 7.0]
    assert frame.attrs["hedge_ratio"] == 0.5


def test_spread_zscore_matrix_handles_multiple_spreads_and_flat_history() -> None:
    matrix = spread_zscore_matrix(
        pd.DataFrame(
            {
                "alpha": [1.0, 2.0, 3.0],
                "flat": [2.0, 2.0, 2.0],
            }
        )
    )

    assert matrix.loc["alpha", "latest_spread"] == 3.0
    assert matrix.loc["alpha", "mean"] == 2.0
    assert matrix.loc["alpha", "standard_deviation"] == 1.0
    assert matrix.loc["alpha", "z_score"] == 1.0
    assert matrix.loc["flat", "observation_count"] == 3
    assert pd.isna(matrix.loc["flat", "z_score"])


def test_rolling_spread_zscore_returns_aligned_series() -> None:
    z_scores = rolling_spread_zscore(pd.Series([1.0, 2.0, 3.0]), window=2)

    assert z_scores.index.to_list() == [0, 1, 2]
    assert pd.isna(z_scores.iloc[0])
    assert math.isclose(z_scores.iloc[2], 0.70710678118, rel_tol=1e-9)


def test_estimate_hedge_ratio_uses_ols_beta() -> None:
    hedge_ratio = estimate_hedge_ratio(
        leg_a=pd.Series([3.0, 5.0, 7.0, 9.0]),
        leg_b=pd.Series([1.0, 2.0, 3.0, 4.0]),
    )

    assert math.isclose(hedge_ratio, 2.0, rel_tol=1e-12)


def test_pair_spread_metrics_can_estimate_hedge_ratio() -> None:
    metrics = pair_spread_metrics(
        leg_a=pd.Series([3.0, 5.1, 6.9, 9.2]),
        leg_b=pd.Series([1.0, 2.0, 3.0, 4.0]),
        spread_name="pair",
    )

    assert metrics.spread_name == "pair"
    assert metrics.observation_count == 4
    assert math.isfinite(metrics.hedge_ratio)
    assert metrics.latest_spread is not None


def test_ornstein_uhlenbeck_forecast_cone_returns_expected_band_columns() -> None:
    values: list[float] = []
    level = 2.0
    for _ in range(20):
        level = 0.25 + 0.7 * level
        values.append(level)

    cone = ornstein_uhlenbeck_forecast_cone(values, horizon=3)

    assert cone.index.to_list() == [1, 2, 3]
    assert {"expected", "standard_deviation", "lower_1std", "upper_2std"} <= set(cone.columns)
    assert cone["expected"].notna().all()


def test_missing_optional_dependency_has_clear_error() -> None:
    with pytest.raises(ImportError, match="example optional forecast"):
        require_optional_dependency(
            "__definitely_missing_msm_pricing_dependency__",
            feature="example optional forecast",
        )
