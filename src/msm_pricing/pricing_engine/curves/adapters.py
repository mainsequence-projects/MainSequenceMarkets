"""Adapters from persisted curve build metadata to primitive curve builders."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import QuantLib as ql

from msm_pricing.pricing_engine.curves.helper_key_nodes import OvernightIndexResolver
from msm_pricing.pricing_engine.curves.helper_resolution import RateHelperRuntimeResolver
from msm_pricing.pricing_engine.curves.reconstruction import (
    CurveReconstructionConfig,
    reconstruct_curve_handle_from_key_nodes,
)

RATE_HELPER_BUILDER_TYPES = frozenset({"rate_helper_curve", "rate_helper_bootstrap"})


def is_rate_helper_curve_build(building_details: object) -> bool:
    """Return whether build details request helper-based curve reconstruction."""

    return _token(getattr(building_details, "builder_type", None)) in RATE_HELPER_BUILDER_TYPES


def reconstruct_curve_from_curve_building_details(
    *,
    building_details: object,
    observation: Mapping[str, Any],
    effective_curve_date: dt.date | dt.datetime | ql.Date,
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    helper_runtime_resolver: RateHelperRuntimeResolver | None = None,
) -> ql.YieldTermStructureHandle:
    """Reconstruct a curve from ``CurveBuildingDetails`` and helper key nodes.

    This is the persistence adapter. It reads build-detail fields, validates
    the helper schema if declared, and delegates to primitive key-node and
    QuantLib helper builders.
    """

    helper_schema = _validate_rate_helper_payload(building_details)
    key_nodes = observation.get("key_nodes")
    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, list):
        raise ValueError("Rate-helper curve reconstruction requires observation['key_nodes'].")
    config = CurveReconstructionConfig.from_curve_building_details(building_details)
    return reconstruct_curve_handle_from_key_nodes(
        key_nodes,
        valuation_date=effective_curve_date,
        day_counter=config.day_counter(),
        bootstrap_method=config.bootstrap_method,
        extrapolation=config.extrapolation,
        helper_schema=helper_schema,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        helper_runtime_resolver=helper_runtime_resolver,
    )


def _validate_rate_helper_payload(building_details: object) -> str:
    payload = getattr(building_details, "builder_payload", None)
    if not isinstance(payload, Mapping):
        raise ValueError(
            "Rate-helper curve reconstruction requires "
            "CurveBuildingDetails.builder_payload with helper_schema='rate_helpers@v1'."
        )
    helper_schema = _token(payload.get("helper_schema") or payload.get("input_schema"))
    if helper_schema != "rate_helpers@v1":
        raise ValueError(
            "Rate-helper curve reconstruction supports helper_schema='rate_helpers@v1' only."
        )
    return helper_schema


def _token(value: object) -> str:
    return str(value or "").strip().lower()


__all__ = [
    "RATE_HELPER_BUILDER_TYPES",
    "is_rate_helper_curve_build",
    "reconstruct_curve_from_curve_building_details",
]
