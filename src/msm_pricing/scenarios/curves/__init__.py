"""Curve-keyed pricing scenarios for fixed-income valuation workflows.

The public API in this package builds transient scenario curve handles from
copied source key-node provenance and delegates valuation to the prepared
``price_scenario(...)`` path. It does not mutate persisted curve data or
import connector-specific curve builders.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "CurveBumpSpec": ".models",
    "CurveScenario": ".models",
    "CurveScenarioDiagnostic": ".models",
    "CurveScenarioResult": ".models",
    "LineCurveResolution": ".models",
    "LineCurveResolutionInput": ".models",
    "ResolvedLineCurve": ".models",
    "build_scenario_curve_handle": ".engine",
    "price_curve_scenario": ".engine",
    "price_resolved_curve_scenario": ".engine",
    "resolve_line_curve_resolutions": ".engine",
    "bump_key_node_rate": ".key_node_bumps",
    "bump_key_nodes": ".key_node_bumps",
    "bumped_raw_rate": ".key_node_bumps",
    "key_node_days_to_maturity": ".key_node_bumps",
    "key_node_decimal_rate": ".key_node_bumps",
    "key_node_maturity_date": ".key_node_bumps",
    "key_nodes_to_curve_observation_nodes": ".key_node_bumps",
    "normalize_rate_value": ".key_node_bumps",
    "rate_in_build_unit": ".key_node_bumps",
    "runtime_curve_quote_convention": ".key_node_bumps",
    "runtime_curve_rate_unit": ".key_node_bumps",
    "runtime_observation_building_details": ".key_node_bumps",
    "tenor_to_days": ".key_node_bumps",
    "to_utc_datetime": ".key_node_bumps",
}


def __getattr__(name: str) -> Any:
    """Lazily load curve-scenario exports without importing QuantLib eagerly."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return importable curve-scenario names for interactive discovery."""

    return sorted(set(globals()) | set(__all__))


__all__ = [
    "CurveBumpSpec",
    "CurveScenario",
    "CurveScenarioDiagnostic",
    "CurveScenarioResult",
    "LineCurveResolution",
    "LineCurveResolutionInput",
    "ResolvedLineCurve",
    "build_scenario_curve_handle",
    "bump_key_node_rate",
    "bump_key_nodes",
    "bumped_raw_rate",
    "key_node_days_to_maturity",
    "key_node_decimal_rate",
    "key_node_maturity_date",
    "key_nodes_to_curve_observation_nodes",
    "normalize_rate_value",
    "price_curve_scenario",
    "price_resolved_curve_scenario",
    "rate_in_build_unit",
    "resolve_line_curve_resolutions",
    "runtime_curve_quote_convention",
    "runtime_curve_rate_unit",
    "runtime_observation_building_details",
    "tenor_to_days",
    "to_utc_datetime",
]
