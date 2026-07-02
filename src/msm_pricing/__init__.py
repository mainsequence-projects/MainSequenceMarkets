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
    "ZeroCouponBond",
]

__all__ = [
    *_INSTRUMENT_EXPORTS,
    "PRICING_CONCEPT_DISCOUNT_CURVES",
    "PRICING_CONCEPT_EQUITY_VOL_CURVES",
    "PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS",
    "PRICING_MARKET_DATA_SET_DEFAULT",
    "PRICING_MARKET_DATA_SET_EOD",
    "PRICING_MARKET_DATA_SET_LIVE",
    "PRICING_MARKET_DATA_SET_RISK_MANAGER",
    "IndexCurveRequirement",
    "PricingMarketDataConfiguration",
    "PricingValuationContext",
    "PricingValuationContextSpec",
    "PricingValuationInstrumentKey",
    "PreparedInstrument",
    "ValuationLine",
    "ValuationPosition",
    "build_valuation_position",
    "price_scenario",
]

_ATTR_TO_MODULE = {name: ".instruments" for name in _INSTRUMENT_EXPORTS}
_ATTR_TO_MODULE["IndexCurveRequirement"] = ".valuation"
_ATTR_TO_MODULE["PricingMarketDataConfiguration"] = ".config"
_ATTR_TO_MODULE["PricingValuationContext"] = ".valuation"
_ATTR_TO_MODULE["PricingValuationContextSpec"] = ".valuation"
_ATTR_TO_MODULE["PricingValuationInstrumentKey"] = ".valuation"
_ATTR_TO_MODULE["PreparedInstrument"] = ".valuation"
_ATTR_TO_MODULE["ValuationLine"] = ".valuation"
_ATTR_TO_MODULE["ValuationPosition"] = ".valuation"
_ATTR_TO_MODULE["build_valuation_position"] = ".valuation"
_ATTR_TO_MODULE["price_scenario"] = ".valuation"
for _name in (
    "PRICING_CONCEPT_DISCOUNT_CURVES",
    "PRICING_CONCEPT_EQUITY_VOL_CURVES",
    "PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS",
    "PRICING_MARKET_DATA_SET_DEFAULT",
    "PRICING_MARKET_DATA_SET_EOD",
    "PRICING_MARKET_DATA_SET_LIVE",
    "PRICING_MARKET_DATA_SET_RISK_MANAGER",
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
