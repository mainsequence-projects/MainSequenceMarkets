"""Generic valuation scenario workflows built on pricing valuation contexts."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ObservedZSpreadOverlay": ".models",
    "ScenarioRunResult": ".models",
    "ScenarioRuntimeOverrides": ".models",
    "ValuationCarryImpact": ".models",
    "ValuationCashflow": ".models",
    "ValuationLineAnalytics": ".models",
    "ValuationLineImpact": ".models",
    "ValuationLinePrice": ".models",
    "ValuationRunResult": ".models",
    "ValuationScenario": ".models",
    "ValuationScenarioWorkflowResult": ".models",
    "ValuationWorkflowDiagnostic": ".models",
    "compute_observed_z_spread_overlays": ".engine",
    "carry_impacts": ".impacts",
    "line_impacts": ".impacts",
    "price_valuation_lines": ".line_pricing",
    "run_valuation_scenario_workflow": ".engine",
}


def __getattr__(name: str) -> Any:
    """Lazily load valuation scenario exports."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return importable valuation scenario names for interactive discovery."""

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
    "carry_impacts",
    "compute_observed_z_spread_overlays",
    "line_impacts",
    "price_valuation_lines",
    "run_valuation_scenario_workflow",
]
