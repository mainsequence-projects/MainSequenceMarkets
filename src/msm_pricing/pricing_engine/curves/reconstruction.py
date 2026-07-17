"""Generic QuantLib curve reconstruction from primitive rate helpers."""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import QuantLib as ql
from pydantic import BaseModel, ConfigDict

from msm_pricing.instruments.json_codec import daycount_from_json
from msm_pricing.pricing_engine.curves.helper_key_nodes import (
    OvernightIndexResolver,
    parse_rate_helper_key_nodes,
)
from msm_pricing.pricing_engine.curves.helper_resolution import RateHelperRuntimeResolver
from msm_pricing.pricing_engine.curves.helpers import (
    RateHelperSpec,
    build_rate_helper_vector,
    build_rate_helpers,
)
from msm_pricing.utils import to_ql_date

SUPPORTED_BOOTSTRAP_METHODS = frozenset({"piecewise_log_linear_discount"})


@dataclass(frozen=True, slots=True)
class CurveReconstructionResult:
    """Runtime curve reconstruction result with helper diagnostics attached."""

    term_structure: ql.YieldTermStructure
    helpers: tuple[ql.RateHelper, ...]
    helper_specs: tuple[RateHelperSpec, ...]
    context_nodes: tuple[Mapping[str, Any], ...] = ()
    helper_quote_errors: tuple[float, ...] = ()


class CurveReconstructionConfig(BaseModel):
    """Serializable adapter config for helper-based curve reconstruction."""

    model_config = ConfigDict(extra="forbid")

    bootstrap_method: Literal["piecewise_log_linear_discount"] = "piecewise_log_linear_discount"
    day_counter_code: str = "Actual360"
    extrapolation: bool = True

    @classmethod
    def from_curve_building_details(cls, building_details: object) -> CurveReconstructionConfig:
        """Build reconstruction config from persisted curve build details."""

        return cls(
            bootstrap_method=_normalize_bootstrap_method(
                _bootstrap_method_from_building_details(building_details)
            ),
            day_counter_code=str(getattr(building_details, "day_counter_code")),
            extrapolation=str(getattr(building_details, "extrapolation_policy", "")).lower()
            in {"enabled", "enable", "true", "yes", "on"},
        )

    def day_counter(self) -> ql.DayCounter:
        """Return the QuantLib day counter encoded by this config."""

        return daycount_from_json(self.day_counter_code)


def reconstruct_curve_handle(
    helpers: Sequence[ql.RateHelper] | ql.RateHelperVector,
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter,
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
) -> ql.YieldTermStructureHandle:
    """Bootstrap a QuantLib curve handle from already-built rate helpers.

    This primitive API intentionally accepts QuantLib inputs only. Persistence
    rows such as ``CurveBuildingDetails`` are adapted before calling this
    function.
    """

    term_structure = reconstruct_curve_term_structure(
        helpers,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
    )
    return ql.YieldTermStructureHandle(term_structure)


def reconstruct_curve_term_structure(
    helpers: Sequence[ql.RateHelper] | ql.RateHelperVector,
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter,
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
) -> ql.YieldTermStructure:
    """Bootstrap a QuantLib curve object from already-built rate helpers.

    Use this when callers need QuantLib methods such as ``dates()`` for
    pillar-date observation export. Use ``reconstruct_curve_handle(...)`` for
    pricing paths that only need a handle.
    """

    method = _normalize_bootstrap_method(bootstrap_method)
    helper_vector = build_rate_helper_vector(helpers)
    ql_valuation_date = _ql_valuation_date(valuation_date)
    with _temporary_evaluation_date(ql_valuation_date):
        if method == "piecewise_log_linear_discount":
            term_structure = ql.PiecewiseLogLinearDiscount(
                ql_valuation_date,
                helper_vector,
                day_counter,
            )
        else:
            raise AssertionError(f"Unhandled bootstrap_method={method!r}.")
        term_structure.recalculate()
        if extrapolation:
            term_structure.enableExtrapolation()
        maybe_freeze = getattr(term_structure, "freeze", None)
        if callable(maybe_freeze):
            maybe_freeze()
        return term_structure


def reconstruct_curve_handle_from_helper_specs(
    helper_specs: Sequence[RateHelperSpec],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter,
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
) -> ql.YieldTermStructureHandle:
    """Build rate helpers from specs and bootstrap a QuantLib curve handle."""

    result = reconstruct_curve_result_from_helper_specs(
        helper_specs,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
    )
    return ql.YieldTermStructureHandle(result.term_structure)


def reconstruct_curve_term_structure_from_helper_specs(
    helper_specs: Sequence[RateHelperSpec],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter,
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
) -> ql.YieldTermStructure:
    """Build rate helpers from specs and bootstrap a QuantLib curve object."""

    return reconstruct_curve_result_from_helper_specs(
        helper_specs,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
    ).term_structure


def reconstruct_curve_result_from_helper_specs(
    helper_specs: Sequence[RateHelperSpec],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter,
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
    context_nodes: Sequence[Mapping[str, Any]] = (),
) -> CurveReconstructionResult:
    """Build helpers, bootstrap a curve, and return helper diagnostics."""

    ql_valuation_date = _ql_valuation_date(valuation_date)
    with _temporary_evaluation_date(ql_valuation_date):
        helpers = build_rate_helpers(helper_specs)
    term_structure = reconstruct_curve_term_structure(
        helpers,
        valuation_date=ql_valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
    )
    with _temporary_evaluation_date(ql_valuation_date):
        helper_quote_errors = tuple(float(helper.quoteError()) for helper in helpers)
    return CurveReconstructionResult(
        term_structure=term_structure,
        helpers=helpers,
        helper_specs=tuple(helper_specs),
        context_nodes=tuple(context_nodes),
        helper_quote_errors=helper_quote_errors,
    )


