"""QuantLib-backed pricing engine helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "compare_bond_to_market_quote": ".bond_analytics",
    "compute_coupon_schedule_force_match": ".coupon_schedules",
    "add_historical_fixings": ".resolvers",
    "build_curve_from_curve_row": ".resolvers",
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
    "build_curve_from_curve_row",
    "compare_bond_to_market_quote",
    "compute_coupon_schedule_force_match",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "select_curve",
]
