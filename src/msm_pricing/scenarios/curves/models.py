"""Public models for transient curve-scenario pricing.

The curve-scenario package owns runtime scenario mechanics only. Persisted
curve rows, curve observations, and key-node provenance remain owned by
``msm_pricing.data_nodes.curves`` and the pricing API rows. Connector-specific
curve rebuilds, such as vendor OIS construction, stay outside core
``msm_pricing`` and should adapt into these generic models at the boundary.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

_ZERO_BP_TOLERANCE = 1e-9


@dataclass(frozen=True)
class CurveBumpSpec:
    """Parallel plus key-rate curve shock expressed in basis points.

    ``parallel_bp`` is applied to every usable source key-node rate/yield.
    ``keyrate_bp`` maps tenor labels such as ``"3M"`` or positive day counts
    to additional basis-point shocks. The object is an input model and does not
    mutate curve observations, submitted key-node dictionaries, or persisted
    curve rows. ``metadata_json`` is caller-owned scenario metadata and is not
    used by core pricing logic.
    """

    parallel_bp: float = 0.0
    keyrate_bp: Mapping[str | int, float] = field(default_factory=dict)
    metadata_json: dict[str, Any] = field(default_factory=dict)

    def keyrate_days_bp(self) -> dict[int, float]:
        """Return key-rate shocks keyed by positive days to maturity.

        Keys that are integers are interpreted as day counts. String keys must
        be tenor labels accepted by ``tenor_to_days(...)``. Values are finite
        basis-point shocks. Invalid non-empty keys or values raise
        ``ValueError`` instead of silently changing the scenario shape.
        """

        from msm_pricing.scenarios.curves.key_node_bumps import tenor_to_days

        out: dict[int, float] = {}
        for raw_key, raw_value in (self.keyrate_bp or {}).items():
            if isinstance(raw_key, bool):
                raise ValueError("keyrate_bp keys must be tenor labels or positive day counts.")
            days = raw_key if isinstance(raw_key, int) else tenor_to_days(raw_key)
            if days is None or int(days) <= 0:
                raise ValueError(
                    f"keyrate_bp keys must be tenor labels or positive day counts: {raw_key!r}."
                )
            value = _finite_float(raw_value, field_name=f"keyrate_bp[{raw_key!r}]")
            out[int(days)] = value
        return out

    def total_bp_for_days(self, days_to_maturity: int | float) -> float:
        """Return the total basis-point shock for a positive maturity day count.

        The total is ``parallel_bp`` plus a linearly interpolated key-rate
        shock. Key-rate shocks extrapolate flat before the first key node and
        after the last key node. The returned value is still in basis points.
        """

        days = _finite_float(days_to_maturity, field_name="days_to_maturity")
        if days <= 0:
            raise ValueError("days_to_maturity must be positive.")
        return _finite_float(self.parallel_bp, field_name="parallel_bp") + _interpolate_bp_by_days(
            days,
            self.keyrate_days_bp(),
        )

    def is_empty(self) -> bool:
        """Return ``True`` when the shock leaves key-node rates unchanged."""

        if abs(_finite_float(self.parallel_bp, field_name="parallel_bp")) > _ZERO_BP_TOLERANCE:
            return False
        return all(abs(value) <= _ZERO_BP_TOLERANCE for value in self.keyrate_days_bp().values())


@dataclass(frozen=True)
class CurveScenario:
    """Curve shocks keyed by ``Curve.unique_identifier``.

    The curve unique identifier is the scenario identity boundary. Do not key
    shocks by backend curve UID, index UID, market-data role, quote side, or
    provider-local names. ``default_shock`` applies to every resolved curve that
    does not have a per-curve entry.
    """

    name: str = "scenario"
    shocks_by_curve_identifier: Mapping[str, CurveBumpSpec] = field(default_factory=dict)
    default_shock: CurveBumpSpec = field(default_factory=CurveBumpSpec)

    def shock_for(self, curve_identifier: str | None) -> CurveBumpSpec:
        """Return the shock for one ``Curve.unique_identifier``.

        Missing or ``None`` identifiers receive ``default_shock``. Explicit
        entries are matched with ``str(curve_identifier)`` so callers can pass
        identifier-like objects without changing the identity rule.
        """

        if curve_identifier is not None:
            shock = self.shocks_by_curve_identifier.get(str(curve_identifier))
            if shock is not None:
                return shock
        return self.default_shock

    def is_empty(self) -> bool:
        """Return ``True`` when the default and every per-curve shock are no-ops."""

        return self.default_shock.is_empty() and all(
            shock.is_empty() for shock in self.shocks_by_curve_identifier.values()
        )


@dataclass(frozen=True)
class ResolvedLineCurve:
    """One curve role resolved for one valuation line.

    This internal resolution record is safe to expose for diagnostics. It
    describes how a line role/selector resolved to ``Curve.unique_identifier``
    and carries runtime-only base/scenario handles. Handles are typed as
    ``object`` because they are QuantLib runtime objects and must not be
    serialized or persisted.
    """

    line_index: int
    role_key: str
    selector_type: str
    selector_key: str
    quote_side: str | None
    curve_uid: uuid.UUID
    curve_identifier: str
    base_handle: object
    scenario_handle: object | None = None
    observed_z_spread_decimal: float | None = None


LineCurveResolution = ResolvedLineCurve
# Public input contract for caller-resolved curve scenario handles.
LineCurveResolutionInput: TypeAlias = (
    Sequence[LineCurveResolution]
    | Mapping[int, LineCurveResolution | Sequence[LineCurveResolution]]
)


@dataclass(frozen=True)
class CurveScenarioDiagnostic:
    """Structured diagnostic emitted by non-strict curve-scenario runs."""

    stage: str
    message: str
    severity: str = "error"
    line_index: int | None = None
    curve_identifier: str | None = None
    role_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible diagnostic row."""

        return {
            "stage": self.stage,
            "line_index": self.line_index,
            "curve_identifier": self.curve_identifier,
            "role_key": self.role_key,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class CurveScenarioResult:
    """Base/scenario valuation output for one curve scenario.

    Base and scenario market values are copied from delegated
    ``price_scenario(...)`` output. ``line_impacts`` contains delegated per-line
    rows. ``curve_shocks`` summarizes resolved curve identities and basis-point
    shocks. ``errors`` contains structured diagnostics from explicit diagnostic
    mode. ``raw_price_scenario_result`` preserves the original delegated payload
    for callers that need fields not promoted onto this result model.
    """

    scenario_name: str
    base_market_value: float | None
    scenario_market_value: float | None
    market_value_delta: float | None
    line_impacts: tuple[Mapping[str, object], ...]
    curve_shocks: tuple[Mapping[str, object], ...]
    errors: tuple[CurveScenarioDiagnostic, ...]
    raw_price_scenario_result: Mapping[str, object]
    line_curve_resolutions: tuple[ResolvedLineCurve, ...] = ()

    @classmethod
    def from_price_scenario_payload(
        cls,
        *,
        scenario_name: str,
        payload: Mapping[str, object],
        curve_shocks: tuple[Mapping[str, object], ...],
        errors: tuple[CurveScenarioDiagnostic, ...] = (),
        line_curve_resolutions: tuple[ResolvedLineCurve, ...] = (),
    ) -> CurveScenarioResult:
        """Build a result model from delegated ``price_scenario(...)`` output."""

        return cls(
            scenario_name=scenario_name,
            base_market_value=_optional_float(payload.get("base_market_value")),
            scenario_market_value=_optional_float(payload.get("scenario_market_value")),
            market_value_delta=_optional_float(payload.get("market_value_delta")),
            line_impacts=_tuple_of_mappings(payload.get("lines")),
            curve_shocks=curve_shocks,
            errors=errors,
            raw_price_scenario_result=dict(payload),
            line_curve_resolutions=line_curve_resolutions,
        )


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be a finite number.")
    return out


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name="scenario result value")


def _tuple_of_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise TypeError("price_scenario(...) lines payload must be a list or tuple.")
    rows: list[Mapping[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("price_scenario(...) line rows must be mappings.")
        rows.append(dict(row))
    return tuple(rows)


def _interpolate_bp_by_days(days: float, points: Mapping[int, float]) -> float:
    if not points:
        return 0.0
    keys = sorted((int(key), float(value)) for key, value in points.items())
    if days <= keys[0][0]:
        return keys[0][1]
    if days >= keys[-1][0]:
        return keys[-1][1]
    for (left_days, left_bp), (right_days, right_bp) in zip(keys, keys[1:], strict=False):
        if left_days <= days <= right_days:
            weight = (days - left_days) / (right_days - left_days)
            return left_bp + weight * (right_bp - left_bp)
    return 0.0


__all__ = [
    "CurveBumpSpec",
    "CurveScenario",
    "CurveScenarioDiagnostic",
    "CurveScenarioResult",
    "LineCurveResolution",
    "LineCurveResolutionInput",
    "ResolvedLineCurve",
]
