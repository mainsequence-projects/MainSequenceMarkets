"""Typed models for generic valuation scenario workflows.

The valuation workflow models are in-memory contracts. They describe pricing
results, runtime overrides, diagnostics, and line impacts without prescribing
pandas/DataFrame output shapes for dashboards or APIs.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from msm_pricing.scenarios.curves import (
    CurveScenario,
    CurveScenarioDiagnostic,
    ResolvedLineCurve,
)


DiagnosticSeverity = Literal["warning", "error"]
LinePriceStatus = Literal["priced", "error"]
OptionalOperationStatus = Literal["ready", "skipped", "error"]
ObservedZSpreadStatus = Literal["computed", "skipped", "error"]


@dataclass(frozen=True)
class ValuationScenario:
    """One valuation-level scenario definition.

    The first implementation supports curve shocks directly through
    ``curve_scenario``. The model is still valuation-level so later scenario
    families can be added without moving generic workflow orchestration into
    the curve-specific namespace.
    """

    name: str
    curve_scenario: CurveScenario | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationWorkflowDiagnostic:
    """Structured diagnostic emitted by valuation workflow phases."""

    stage: str
    message: str
    severity: DiagnosticSeverity = "error"
    scenario_name: str | None = None
    line_index: int | None = None
    asset_uid: uuid.UUID | None = None
    curve_identifier: str | None = None
    role_key: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_curve_diagnostic(
        cls,
        diagnostic: CurveScenarioDiagnostic,
        *,
        scenario_name: str | None = None,
    ) -> ValuationWorkflowDiagnostic:
        """Adapt a curve-scenario diagnostic into the valuation workflow shape."""

        return cls(
            stage=diagnostic.stage,
            message=diagnostic.message,
            severity="warning" if diagnostic.severity == "warning" else "error",
            scenario_name=scenario_name,
            line_index=diagnostic.line_index,
            curve_identifier=diagnostic.curve_identifier,
            role_key=diagnostic.role_key,
        )


@dataclass(frozen=True)
class ObservedZSpreadOverlay:
    """Observed dirty-price z-spread calculation for one valuation line."""

    line_index: int
    target_dirty_price: float | None
    z_spread_decimal: float | None
    curve_identifier: str | None
    status: ObservedZSpreadStatus
    message: str | None = None
    asset_uid: uuid.UUID | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioRuntimeOverrides:
    """Runtime-only line overrides prepared for one valuation scenario."""

    line_curve_handles: Mapping[int, object] = field(default_factory=dict)
    scenario_curve_handles: Mapping[int, object] = field(default_factory=dict)
    curve_resolutions: tuple[ResolvedLineCurve, ...] = ()
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...] = ()


@dataclass(frozen=True)
class ValuationLinePrice:
    """Unit-scaled pricing result for one valuation line."""

    line_index: int
    instrument_type: str
    asset_uid: uuid.UUID | None
    units: float
    unit_price: float | None
    market_value: float | None
    status: LinePriceStatus
    error: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationLineAnalytics:
    """Raw and unit-scaled analytics for one valuation line."""

    line_index: int
    instrument_type: str
    asset_uid: uuid.UUID | None
    units: float
    raw_analytics: Mapping[str, object] = field(default_factory=dict)
    scaled_analytics: Mapping[str, float] = field(default_factory=dict)
    status: OptionalOperationStatus = "ready"
    error: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationCashflow:
    """Unit-scaled cashflow row for one valuation line and leg."""

    line_index: int
    instrument_type: str
    asset_uid: uuid.UUID | None
    units: float
    leg: str
    amount: float | None = None
    payment_date: object | None = None
    cashflow: Mapping[str, object] = field(default_factory=dict)
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationRunResult:
    """Partial-success valuation result for one base or scenario run."""

    scenario_name: str
    total_market_value: float | None
    line_prices: tuple[ValuationLinePrice, ...]
    line_analytics: tuple[ValuationLineAnalytics, ...] = ()
    cashflows: tuple[ValuationCashflow, ...] = ()
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...] = ()


@dataclass(frozen=True)
class ValuationLineImpact:
    """Base-versus-scenario impact for one valuation line."""

    line_index: int
    scenario_name: str
    instrument_type: str | None
    asset_uid: uuid.UUID | None
    units: float | None
    base_market_value: float | None
    scenario_market_value: float | None
    market_value_delta: float | None
    base_status: str | None
    scenario_status: str | None
    error: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationCarryImpact:
    """Base-versus-scenario cashflow carry impact for one valuation line."""

    line_index: int
    scenario_name: str
    base_carry: float
    scenario_carry: float
    carry_impact: float
    carry_days: int


@dataclass(frozen=True)
class ScenarioRunResult:
    """One scenario run plus impacts against the base valuation run."""

    scenario: ValuationScenario
    run: ValuationRunResult
    impacts: tuple[ValuationLineImpact, ...]
    carry_impacts: tuple[ValuationCarryImpact, ...] = ()
    runtime_overrides: ScenarioRuntimeOverrides | None = None


@dataclass(frozen=True)
class ValuationScenarioWorkflowResult:
    """Base and scenario valuation workflow result."""

    base: ValuationRunResult
    scenarios: tuple[ScenarioRunResult, ...]
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...]
    runtime_resolutions: tuple[ResolvedLineCurve, ...] = ()
    observed_z_spread_overlays: tuple[ObservedZSpreadOverlay, ...] = ()


def normalize_valuation_scenarios(
    scenarios: ValuationScenario | Sequence[ValuationScenario],
) -> tuple[ValuationScenario, ...]:
    """Return a tuple of valuation scenarios from a scalar or sequence input."""

    if isinstance(scenarios, ValuationScenario):
        return (scenarios,)
    return tuple(scenarios)


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
    "normalize_valuation_scenarios",
]
