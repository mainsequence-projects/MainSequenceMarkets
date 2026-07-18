"""Generic valuation scenario workflow orchestration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from msm_pricing.pricing_engine.curve_overlays import apply_z_spread_to_curve
from msm_pricing.pricing_engine.curves import OvernightIndexResolver
from msm_pricing.scenarios.curves import (
    CurveScenarioRuntimeOverrides,
    prepare_curve_scenario_runtime_overrides,
)
from msm_pricing.valuation import PricingValuationContext, ValuationPosition

from .impacts import carry_impacts, line_impacts
from .line_pricing import price_valuation_lines
from .models import (
    ObservedZSpreadOverlay,
    ScenarioRunResult,
    ScenarioRuntimeOverrides,
    ValuationScenario,
    ValuationScenarioWorkflowResult,
    ValuationWorkflowDiagnostic,
    normalize_valuation_scenarios,
)


def run_valuation_scenario_workflow(
    position: ValuationPosition,
    scenarios: ValuationScenario | Sequence[ValuationScenario],
    *,
    context: PricingValuationContext | None = None,
    curve_quote_side: str | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    include_analytics: bool = True,
    include_cashflows: bool = True,
    carry_days: int | None = None,
    strict: bool = False,
) -> ValuationScenarioWorkflowResult:
    """Run base valuation plus one or more typed valuation scenarios.

    The workflow prepares or reuses one ``PricingValuationContext``, delegates
    curve runtime override construction to ``msm_pricing.scenarios.curves``,
    computes optional observed dirty-price z-spread overlays, prices the base
    and scenario runs with ``price_valuation_lines(...)``, and returns typed
    in-memory records for downstream table adapters.

    ``strict=False`` keeps line-level failures as diagnostics whenever the
    failed phase supports partial success. ``strict=True`` raises from the
    failing phase and is appropriate for workflows that must price every line.
    Submitted instruments and persisted curve observations are not mutated.
    """

    scenario_items = normalize_valuation_scenarios(scenarios)
    pricing_context = context or PricingValuationContext.prepare_for_position(
        position,
        curve_quote_side=curve_quote_side,
    )
    if context is not None:
        pricing_context.validate_position_compatibility(position)

    diagnostics: list[ValuationWorkflowDiagnostic] = []
    observed_overlays_by_line: dict[int, ObservedZSpreadOverlay] = {}
    prepared: list[tuple[ValuationScenario, ScenarioRuntimeOverrides]] = []

    for scenario in scenario_items:
        runtime_overrides = _prepare_runtime_overrides(
            position=position,
            scenario=scenario,
            context=pricing_context,
            curve_quote_side=curve_quote_side,
            overnight_index_resolver=overnight_index_resolver,
            strict=strict,
        )
        diagnostics.extend(runtime_overrides.diagnostics)
        overlays = compute_observed_z_spread_overlays(
            position,
            context=pricing_context,
            discount_curves_by_line=runtime_overrides.line_curve_handles,
            curve_resolutions=runtime_overrides.curve_resolutions,
            strict=strict,
        )
        diagnostics.extend(
            _overlay_diagnostics(
                overlays,
                scenario_name=scenario.name,
            )
        )
        for overlay in overlays:
            observed_overlays_by_line.setdefault(overlay.line_index, overlay)
        runtime_overrides = _apply_observed_z_spread_overlays(
            runtime_overrides,
            overlays,
        )
        prepared.append((scenario, runtime_overrides))

    base_runtime = _base_runtime_overrides(prepared)
    base = price_valuation_lines(
        position,
        context=pricing_context,
        curve_handles_by_line=base_runtime.line_curve_handles,
        scenario_name="base",
        include_analytics=include_analytics,
        include_cashflows=include_cashflows,
        strict=strict,
    )
    diagnostics.extend(base.diagnostics)

    scenario_results: list[ScenarioRunResult] = []
    for scenario, runtime_overrides in prepared:
        run = price_valuation_lines(
            position,
            context=pricing_context,
            curve_handles_by_line=runtime_overrides.scenario_curve_handles,
            scenario_name=scenario.name,
            include_analytics=include_analytics,
            include_cashflows=include_cashflows,
            strict=strict,
        )
        diagnostics.extend(run.diagnostics)
        scenario_results.append(
            ScenarioRunResult(
                scenario=scenario,
                run=run,
                impacts=line_impacts(base, run, scenario_name=scenario.name),
                carry_impacts=()
                if carry_days is None
                else carry_impacts(
                    base.cashflows,
                    run.cashflows,
                    valuation_date=pricing_context.valuation_date,
                    carry_days=carry_days,
                    scenario_name=scenario.name,
                ),
                runtime_overrides=runtime_overrides,
            )
        )

    return ValuationScenarioWorkflowResult(
        base=base,
        scenarios=tuple(scenario_results),
        diagnostics=tuple(diagnostics),
        runtime_resolutions=tuple(
            resolution
            for _scenario, runtime_overrides in prepared
            for resolution in runtime_overrides.curve_resolutions
        ),
        observed_z_spread_overlays=tuple(observed_overlays_by_line.values()),
    )


def compute_observed_z_spread_overlays(
    position: ValuationPosition,
    *,
    context: PricingValuationContext,
    discount_curves_by_line: Mapping[int, object] | None = None,
    curve_resolutions: Sequence[object] = (),
    strict: bool = False,
) -> tuple[ObservedZSpreadOverlay, ...]:
    """Compute non-mutating observed z-spread overlays from dirty prices.

    Lines can provide dirty-price targets through ``metadata_json`` keys
    ``observed_dirty_price`` or ``observed_dirty_ccy``. For each target, this
    helper prepares the line instrument through the supplied context, computes
    a decimal z-spread against the selected runtime discount curve, and returns
    an explicit ``ObservedZSpreadOverlay`` record.

    The helper does not write the computed spread back to line metadata. The
    caller decides whether and how to apply returned spreads to runtime curve
    handles.
    """

    overlays: list[ObservedZSpreadOverlay] = []
    curves_by_line = dict(discount_curves_by_line or {})
    identifiers_by_line = _curve_identifiers_by_line(curve_resolutions)
    for line_index, line in enumerate(position.lines):
        metadata = dict(line.metadata_json)
        try:
            target_dirty = _target_dirty_price(metadata)
        except Exception as exc:
            overlays.append(
                _overlay_or_raise(
                    ObservedZSpreadOverlay(
                        line_index=line_index,
                        target_dirty_price=None,
                        z_spread_decimal=None,
                        curve_identifier=identifiers_by_line.get(line_index),
                        status="error",
                        message=str(exc),
                        asset_uid=line.asset_uid,
                        metadata_json=metadata,
                    ),
                    strict=strict,
                )
            )
            continue
        if target_dirty is None:
            continue
        curve_handle = _discount_curve_handle(curves_by_line.get(line_index))
        curve_identifier = identifiers_by_line.get(line_index)
        if curve_handle is None:
            overlays.append(
                _overlay_or_raise(
                    ObservedZSpreadOverlay(
                        line_index=line_index,
                        target_dirty_price=target_dirty,
                        z_spread_decimal=None,
                        curve_identifier=curve_identifier,
                        status="error",
                        message="discount curve is unavailable for observed z-spread anchoring",
                        asset_uid=line.asset_uid,
                        metadata_json=metadata,
                    ),
                    strict=strict,
                )
            )
            continue
        try:
            prepared = context.prepare_instrument(line.instrument)
            z_spread = prepared.z_spread(target_dirty, discount_curve=curve_handle)
            overlays.append(
                ObservedZSpreadOverlay(
                    line_index=line_index,
                    target_dirty_price=target_dirty,
                    z_spread_decimal=_finite_float(
                        z_spread,
                        field_name="observed z-spread",
                    ),
                    curve_identifier=curve_identifier,
                    status="computed",
                    asset_uid=line.asset_uid,
                    metadata_json=metadata,
                )
            )
        except Exception as exc:
            overlays.append(
                _overlay_or_raise(
                    ObservedZSpreadOverlay(
                        line_index=line_index,
                        target_dirty_price=target_dirty,
                        z_spread_decimal=None,
                        curve_identifier=curve_identifier,
                        status="error",
                        message=str(exc),
                        asset_uid=line.asset_uid,
                        metadata_json=metadata,
                    ),
                    strict=strict,
                )
            )
    return tuple(overlays)


def _prepare_runtime_overrides(
    *,
    position: ValuationPosition,
    scenario: ValuationScenario,
    context: PricingValuationContext,
    curve_quote_side: str | None,
    overnight_index_resolver: OvernightIndexResolver | None,
    strict: bool,
) -> ScenarioRuntimeOverrides:
    if scenario.curve_scenario is None:
        return ScenarioRuntimeOverrides()

    curve_overrides = prepare_curve_scenario_runtime_overrides(
        position,
        scenario.curve_scenario,
        context=context,
        curve_quote_side=curve_quote_side,
        overnight_index_resolver=overnight_index_resolver,
        strict=strict,
    )
    return _valuation_runtime_overrides(
        curve_overrides,
        scenario_name=scenario.name,
    )


def _valuation_runtime_overrides(
    curve_overrides: CurveScenarioRuntimeOverrides,
    *,
    scenario_name: str,
) -> ScenarioRuntimeOverrides:
    return ScenarioRuntimeOverrides(
        line_curve_handles=dict(curve_overrides.base_curve_handles_by_line),
        scenario_curve_handles=dict(curve_overrides.scenario_curve_handles_by_line),
        curve_resolutions=curve_overrides.line_curve_resolutions,
        diagnostics=tuple(
            ValuationWorkflowDiagnostic.from_curve_diagnostic(
                diagnostic,
                scenario_name=scenario_name,
            )
            for diagnostic in curve_overrides.errors
        ),
    )


def _base_runtime_overrides(
    prepared: Sequence[tuple[ValuationScenario, ScenarioRuntimeOverrides]],
) -> ScenarioRuntimeOverrides:
    for _scenario, runtime_overrides in prepared:
        if runtime_overrides.line_curve_handles:
            return runtime_overrides
    return ScenarioRuntimeOverrides()


def _apply_observed_z_spread_overlays(
    runtime_overrides: ScenarioRuntimeOverrides,
    overlays: Sequence[ObservedZSpreadOverlay],
) -> ScenarioRuntimeOverrides:
    spreads_by_line = {
        overlay.line_index: overlay.z_spread_decimal
        for overlay in overlays
        if overlay.status == "computed" and overlay.z_spread_decimal is not None
    }
    if not spreads_by_line:
        return runtime_overrides

    return ScenarioRuntimeOverrides(
        line_curve_handles=_apply_spreads_to_handles(
            runtime_overrides.line_curve_handles,
            spreads_by_line,
        ),
        scenario_curve_handles=_apply_spreads_to_handles(
            runtime_overrides.scenario_curve_handles,
            spreads_by_line,
        ),
        curve_resolutions=tuple(
            replace(
                resolution,
                observed_z_spread_decimal=spreads_by_line[resolution.line_index],
            )
            if resolution.line_index in spreads_by_line
            else resolution
            for resolution in runtime_overrides.curve_resolutions
        ),
        diagnostics=runtime_overrides.diagnostics,
    )


def _apply_spreads_to_handles(
    handles_by_line: Mapping[int, object],
    spreads_by_line: Mapping[int, float],
) -> dict[int, object]:
    out: dict[int, object] = {}
    for line_index, handle in handles_by_line.items():
        spread = spreads_by_line.get(line_index)
        if spread is None:
            out[int(line_index)] = handle
            continue
        out[int(line_index)] = _apply_spread_to_discount_handle(handle, spread)
    return out


def _overlay_diagnostics(
    overlays: Sequence[ObservedZSpreadOverlay],
    *,
    scenario_name: str,
) -> tuple[ValuationWorkflowDiagnostic, ...]:
    return tuple(
        ValuationWorkflowDiagnostic(
            stage="observed_z_spread",
            message=overlay.message or "observed z-spread could not be computed",
            scenario_name=scenario_name,
            line_index=overlay.line_index,
            asset_uid=overlay.asset_uid,
            curve_identifier=overlay.curve_identifier,
            metadata_json=overlay.metadata_json,
        )
        for overlay in overlays
        if overlay.status == "error"
    )


def _curve_identifiers_by_line(curve_resolutions: Sequence[object]) -> dict[int, str]:
    identifiers: dict[int, str] = {}
    role_rank_by_line: dict[int, int] = {}
    for resolution in curve_resolutions:
        line_index = getattr(resolution, "line_index", None)
        curve_identifier = getattr(resolution, "curve_identifier", None)
        if isinstance(line_index, int) and curve_identifier is not None:
            rank = _discount_role_rank(getattr(resolution, "role_key", None))
            current_rank = role_rank_by_line.get(line_index)
            if current_rank is None or rank < current_rank:
                identifiers[line_index] = str(curve_identifier)
                role_rank_by_line[line_index] = rank
    return identifiers


def _discount_curve_handle(handle: object) -> object | None:
    if not isinstance(handle, Mapping):
        return handle
    for key in ("discount", "default", "projection", "forwarding", "floating"):
        value = handle.get(key)
        if value is not None:
            return value
    return None


def _apply_spread_to_discount_handle(handle: object, spread: float) -> object:
    if not isinstance(handle, Mapping):
        return apply_z_spread_to_curve(handle, spread)
    out = dict(handle)
    for key in ("discount", "default", "projection", "forwarding", "floating"):
        value = out.get(key)
        if value is None:
            continue
        out[key] = apply_z_spread_to_curve(value, spread)
        return out
    return out


def _discount_role_rank(role_key: object) -> int:
    role = None if role_key is None else str(role_key)
    if role == "discount":
        return 0
    if role in {"default", "projection", "forwarding", "floating"}:
        return 1
    return 2


def _target_dirty_price(metadata: Mapping[str, object]) -> float | None:
    for key in ("observed_dirty_price", "observed_dirty_ccy"):
        value = metadata.get(key)
        if value not in (None, ""):
            return _finite_float(value, field_name=key)
    return None


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be finite.")
    return out


def _overlay_or_raise(
    overlay: ObservedZSpreadOverlay,
    *,
    strict: bool,
) -> ObservedZSpreadOverlay:
    if strict:
        raise RuntimeError(overlay.message or "observed z-spread could not be computed")
    return overlay


__all__ = [
    "compute_observed_z_spread_overlays",
    "run_valuation_scenario_workflow",
]