def reconstruct_curve_handle_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter | str | Mapping[str, Any],
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
    helper_schema: str = "rate_helpers@v1",
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    helper_runtime_resolver: RateHelperRuntimeResolver | None = None,
) -> ql.YieldTermStructureHandle:
    """Build helper specs from key nodes and bootstrap a QuantLib curve handle."""

    result = reconstruct_curve_result_from_key_nodes(
        key_nodes,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
        helper_schema=helper_schema,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        helper_runtime_resolver=helper_runtime_resolver,
    )
    return ql.YieldTermStructureHandle(result.term_structure)


def reconstruct_curve_term_structure_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter | str | Mapping[str, Any],
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
    helper_schema: str = "rate_helpers@v1",
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    helper_runtime_resolver: RateHelperRuntimeResolver | None = None,
) -> ql.YieldTermStructure:
    """Build helper specs from key nodes and bootstrap a QuantLib curve object."""

    return reconstruct_curve_result_from_key_nodes(
        key_nodes,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
        helper_schema=helper_schema,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        helper_runtime_resolver=helper_runtime_resolver,
    ).term_structure


def reconstruct_curve_result_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter | str | Mapping[str, Any],
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
    helper_schema: str = "rate_helpers@v1",
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    helper_runtime_resolver: RateHelperRuntimeResolver | None = None,
) -> CurveReconstructionResult:
    """Build helper specs from key nodes and return a diagnostic reconstruction."""

    parsed = parse_rate_helper_key_nodes(
        key_nodes,
        helper_schema=helper_schema,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        helper_runtime_resolver=helper_runtime_resolver,
    )
    return reconstruct_curve_result_from_helper_specs(
        parsed.helper_specs,
        valuation_date=valuation_date,
        day_counter=_day_counter(day_counter),
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
        context_nodes=parsed.context_nodes,
    )


def build_curve_from_helper_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    valuation_date: dt.date | dt.datetime | ql.Date,
    day_counter: ql.DayCounter | str | Mapping[str, Any],
    bootstrap_method: str = "piecewise_log_linear_discount",
    extrapolation: bool = True,
    helper_schema: str = "rate_helpers@v1",
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    helper_runtime_resolver: RateHelperRuntimeResolver | None = None,
) -> ql.YieldTermStructureHandle:
    """Alias for helper-key-node reconstruction with an explicit public name."""

    return reconstruct_curve_handle_from_key_nodes(
        key_nodes,
        valuation_date=valuation_date,
        day_counter=day_counter,
        bootstrap_method=bootstrap_method,
        extrapolation=extrapolation,
        helper_schema=helper_schema,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        helper_runtime_resolver=helper_runtime_resolver,
    )


def _normalize_bootstrap_method(value: str | None) -> str:
    method = str(value or "piecewise_log_linear_discount").strip().lower()
    if method == "log_linear_discount":
        method = "piecewise_log_linear_discount"
    if method not in SUPPORTED_BOOTSTRAP_METHODS:
        raise NotImplementedError(
            f"Unsupported bootstrap_method={value!r}. Supported values: "
            f"{', '.join(sorted(SUPPORTED_BOOTSTRAP_METHODS))}."
        )
    return method


def _bootstrap_method_from_building_details(building_details: object) -> str:
    explicit = str(getattr(building_details, "bootstrap_method", "") or "").strip().lower()
    if explicit:
        return explicit
    interpolation_method = str(
        getattr(building_details, "interpolation_method", "") or ""
    ).strip().lower()
    if interpolation_method == "log_linear_discount":
        return "piecewise_log_linear_discount"
    return interpolation_method or "piecewise_log_linear_discount"


def _day_counter(value: ql.DayCounter | str | Mapping[str, Any]) -> ql.DayCounter:
    if isinstance(value, ql.DayCounter):
        return value
    return daycount_from_json(value)


def _ql_valuation_date(value: dt.date | dt.datetime | ql.Date) -> ql.Date:
    if isinstance(value, ql.Date):
        return value
    if isinstance(value, dt.datetime):
        return to_ql_date(value)
    return to_ql_date(dt.datetime.combine(value, dt.time()))


@contextlib.contextmanager
def _temporary_evaluation_date(value: ql.Date):
    settings = ql.Settings.instance()
    previous = settings.evaluationDate
    settings.evaluationDate = value
    try:
        yield
    finally:
        settings.evaluationDate = previous


__all__ = [
    "CurveReconstructionConfig",
    "CurveReconstructionResult",
    "SUPPORTED_BOOTSTRAP_METHODS",
    "build_curve_from_helper_key_nodes",
    "reconstruct_curve_handle",
    "reconstruct_curve_handle_from_helper_specs",
    "reconstruct_curve_handle_from_key_nodes",
    "reconstruct_curve_result_from_helper_specs",
    "reconstruct_curve_result_from_key_nodes",
    "reconstruct_curve_term_structure",
    "reconstruct_curve_term_structure_from_helper_specs",
    "reconstruct_curve_term_structure_from_key_nodes",
]
