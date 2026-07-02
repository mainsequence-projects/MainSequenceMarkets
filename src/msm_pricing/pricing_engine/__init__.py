"""QuantLib-backed pricing engine helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "apply_z_spread_to_curve": ".curve_overlays",
    "compare_bond_to_market_quote": ".bond_analytics",
    "compute_coupon_schedule_force_match": ".coupon_schedules",
    "add_historical_fixings": ".resolvers",
    "build_curve_from_curve_row": ".resolvers",
    "CurveSelectionContext": ".resolvers",
    "normalize_curve_quote_side": ".resolvers",
    "resolve_curve_building_details": ".resolvers",
    "resolve_curve_for_index_binding": ".resolvers",
    "resolve_index_convention": ".resolvers",
    "resolve_pricing_curve": ".resolvers",
    "resolve_quantlib_index": ".resolvers",
    "select_curve": ".resolvers",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "add_historical_fixings",
    "apply_z_spread_to_curve",
    "build_curve_from_curve_row",
    "compare_bond_to_market_quote",
    "compute_coupon_schedule_force_match",
    "CurveSelectionContext",
    "normalize_curve_quote_side",
    "resolve_curve_building_details",
    "resolve_curve_for_index_binding",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "select_curve",
]
