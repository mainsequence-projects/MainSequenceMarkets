"""Curve reconstruction primitives for QuantLib-backed pricing."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "CurveObservationExportConfig": ".observations",
    "CurveObservationNode": ".observations",
    "CurveReconstructionConfig": ".reconstruction",
    "OIS_HELPER_TYPES": ".helper_key_nodes",
    "OISRateHelperKeyNode": ".helper_key_nodes",
    "OISRateHelperSpec": ".helpers",
    "OVERNIGHT_DEPOSIT_HELPER_TYPE": ".helper_key_nodes",
    "OvernightDepositHelperKeyNode": ".helper_key_nodes",
    "OvernightDepositHelperSpec": ".helpers",
    "OvernightIndexResolver": ".helper_key_nodes",
    "RATE_HELPER_BUILDER_TYPES": ".adapters",
    "RATE_QUOTE_TYPES": ".quote_units",
    "RateHelperKeyNode": ".helper_key_nodes",
    "RateHelperSpec": ".helpers",
    "SUPPORTED_BOOTSTRAP_METHODS": ".reconstruction",
    "SUPPORTED_RATE_HELPER_TYPES": ".helper_key_nodes",
    "build_ois_rate_helper": ".helpers",
    "build_overnight_deposit_helper": ".helpers",
    "build_curve_from_helper_key_nodes": ".reconstruction",
    "build_rate_helper": ".helpers",
    "build_rate_helper_vector": ".helpers",
    "build_rate_helpers": ".helpers",
    "curve_observation_value": ".observations",
    "export_curve_observation_nodes": ".observations",
    "helper_specs_from_key_nodes": ".helper_key_nodes",
    "is_rate_helper_curve_build": ".adapters",
    "key_node_decimal_rate": ".quote_units",
    "key_nodes_contain_rate_helpers": ".helper_key_nodes",
    "normalize_helper_type": ".helper_key_nodes",
    "normalize_rate_value": ".quote_units",
    "parse_rate_helper_key_node": ".helper_key_nodes",
    "ql_period_from_tenor": ".helpers",
    "reconstruct_curve_from_curve_building_details": ".adapters",
    "reconstruct_curve_handle": ".reconstruction",
    "reconstruct_curve_handle_from_helper_specs": ".reconstruction",
    "reconstruct_curve_handle_from_key_nodes": ".reconstruction",
}


def __getattr__(name: str) -> Any:
    """Lazily load curve reconstruction exports."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return importable curve reconstruction names for interactive discovery."""

    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORTS)
