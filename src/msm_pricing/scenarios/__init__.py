"""Scenario namespaces for pricing risk-factor workflows.

This package is intentionally domain-neutral. Concrete scenario families live
in subpackages such as :mod:`msm_pricing.scenarios.curves` so future equities,
volatility, credit, or commodity scenarios can use sibling namespaces instead
of a mixed catch-all module.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ObservedZSpreadOverlay": ".valuation",
    "ScenarioRunResult": ".valuation",
    "ScenarioRuntimeOverrides": ".valuation",
    "ValuationCarryImpact": ".valuation",
    "ValuationCashflow": ".valuation",
    "ValuationLineAnalytics": ".valuation",
    "ValuationLineImpact": ".valuation",
    "ValuationLinePrice": ".valuation",
    "ValuationRunResult": ".valuation",
    "ValuationScenario": ".valuation",
    "ValuationScenarioWorkflowResult": ".valuation",
    "ValuationWorkflowDiagnostic": ".valuation",
    "compute_observed_z_spread_overlays": ".valuation",
    "price_valuation_lines": ".valuation",
    "run_valuation_scenario_workflow": ".valuation",
}


def __getattr__(name: str) -> Any:
    """Lazily load scenario namespace exports."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return importable scenario names for interactive discovery."""

    return sorted(set(globals()) | set(__all__))


__all__ = [
    "ObservedZSpreadOverlay",
    "ScenarioRunResult",
    "ScenarioRuntimeOverrides",
    "ValuationCarryImpact",
    "ValuationCashflow",
    "ValuationLineAnalytics",
    "ValuationLineImpact",
    "ValuationLinePrice",
    "ValuationRunResult",
    "ValuationScenario",
    "ValuationScenarioWorkflowResult",
    "ValuationWorkflowDiagnostic",
    "compute_observed_z_spread_overlays",
    "price_valuation_lines",
    "run_valuation_scenario_workflow",
]
