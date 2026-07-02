from __future__ import annotations

import math

import pytest

from msm_pricing.analytics.spreads import dv01_hedge_ratio, fixed_income_spread_metrics


def test_dv01_hedge_ratio_returns_subtracted_hedge_multiplier() -> None:
    assert dv01_hedge_ratio(base_dv01=100.0, hedge_dv01=80.0) == 1.25


def test_dv01_hedge_ratio_rejects_zero_hedge_dv01() -> None:
    with pytest.raises(ValueError, match="hedge_dv01 must be non-zero"):
        dv01_hedge_ratio(base_dv01=100.0, hedge_dv01=0.0)


def test_fixed_income_spread_metrics_use_dv01_neutral_ratio_by_default() -> None:
    metrics = fixed_income_spread_metrics(
        base_values=[100.0, 101.0, 102.0],
        hedge_values=[80.0, 80.5, 81.0],
        base_dv01=100.0,
        hedge_dv01=80.0,
        base_carry=5.0,
        hedge_carry=2.0,
        base_roll_down=3.0,
        hedge_roll_down=1.0,
        base_downside=-8.0,
        hedge_downside=-4.0,
        spread_name="bond_rv",
        base_name="asset",
        hedge_name="benchmark",
    )

    assert metrics.spread_name == "bond_rv"
    assert metrics.hedge_ratio == 1.25
    assert metrics.dv01_hedge_ratio == 1.25
    assert metrics.net_dv01 == 0.0
    assert metrics.spread.values.to_list() == [0.0, 0.375, 0.75]
    assert metrics.pair_metrics.observation_count == 3
    assert metrics.base_leg.market_value == 102.0
    assert metrics.hedge_leg.market_value == 81.0
    assert metrics.carry == 2.5
    assert metrics.roll_down == 1.75
    assert metrics.downside == -3.0


def test_fixed_income_spread_metrics_allow_explicit_non_neutral_ratio() -> None:
    metrics = fixed_income_spread_metrics(
        base_values=[100.0, 101.0],
        hedge_values=[80.0, 80.5],
        base_dv01=100.0,
        hedge_dv01=80.0,
        hedge_ratio=1.0,
    )

    assert metrics.hedge_ratio == 1.0
    assert metrics.dv01_hedge_ratio == 1.25
    assert math.isclose(metrics.net_dv01, 20.0, rel_tol=1e-12)
