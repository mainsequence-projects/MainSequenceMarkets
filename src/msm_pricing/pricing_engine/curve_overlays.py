"""Derived QuantLib curve overlays used by pricing workflows."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import TypeAlias

import QuantLib as ql

NumericSpread: TypeAlias = int | float | Decimal

_ZERO_SPREAD_TOLERANCE = 1e-15


def apply_z_spread_to_curve(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure,
    z_spread_decimal: NumericSpread | None,
) -> ql.YieldTermStructureHandle:
    """Return ``curve`` overlaid with a decimal z-spread.

    ``Bond.z_spread(...)`` returns a decimal spread quoted as a continuous
    zero-rate spread. This helper applies that exact convention to a resolved
    curve handle. The overlay is derived runtime state; it does not mutate the
    base curve, persisted curve nodes, or ``CurveBuildingDetails``.
    """

    handle = _coerce_curve_handle(curve)
    if z_spread_decimal is None:
        return handle

    spread_value = _coerce_z_spread_decimal(z_spread_decimal)
    if abs(spread_value) < _ZERO_SPREAD_TOLERANCE:
        return handle

    overlay = ql.ZeroSpreadedTermStructure(
        handle,
        ql.QuoteHandle(ql.SimpleQuote(spread_value)),
        ql.Continuous,
        ql.NoFrequency,
    )
    overlay.enableExtrapolation()
    return ql.YieldTermStructureHandle(overlay)


def _coerce_curve_handle(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure,
) -> ql.YieldTermStructureHandle:
    if isinstance(curve, ql.YieldTermStructureHandle):
        return curve
    if isinstance(curve, ql.YieldTermStructure):
        return ql.YieldTermStructureHandle(curve)
    raise TypeError(
        "curve must be a QuantLib YieldTermStructureHandle or YieldTermStructure."
    )


def _coerce_z_spread_decimal(value: NumericSpread) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError("z_spread_decimal must be a finite decimal number or None.")
    try:
        spread_value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("z_spread_decimal must be finite.") from exc
    if not math.isfinite(spread_value):
        raise ValueError("z_spread_decimal must be finite.")
    return spread_value


__all__ = ["apply_z_spread_to_curve"]
