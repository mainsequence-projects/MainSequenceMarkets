from __future__ import annotations

# ruff: noqa: E402

from decimal import Decimal

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.pricing_engine import apply_z_spread_to_curve
from msm_pricing.pricing_engine.curve_overlays import (
    apply_z_spread_to_curve as direct_apply_z_spread_to_curve,
)

_REF = ql.Date(1, 1, 2026)
_DC = ql.Actual365Fixed()


def _flat_curve(rate: float) -> ql.FlatForward:
    curve = ql.FlatForward(_REF, rate, _DC, ql.Continuous, ql.NoFrequency)
    curve.enableExtrapolation()
    return curve


def _flat_handle(rate: float) -> ql.YieldTermStructureHandle:
    return ql.YieldTermStructureHandle(_flat_curve(rate))


def _continuous_zero_rate(
    handle: ql.YieldTermStructureHandle,
    days: int = 365,
) -> float:
    return handle.zeroRate(_REF + days, _DC, ql.Continuous, ql.NoFrequency).rate()


def test_apply_z_spread_to_curve_adds_continuous_decimal_spread() -> None:
    base = _flat_handle(0.05)

    spreaded = apply_z_spread_to_curve(base, 0.003)

    assert _continuous_zero_rate(spreaded) - _continuous_zero_rate(base) == pytest.approx(
        0.003,
        abs=1e-10,
    )


def test_apply_z_spread_to_curve_accepts_decimal_spread() -> None:
    base = _flat_handle(0.05)

    spreaded = apply_z_spread_to_curve(base, Decimal("0.0015"))

    assert _continuous_zero_rate(spreaded) - _continuous_zero_rate(base) == pytest.approx(
        0.0015,
        abs=1e-10,
    )


def test_apply_z_spread_to_curve_returns_same_handle_for_no_spread() -> None:
    base = _flat_handle(0.05)

    assert apply_z_spread_to_curve(base, None) is base
    assert apply_z_spread_to_curve(base, 0.0) is base
    assert apply_z_spread_to_curve(base, 1e-16) is base


def test_apply_z_spread_to_curve_accepts_raw_yield_term_structure() -> None:
    curve = _flat_curve(0.05)

    spreaded = apply_z_spread_to_curve(curve, 0.002)

    assert isinstance(spreaded, ql.YieldTermStructureHandle)
    assert _continuous_zero_rate(spreaded) == pytest.approx(0.052, abs=1e-10)


@pytest.mark.parametrize("bad_value", ["0.003", float("nan"), float("inf"), True, object()])
def test_apply_z_spread_to_curve_rejects_invalid_spread_values(bad_value: object) -> None:
    base = _flat_handle(0.05)

    with pytest.raises((TypeError, ValueError)):
        apply_z_spread_to_curve(base, bad_value)  # type: ignore[arg-type]


def test_apply_z_spread_to_curve_rejects_invalid_curve() -> None:
    with pytest.raises(TypeError, match="YieldTermStructureHandle"):
        apply_z_spread_to_curve(object(), 0.001)  # type: ignore[arg-type]


def test_apply_z_spread_to_curve_is_public_pricing_engine_export() -> None:
    assert apply_z_spread_to_curve is direct_apply_z_spread_to_curve
