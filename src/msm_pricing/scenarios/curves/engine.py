"""Curve-scenario pricing built on prepared valuation contexts.

The engine creates transient runtime curve handles from copied key-node
provenance, then delegates base/scenario line pricing to
``msm_pricing.valuation.price_scenario(...)``. It does not mutate submitted
instruments, prepared valuation contexts, persisted curve observations, or
connector-owned source data.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import QuantLib as ql

from msm_pricing.api.curve_building_details import CurveBuildingDetails
from msm_pricing.api.curves import Curve
from msm_pricing.instruments.base_instrument import InstrumentModel
from msm_pricing.pricing_engine.curves import OvernightIndexResolver, is_rate_helper_curve_build
from msm_pricing.pricing_engine.curve_overlays import apply_z_spread_to_curve
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation
from msm_pricing.scenarios.curves.key_node_bumps import (
    bump_key_nodes,
    key_nodes_to_curve_observation_nodes,
    runtime_observation_building_details,
)
from msm_pricing.scenarios.curves.models import (
    CurveBumpSpec,
    CurveScenario,
    CurveScenarioDiagnostic,
    CurveScenarioResult,
    LineCurveResolutionInput,
    ResolvedLineCurve,
)
from msm_pricing.valuation import (
    PricingValuationContext,
    PricingValuationContextSpec,
    ValuationPosition,
    _instrument_index_curve_requirements,
    _instrument_keys,
    price_scenario,
)

_FLOATING_ROLE_ATTRIBUTES = (
    ("floating_rate_index_uid", "projection"),
    ("float_leg_index_uid", "projection"),
)
_BENCHMARK_ROLE_ATTRIBUTES = (("benchmark_rate_index_uid", "z_spread_base"),)


def build_scenario_curve_handle(
    *,
    curve: Curve,
    building_details: CurveBuildingDetails,
    observation: Mapping[str, Any],
    bump_spec: CurveBumpSpec,
    effective_curve_date: object,
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
) -> object:
    """Build one runtime curve handle from copied, bumped source key nodes.

    ``bump_spec`` is expressed in basis points. Source key-node rates are
    bumped on copied dictionaries, converted into runtime observation ``nodes``
    using ``CurveBuildingDetails`` output convention/unit, and passed to the
    existing resolver ``build_curve_from_curve_observation(...)``. The returned
    object is a QuantLib runtime handle and is not persisted.
    """

    key_nodes = _key_node_sequence(observation, curve_identifier=curve.unique_identifier)
    bumped = bump_key_nodes(
        key_nodes,
        bump_spec,
        effective_curve_date=effective_curve_date,
    )
    if is_rate_helper_curve_build(building_details):
        scenario_observation = dict(observation)
        scenario_observation.update(
            {
                "curve_identifier": curve.unique_identifier,
                "time_index": effective_curve_date,
                "key_nodes": bumped,
            }
        )
        return build_curve_from_curve_observation(
            curve=curve,
            building_details=building_details,
            observation=scenario_observation,
            effective_curve_date=effective_curve_date,
            overnight_index=overnight_index,
            overnight_index_resolver=overnight_index_resolver,
        )

    runtime_details = runtime_observation_building_details(building_details)
    nodes = key_nodes_to_curve_observation_nodes(
        bumped,
        building_details=runtime_details,
        effective_curve_date=effective_curve_date,
    )
    scenario_observation = dict(observation)
    scenario_observation.update(
        {
            "curve_identifier": curve.unique_identifier,
            "time_index": effective_curve_date,
            "nodes": nodes,
            "key_nodes": bumped,
        }
    )
    return build_curve_from_curve_observation(
        curve=curve,
        building_details=runtime_details,
        observation=scenario_observation,
        effective_curve_date=effective_curve_date,
    )


def resolve_line_curve_resolutions(
    position: ValuationPosition,
    context: PricingValuationContext,
) -> tuple[ResolvedLineCurve, ...]:
    """Resolve curve rows and base handles for every curve-using position line.

    Resolution uses the already prepared context caches. Each returned row is
    keyed by line index plus market-data-set role/selector and references
    ``Curve.unique_identifier`` for scenario lookup.
    """

    context.validate_position_compatibility(position)
    resolutions: list[ResolvedLineCurve] = []
    for line_index, line in enumerate(position.lines):
        observed_z_spread_decimal = _observed_z_spread_decimal(line.metadata_json)
        seen_binding_keys: set[str] = set()
        for index_uid, role_key in _instrument_curve_requirements(line.instrument):
            binding = context.get_index_curve_binding(role_key=role_key, index_uid=index_uid)
            binding_key = str(getattr(binding, "binding_key", ""))
            if binding_key in seen_binding_keys:
                continue
            seen_binding_keys.add(binding_key)
            curve = context.get_curve(binding.curve_uid)
            resolutions.append(
                ResolvedLineCurve(
                    line_index=line_index,
                    role_key=str(binding.role_key),
                    selector_type=str(binding.selector_type),
                    selector_key=str(binding.selector_key),
                    quote_side=binding.quote_side,
                    curve_uid=uuid.UUID(str(binding.curve_uid)),
                    curve_identifier=str(curve.unique_identifier),
                    base_handle=context.get_curve_handle(binding.curve_uid),
                    observed_z_spread_decimal=observed_z_spread_decimal,
                )
            )
    return tuple(resolutions)


def price_curve_scenario(
    position: ValuationPosition,
    scenario: CurveScenario,
    *,
    context: PricingValuationContext | None = None,
    curve_quote_side: str | None = None,
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    strict: bool = True,
) -> CurveScenarioResult:
    """Price a valuation position under a curve scenario.

    The helper prepares a ``PricingValuationContext`` at most once when no
    context is supplied. It resolves curve handles from that context, builds
    non-empty scenario handles from copied key-node provenance, applies
    line-local z-spread overlays to runtime handles only, and delegates pricing
    to ``price_scenario(...)``. ``strict=True`` raises before pricing when
    required curve data is missing. ``strict=False`` collects structured
    diagnostics in the result. Helper-reconstructed OIS curves can supply an
    explicit ``overnight_index`` or ``overnight_index_resolver`` for scenario
    handle construction.
    """

    diagnostics: list[CurveScenarioDiagnostic] = []
    if context is None:
        context = PricingValuationContext.prepare_for_position(
            position,
            curve_quote_side=curve_quote_side,
        )
    else:
        context.validate_position_compatibility(position)

    resolutions = _collect_or_raise(
        lambda: resolve_line_curve_resolutions(position, context),
        diagnostics=diagnostics,
        strict=strict,
        stage="curve_resolution",
    )
    scenario_handles = _build_scenario_handles_by_identifier(
        scenario=scenario,
        context=context,
        resolutions=resolutions,
        overnight_index=overnight_index,
        overnight_index_resolver=overnight_index_resolver,
        diagnostics=diagnostics,
        strict=strict,
    )
    resolutions = tuple(
        replace(
            resolution,
            scenario_handle=scenario_handles.get(
                resolution.curve_identifier,
                resolution.base_handle,
            ),
        )
        for resolution in resolutions
    )
    _preflight_shocks_have_resolutions(
        scenario=scenario,
        resolutions=resolutions,
        diagnostics=diagnostics,
        strict=strict,
    )
    base_handles_by_line, scenario_handles_by_line = _line_curve_handle_maps(
        position=position,
        scenario=scenario,
        resolutions=resolutions,
        diagnostics=diagnostics,
        strict=strict,
    )
    payload = price_scenario(
        position=position,
        context=context,
        line_curve_handles=base_handles_by_line,
        scenario_curve_handles=scenario_handles_by_line,
    )
    return CurveScenarioResult.from_price_scenario_payload(
        scenario_name=scenario.name,
        payload=payload,
        curve_shocks=_curve_shock_rows(scenario=scenario, resolutions=resolutions),
        errors=tuple(diagnostics),
        line_curve_resolutions=resolutions,
        base_curve_handles_by_line=base_handles_by_line,
        scenario_curve_handles_by_line=scenario_handles_by_line,
    )


def price_resolved_curve_scenario(
    position: ValuationPosition,
    scenario: CurveScenario,
    *,
    line_curve_resolutions: LineCurveResolutionInput,
    context: PricingValuationContext | None = None,
    curve_quote_side: str | None = None,
    strict: bool = True,
) -> CurveScenarioResult:
    """Price a curve scenario from caller-supplied line curve resolutions.

    Use this entry point when an application or connector has already resolved
    each valuation line to explicit base and scenario runtime curve handles.
    ``line_curve_resolutions`` accepts either a flat sequence of
    ``LineCurveResolution`` records or a mapping keyed by ``line_index``. Each
    non-empty selected shock must have a ``scenario_handle``. Empty shocks reuse
    the selected base handle.

    Pricing is still delegated to ``msm_pricing.valuation.price_scenario(...)``.
    This helper does not resolve market-data-set curve bindings, load curve
    rows, read curve observations, rebuild handles from key nodes, or mutate
    submitted instruments. If ``context`` is omitted, a minimal context is
    created for instrument preparation only; callers whose instruments need
    cached index conventions or fixings should pass a prepared context.
    """

    diagnostics: list[CurveScenarioDiagnostic] = []
    context = _resolved_curve_scenario_context(
        position=position,
        context=context,
        curve_quote_side=curve_quote_side,
    )
    resolutions = _normalize_line_curve_resolutions(line_curve_resolutions)
    _validate_resolution_line_indices(position=position, resolutions=resolutions)
    resolutions = _with_position_z_spread_defaults(position=position, resolutions=resolutions)
    _preflight_shocks_have_resolutions(
        scenario=scenario,
        resolutions=resolutions,
        diagnostics=diagnostics,
        strict=strict,
    )
    base_handles_by_line, scenario_handles_by_line = _line_curve_handle_maps_from_resolutions(
        position=position,
        scenario=scenario,
        resolutions=resolutions,
        diagnostics=diagnostics,
        strict=strict,
    )
    payload = price_scenario(
        position=position,
        context=context,
        line_curve_handles=base_handles_by_line,
        scenario_curve_handles=scenario_handles_by_line,
    )
    return CurveScenarioResult.from_price_scenario_payload(
        scenario_name=scenario.name,
        payload=payload,
        curve_shocks=_curve_shock_rows(scenario=scenario, resolutions=resolutions),
        errors=tuple(diagnostics),
        line_curve_resolutions=resolutions,
        base_curve_handles_by_line=base_handles_by_line,
        scenario_curve_handles_by_line=scenario_handles_by_line,
    )


def _build_scenario_handles_by_identifier(
    *,
    scenario: CurveScenario,
    context: PricingValuationContext,
    resolutions: Sequence[ResolvedLineCurve],
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> dict[str, object]:
    handles: dict[str, object] = {}
    seen_curve_uids: set[uuid.UUID] = set()
    for resolution in resolutions:
        if resolution.curve_uid in seen_curve_uids:
            continue
        seen_curve_uids.add(resolution.curve_uid)
        shock = scenario.shock_for(resolution.curve_identifier)
        if shock.is_empty():
            handles[resolution.curve_identifier] = resolution.base_handle
            continue
        handle = _collect_or_raise(
            lambda resolution=resolution, shock=shock: build_scenario_curve_handle(
                curve=context.get_curve(resolution.curve_uid),
                building_details=context.get_curve_building_details(resolution.curve_uid),
                observation=_observation_mapping(
                    context.get_curve_observation(resolution.curve_uid),
                    curve_identifier=resolution.curve_identifier,
                ),
                bump_spec=shock,
                effective_curve_date=_effective_curve_date(context, resolution),
                overnight_index=overnight_index,
                overnight_index_resolver=overnight_index_resolver,
            ),
            diagnostics=diagnostics,
            strict=strict,
            stage="scenario_curve_build",
            curve_identifier=resolution.curve_identifier,
            role_key=resolution.role_key,
            line_index=resolution.line_index,
        )
        if handle is not None:
            handles[resolution.curve_identifier] = handle
    return handles


def _preflight_shocks_have_resolutions(
    *,
    scenario: CurveScenario,
    resolutions: Sequence[ResolvedLineCurve],
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> None:
    resolved_identifiers = {resolution.curve_identifier for resolution in resolutions}
    for curve_identifier, shock in scenario.shocks_by_curve_identifier.items():
        if shock.is_empty() or curve_identifier in resolved_identifiers:
            continue
        _record_or_raise(
            CurveScenarioDiagnostic(
                stage="preflight",
                curve_identifier=curve_identifier,
                message=(
                    "CurveScenario contains a non-empty shock for a curve identifier "
                    "that was not resolved by the valuation position."
                ),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )
    if not resolved_identifiers and not scenario.default_shock.is_empty():
        _record_or_raise(
            CurveScenarioDiagnostic(
                stage="preflight",
                message=(
                    "CurveScenario.default_shock is non-empty but the valuation "
                    "position resolved no curves."
                ),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )


def _line_curve_handle_maps(
    *,
    position: ValuationPosition,
    scenario: CurveScenario,
    resolutions: Sequence[ResolvedLineCurve],
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> tuple[dict[int, object], dict[int, object]]:
    return _line_curve_handle_maps_from_resolutions(
        position=position,
        scenario=scenario,
        resolutions=resolutions,
        diagnostics=diagnostics,
        strict=strict,
    )


def _line_curve_handle_maps_from_resolutions(
    *,
    position: ValuationPosition,
    scenario: CurveScenario,
    resolutions: Sequence[ResolvedLineCurve],
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> tuple[dict[int, object], dict[int, object]]:
    by_line: dict[int, list[ResolvedLineCurve]] = {}
    for resolution in resolutions:
        by_line.setdefault(resolution.line_index, []).append(resolution)

    base_handles: dict[int, object] = {}
    scenario_handles_by_line: dict[int, object] = {}
    for line_index, line in enumerate(position.lines):
        candidates = _dedupe_line_resolutions(by_line.get(line_index, ()))
        if not candidates:
            continue
        selected = _preferred_resolution(line.instrument, candidates)
        _validate_unselected_shocks(
            selected=selected,
            candidates=candidates,
            scenario=scenario,
            diagnostics=diagnostics,
            strict=strict,
        )
        base_handles[line_index] = _apply_observed_z_spread(
            selected.base_handle,
            selected.observed_z_spread_decimal,
        )
        selected_shock = scenario.shock_for(selected.curve_identifier)
        scenario_handle = (
            selected.base_handle if selected_shock.is_empty() else selected.scenario_handle
        )
        if scenario_handle is None:
            _record_or_raise(
                CurveScenarioDiagnostic(
                    stage="scenario_curve_selection",
                    line_index=line_index,
                    curve_identifier=selected.curve_identifier,
                    role_key=selected.role_key,
                    message="Non-empty curve shock has no scenario handle for selected line curve.",
                ),
                diagnostics=diagnostics,
                strict=strict,
            )
            scenario_handle = selected.base_handle
        scenario_handles_by_line[line_index] = _apply_observed_z_spread(
            scenario_handle,
            selected.observed_z_spread_decimal,
        )
    return base_handles, scenario_handles_by_line


def _normalize_line_curve_resolutions(
    line_curve_resolutions: LineCurveResolutionInput,
) -> tuple[ResolvedLineCurve, ...]:
    if isinstance(line_curve_resolutions, Mapping):
        rows: list[ResolvedLineCurve] = []
        for raw_line_index, raw_value in line_curve_resolutions.items():
            line_index = _coerce_line_index(raw_line_index)
            for resolution in _line_resolution_sequence(raw_value):
                if resolution.line_index != line_index:
                    raise ValueError(
                        "line_curve_resolutions mapping key does not match "
                        f"resolution.line_index: key={line_index}, "
                        f"resolution.line_index={resolution.line_index}."
                    )
                rows.append(resolution)
        return tuple(rows)

    if isinstance(line_curve_resolutions, str | bytes) or not isinstance(
        line_curve_resolutions,
        Sequence,
    ):
        raise TypeError(
            "line_curve_resolutions must be a sequence of LineCurveResolution "
            "records or a mapping keyed by line_index."
        )
    return tuple(_require_line_resolution(row) for row in line_curve_resolutions)


def _line_resolution_sequence(value: object) -> tuple[ResolvedLineCurve, ...]:
    if isinstance(value, ResolvedLineCurve):
        return (value,)
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(
            "line_curve_resolutions mapping values must be LineCurveResolution "
            "records or sequences of them."
        )
    return tuple(_require_line_resolution(row) for row in value)


def _require_line_resolution(value: object) -> ResolvedLineCurve:
    if not isinstance(value, ResolvedLineCurve):
        raise TypeError(
            "line_curve_resolutions must contain LineCurveResolution records, "
            f"not {type(value).__name__}."
        )
    return value


def _coerce_line_index(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("line_curve_resolutions mapping keys must be integer line indexes.")
    return value


def _validate_resolution_line_indices(
    *,
    position: ValuationPosition,
    resolutions: Sequence[ResolvedLineCurve],
) -> None:
    line_count = len(position.lines)
    for resolution in resolutions:
        if resolution.line_index < 0 or resolution.line_index >= line_count:
            raise ValueError(
                "LineCurveResolution.line_index is outside the valuation position: "
                f"{resolution.line_index} for {line_count} lines."
            )


def _with_position_z_spread_defaults(
    *,
    position: ValuationPosition,
    resolutions: Sequence[ResolvedLineCurve],
) -> tuple[ResolvedLineCurve, ...]:
    out: list[ResolvedLineCurve] = []
    observed_by_line: dict[int, float | None] = {}
    for resolution in resolutions:
        if resolution.observed_z_spread_decimal is not None:
            out.append(resolution)
            continue
        if resolution.line_index not in observed_by_line:
            observed_by_line[resolution.line_index] = _observed_z_spread_decimal(
                position.lines[resolution.line_index].metadata_json,
            )
        observed = observed_by_line[resolution.line_index]
        out.append(
            resolution
            if observed is None
            else replace(resolution, observed_z_spread_decimal=observed)
        )
    return tuple(out)


def _resolved_curve_scenario_context(
    *,
    position: ValuationPosition,
    context: PricingValuationContext | None,
    curve_quote_side: str | None,
) -> PricingValuationContext:
    if context is not None:
        context.validate_position_compatibility(position)
        return context

    normalized_quote_side = _normalize_curve_quote_side(curve_quote_side)
    instruments = tuple(line.instrument for line in position.lines)
    return PricingValuationContext(
        spec=PricingValuationContextSpec(
            valuation_date=_normalize_valuation_date(position.valuation_date),
            market_data_set=position.market_data_set,
            market_data_set_uid=None,
            curve_quote_side=normalized_quote_side,
            requirements=_instrument_index_curve_requirements(
                instruments,
                quote_side=normalized_quote_side,
            ),
            instruments=_instrument_keys(instruments),
        )
    )


def _normalize_curve_quote_side(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_valuation_date(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _validate_unselected_shocks(
    *,
    selected: ResolvedLineCurve,
    candidates: Sequence[ResolvedLineCurve],
    scenario: CurveScenario,
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> None:
    for candidate in candidates:
        if candidate.curve_identifier == selected.curve_identifier:
            continue
        if scenario.shock_for(candidate.curve_identifier).is_empty():
            continue
        _record_or_raise(
            CurveScenarioDiagnostic(
                stage="line_curve_selection",
                line_index=candidate.line_index,
                curve_identifier=candidate.curve_identifier,
                role_key=candidate.role_key,
                message=(
                    "A non-empty shock was resolved for a related curve that cannot "
                    "be applied through the current single reset_curve(...) override."
                ),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )


def _instrument_curve_requirements(
    instrument: InstrumentModel,
) -> tuple[tuple[uuid.UUID, str], ...]:
    requirements: list[tuple[uuid.UUID, str]] = []
    for attribute_name, role_key in (*_FLOATING_ROLE_ATTRIBUTES, *_BENCHMARK_ROLE_ATTRIBUTES):
        value = getattr(instrument, attribute_name, None)
        if value in (None, ""):
            continue
        requirements.append((_coerce_uuid(value, field_name=attribute_name), role_key))
    return tuple(requirements)


def _preferred_resolution(
    instrument: InstrumentModel,
    candidates: Sequence[ResolvedLineCurve],
) -> ResolvedLineCurve:
    role_order = _preferred_role_order(instrument)
    for role_key in role_order:
        for candidate in candidates:
            if candidate.role_key == role_key:
                return candidate
    return candidates[0]


def _preferred_role_order(instrument: InstrumentModel) -> tuple[str, ...]:
    for attribute_name, _role_key in _FLOATING_ROLE_ATTRIBUTES:
        if getattr(instrument, attribute_name, None) not in (None, ""):
            return ("projection", "floating", "discount", "z_spread_base")
    return ("z_spread_base", "discount", "projection", "floating")


def _dedupe_line_resolutions(
    candidates: Sequence[ResolvedLineCurve],
) -> tuple[ResolvedLineCurve, ...]:
    out: list[ResolvedLineCurve] = []
    seen_identifiers: set[str] = set()
    for candidate in candidates:
        identifier = candidate.curve_identifier
        if identifier in seen_identifiers:
            continue
        seen_identifiers.add(identifier)
        out.append(candidate)
    return tuple(out)


def _curve_shock_rows(
    *,
    scenario: CurveScenario,
    resolutions: Sequence[ResolvedLineCurve],
) -> tuple[Mapping[str, object], ...]:
    rows: dict[str, dict[str, object]] = {}
    for resolution in resolutions:
        row = rows.setdefault(
            resolution.curve_identifier,
            {
                "curve_identifier": resolution.curve_identifier,
                "parallel_bp": scenario.shock_for(resolution.curve_identifier).parallel_bp,
                "keyrate_bp": dict(scenario.shock_for(resolution.curve_identifier).keyrate_bp),
                "line_count": 0,
            },
        )
        row["line_count"] = int(row["line_count"]) + 1
    return tuple(rows.values())


def _apply_observed_z_spread(handle: object, z_spread_decimal: float | None) -> object:
    if z_spread_decimal is None or abs(z_spread_decimal) < 1e-15:
        return handle
    return apply_z_spread_to_curve(handle, z_spread_decimal)


def _observed_z_spread_decimal(metadata_json: Mapping[str, Any]) -> float | None:
    for key in ("observed_z_spread_decimal", "observed_z_spread"):
        value = metadata_json.get(key)
        if value in (None, ""):
            continue
        try:
            out = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"metadata_json[{key!r}] must be a finite decimal z-spread.") from exc
        if not math.isfinite(out):
            raise ValueError(f"metadata_json[{key!r}] must be a finite decimal z-spread.")
        return out
    return None


def _effective_curve_date(
    context: PricingValuationContext,
    resolution: ResolvedLineCurve,
) -> object:
    try:
        return context.curve_observation_dates[resolution.curve_uid]
    except KeyError as exc:
        raise LookupError(
            "PricingValuationContext has no effective curve date cached for "
            f"curve_identifier={resolution.curve_identifier!r}."
        ) from exc


def _observation_mapping(
    observation: object,
    *,
    curve_identifier: str,
) -> Mapping[str, Any]:
    if isinstance(observation, Mapping):
        return observation
    model_dump = getattr(observation, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="python")
        if isinstance(payload, Mapping):
            return payload
    raise TypeError(f"Curve observation for {curve_identifier!r} must be a mapping.")


def _key_node_sequence(
    observation: Mapping[str, Any],
    *,
    curve_identifier: str,
) -> Sequence[Mapping[str, Any]]:
    key_nodes = observation.get("key_nodes")
    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        raise ValueError(
            f"Curve observation for {curve_identifier!r} must contain key_nodes "
            "as a sequence of mapping objects."
        )
    if not key_nodes:
        raise ValueError(f"Curve observation for {curve_identifier!r} has no key_nodes.")
    for node in key_nodes:
        if not isinstance(node, Mapping):
            raise ValueError(
                f"Curve observation for {curve_identifier!r} key_nodes must contain mappings."
            )
    return key_nodes


def _collect_or_raise(
    callback: Any,
    *,
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
    stage: str,
    line_index: int | None = None,
    curve_identifier: str | None = None,
    role_key: str | None = None,
) -> Any:
    try:
        return callback()
    except Exception as exc:
        _record_or_raise(
            CurveScenarioDiagnostic(
                stage=stage,
                line_index=line_index,
                curve_identifier=curve_identifier,
                role_key=role_key,
                message=str(exc),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )
        return None


def _record_or_raise(
    diagnostic: CurveScenarioDiagnostic,
    *,
    diagnostics: list[CurveScenarioDiagnostic],
    strict: bool,
) -> None:
    if strict:
        raise RuntimeError(diagnostic.message)
    diagnostics.append(diagnostic)


def _coerce_uuid(value: object, *, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID value.") from exc


__all__ = [
    "build_scenario_curve_handle",
    "price_curve_scenario",
    "price_resolved_curve_scenario",
    "resolve_line_curve_resolutions",
]
