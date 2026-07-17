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
    "CurveBumpSpec",
    "CurveScenario",
    "CurveScenarioResult",
    "ObservedZSpreadOverlay",
    "ScenarioRunResult",
    "ScenarioRuntimeOverrides",
    "ValuationCarryImpact",
    "ValuationCashflow",
    "ValuationLine",
    "ValuationLineAnalytics",
    "ValuationLineImpact",
    "ValuationLinePrice",
    "ValuationPosition",
    "ValuationRunResult",
    "ValuationScenario",
    "ValuationScenarioWorkflowResult",
    "ValuationWorkflowDiagnostic",
    "build_valuation_position",
    "compute_observed_z_spread_overlays",
    "price_curve_scenario",
    "price_scenario",
    "price_valuation_lines",
    "run_valuation_scenario_workflow",
]

_ATTR_TO_MODULE = {name: ".instruments" for name in _INSTRUMENT_EXPORTS}
_ATTR_TO_MODULE["IndexCurveRequirement"] = ".valuation"
_ATTR_TO_MODULE["PricingMarketDataConfiguration"] = ".config"
_ATTR_TO_MODULE["PricingValuationContext"] = ".valuation"
_ATTR_TO_MODULE["PricingValuationContextSpec"] = ".valuation"
_ATTR_TO_MODULE["PricingValuationInstrumentKey"] = ".valuation"
_ATTR_TO_MODULE["PreparedInstrument"] = ".valuation"
_ATTR_TO_MODULE["CurveBumpSpec"] = ".scenarios.curves"
_ATTR_TO_MODULE["CurveScenario"] = ".scenarios.curves"
_ATTR_TO_MODULE["CurveScenarioResult"] = ".scenarios.curves"
_ATTR_TO_MODULE["ObservedZSpreadOverlay"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ScenarioRunResult"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ScenarioRuntimeOverrides"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationCarryImpact"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationCashflow"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationLine"] = ".valuation"
_ATTR_TO_MODULE["ValuationLineAnalytics"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationLineImpact"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationLinePrice"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationPosition"] = ".valuation"
_ATTR_TO_MODULE["ValuationRunResult"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationScenario"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationScenarioWorkflowResult"] = ".scenarios.valuation"
_ATTR_TO_MODULE["ValuationWorkflowDiagnostic"] = ".scenarios.valuation"
_ATTR_TO_MODULE["build_valuation_position"] = ".valuation"
_ATTR_TO_MODULE["compute_observed_z_spread_overlays"] = ".scenarios.valuation"
_ATTR_TO_MODULE["price_curve_scenario"] = ".scenarios.curves"
_ATTR_TO_MODULE["price_scenario"] = ".valuation"
_ATTR_TO_MODULE["price_valuation_lines"] = ".scenarios.valuation"
_ATTR_TO_MODULE["run_valuation_scenario_workflow"] = ".scenarios.valuation"
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
