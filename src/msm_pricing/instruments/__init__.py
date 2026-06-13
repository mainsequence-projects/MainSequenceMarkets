from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "AmortizingFixedRateBond": (".bond", "AmortizingFixedRateBond"),
    "AmortizingFloatingRateBond": (".bond", "AmortizingFloatingRateBond"),
    "CallableFixedRateBond": (".bond", "CallableFixedRateBond"),
    "FixedRateBond": (".bond", "FixedRateBond"),
    "FloatingRateBond": (".bond", "FloatingRateBond"),
    "Instrument": (".base_instrument", "InstrumentModel"),
    "InterestRateSwap": (".interest_rate_swap", "InterestRateSwap"),
    "ZeroCouponBond": (".bond", "ZeroCouponBond"),
}

__all__ = [
    "AmortizingFixedRateBond",
    "AmortizingFloatingRateBond",
    "CallableFixedRateBond",
    "FixedRateBond",
    "FloatingRateBond",
    "Instrument",
    "InterestRateSwap",
    "ZeroCouponBond",
]


def __getattr__(name: str) -> Any:
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = export
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
