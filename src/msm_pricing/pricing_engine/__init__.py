"""QuantLib-backed pricing engine helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "IndexSpec": ".indices",
    "add_historical_fixings": ".indices",
    "build_zero_curve": ".indices",
    "build_zero_curve_with_effective_date": ".indices",
    "clear_index_cache": ".indices",
    "clear_index_spec_cache": ".indices",
    "compare_bond_to_market_quote": ".bond_analytics",
    "compute_coupon_schedule_force_match": ".coupon_schedules",
    "get_index": ".indices",
    "get_index_spec": ".indices",
    "index_by_name": ".indices",
    "register_index_spec": ".indices",
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
    "IndexSpec",
    "add_historical_fixings",
    "build_zero_curve",
    "build_zero_curve_with_effective_date",
    "clear_index_cache",
    "clear_index_spec_cache",
    "compare_bond_to_market_quote",
    "compute_coupon_schedule_force_match",
    "get_index",
    "get_index_spec",
    "index_by_name",
    "register_index_spec",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "select_curve",
]
