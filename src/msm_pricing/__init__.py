from __future__ import annotations

from importlib import import_module

_INSTRUMENT_EXPORTS = [
    "AmortizingFixedRateBond",
    "AmortizingFloatingRateBond",
    "CallableFixedRateBond",
    "FixedRateBond",
    "FloatingRateBond",
    "Instrument",
    "InterestRateSwap",
    "Position",
    "PositionLine",
    "ZeroCouponBond",
]

__all__ = [
    *_INSTRUMENT_EXPORTS,
    "PRICING_CONCEPT_DISCOUNT_CURVES",
    "PRICING_CONCEPT_EQUITY_VOL_CURVES",
    "PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS",
    "PRICING_CONTEXT_DEFAULT",
    "PRICING_CONTEXT_EOD",
    "PRICING_CONTEXT_LIVE",
    "PRICING_CONTEXT_RISK_MANAGER",
    "PricingMarketDataConfiguration",
]

_ATTR_TO_MODULE = {name: ".instruments" for name in _INSTRUMENT_EXPORTS}
_ATTR_TO_MODULE["PricingMarketDataConfiguration"] = ".config"
for _name in (
    "PRICING_CONCEPT_DISCOUNT_CURVES",
    "PRICING_CONCEPT_EQUITY_VOL_CURVES",
    "PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS",
    "PRICING_CONTEXT_DEFAULT",
    "PRICING_CONTEXT_EOD",
    "PRICING_CONTEXT_LIVE",
    "PRICING_CONTEXT_RISK_MANAGER",
):
    _ATTR_TO_MODULE[_name] = ".settings"


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
