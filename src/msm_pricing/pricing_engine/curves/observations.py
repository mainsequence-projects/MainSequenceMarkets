"""Observation-node export helpers for QuantLib curve handles."""

from __future__ import annotations

import datetime as dt
import contextlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import QuantLib as ql
from pydantic import BaseModel, ConfigDict, Field

from msm_pricing.instruments.json_codec import daycount_from_json
from msm_pricing.utils import to_py_date, to_ql_date


class CurveObservationNode(BaseModel):
    """Serializable curve observation point exported from a QuantLib curve."""

    model_config = ConfigDict(extra="forbid")

    days_to_maturity: int = Field(ge=0)
    maturity_date: dt.date
    zero: float | None = None
    discount_factor: float | None = None

    def to_curve_node(self) -> dict[str, int | float | str]:
        """Return a resolver-compatible curve node dictionary."""

        payload: dict[str, int | float | str] = {
            "days_to_maturity": self.days_to_maturity,
            "maturity_date": self.maturity_date.isoformat(),
        }
        if self.zero is not None:
            payload["zero"] = self.zero
        if self.discount_factor is not None:
            payload["discount_factor"] = self.discount_factor
        return payload


class CurveObservationExportConfig(BaseModel):
    """Configuration for exporting observations from a QuantLib curve."""

    model_config = ConfigDict(extra="forbid")

    quote_convention: Literal["zero_rate", "discount_factor"] = "zero_rate"
    rate_unit: Literal["decimal", "percent"] = "decimal"
    day_counter_code: str = "Actual360"
    compounding: Literal["simple", "continuous", "compounded"] = "simple"
    compounding_frequency: Literal[
        "annual",
        "semiannual",
        "quarterly",
        "monthly",
        "daily",
        "no_frequency",
    ] = "no_frequency"

    @classmethod
    def from_curve_building_details(
        cls,
        building_details: object,
    ) -> CurveObservationExportConfig:
        """Build export config from persisted curve build details.

        Helper-based curves may use source/input placeholders such as
        ``quote_convention="helper_quote"``. In that case the persisted
        ``builder_payload`` must provide explicit runtime/output keys such as
        ``output_quote_convention`` and ``output_rate_unit``.
        """

        compounding, frequency = _export_compounding_and_frequency(building_details)
        return cls(
            quote_convention=_export_quote_convention(building_details),
            rate_unit=_export_rate_unit(building_details),
            day_counter_code=str(getattr(building_details, "day_counter_code")),
            compounding=compounding,
            compounding_frequency=frequency,
        )


def export_curve_observation_nodes(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure,
    *,
    valuation_date: dt.date | dt.datetime | ql.Date | None = None,
    node_days: Sequence[int] | None = None,
    include_pillar_dates: bool = True,
    config: CurveObservationExportConfig | Mapping[str, Any] | None = None,
) -> list[dict[str, int | float | str]]:
    """Export resolver-compatible observation nodes from a QuantLib curve.

    Pillar dates are included when the submitted object exposes QuantLib's
    ``dates()`` method. Handles do not expose those dates in all bindings, so
    callers that submit a handle should pass explicit ``node_days`` when they
    need a deterministic export grid.
    """

    export_config = _export_config(config)
    term_structure = _term_structure(curve)
    base = _reference_date(term_structure, valuation_date=valuation_date)
    with _temporary_evaluation_date(base):
        ql_dates = _export_dates(
            term_structure,
            base=base,
            node_days=node_days,
            include_pillar_dates=include_pillar_dates,
        )
        nodes = [
            _export_node(
                term_structure,
                base=base,
                ql_date=ql_date,
                config=export_config,
            )
            for ql_date in ql_dates
        ]
    return [node.to_curve_node() for node in nodes]


def curve_observation_value(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure,
    *,
    maturity_date: dt.date | dt.datetime | ql.Date,
    valuation_date: dt.date | dt.datetime | ql.Date | None = None,
    config: CurveObservationExportConfig | Mapping[str, Any] | None = None,
) -> float:
    """Return one configured observation value from a QuantLib curve."""

    export_config = _export_config(config)
    term_structure = _term_structure(curve)
    ql_date = _ql_date(maturity_date)
    if valuation_date is not None:
        with _temporary_evaluation_date(_ql_date(valuation_date)):
            return _curve_observation_value(
                term_structure,
                ql_date=ql_date,
                export_config=export_config,
            )
    return _curve_observation_value(
        term_structure,
        ql_date=ql_date,
        export_config=export_config,
    )


def _curve_observation_value(
    term_structure: ql.YieldTermStructure,
    *,
    ql_date: ql.Date,
    export_config: CurveObservationExportConfig,
) -> float:
    if export_config.quote_convention == "discount_factor":
        return float(term_structure.discount(ql_date))
    day_counter = daycount_from_json(export_config.day_counter_code)
    value = float(
        term_structure.zeroRate(
            ql_date,
            day_counter,
            _compounding(export_config.compounding),
            _frequency(export_config.compounding_frequency),
        ).rate()
    )
    if export_config.rate_unit == "percent":
        return value * 100.0
    return value


def _export_node(
    curve: ql.YieldTermStructure,
    *,
    base: ql.Date,
    ql_date: ql.Date,
    config: CurveObservationExportConfig,
) -> CurveObservationNode:
    days = int(ql_date.serialNumber() - base.serialNumber())
    maturity_date = to_py_date(ql_date).date()
    if config.quote_convention == "discount_factor":
        return CurveObservationNode(
            days_to_maturity=days,
            maturity_date=maturity_date,
            discount_factor=curve_observation_value(
                curve,
                maturity_date=ql_date,
                config=config,
            ),
        )
    zero = curve_observation_value(curve, maturity_date=ql_date, config=config)
    return CurveObservationNode(days_to_maturity=days, maturity_date=maturity_date, zero=zero)


def _export_dates(
    curve: ql.YieldTermStructure,
    *,
    base: ql.Date,
    node_days: Sequence[int] | None,
    include_pillar_dates: bool,
) -> tuple[ql.Date, ...]:
    serials: set[int] = set()
    dates: list[ql.Date] = []
    if include_pillar_dates:
        maybe_dates = getattr(curve, "dates", None)
        if callable(maybe_dates):
            for ql_date in maybe_dates():
                _append_date(dates, serials, base=base, ql_date=ql_date)
    for days in node_days or ():
        if int(days) < 0:
            raise ValueError("node_days cannot contain negative maturities.")
        _append_date(dates, serials, base=base, ql_date=base + int(days))
    if not dates:
        raise ValueError(
            "No export dates were available. Pass node_days or submit a QuantLib "
            "term structure object that exposes dates()."
        )
    return tuple(sorted(dates, key=lambda item: item.serialNumber()))


def _append_date(
    dates: list[ql.Date],
    serials: set[int],
    *,
    base: ql.Date,
    ql_date: ql.Date,
) -> None:
    if ql_date.serialNumber() < base.serialNumber():
        return
    if ql_date.serialNumber() in serials:
        return
    serials.add(ql_date.serialNumber())
    dates.append(ql_date)


def _term_structure(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure,
) -> ql.YieldTermStructure:
    if isinstance(curve, ql.YieldTermStructureHandle):
        return curve.currentLink()
    return curve


def _reference_date(
    curve: ql.YieldTermStructure,
    *,
    valuation_date: dt.date | dt.datetime | ql.Date | None,
) -> ql.Date:
    if valuation_date is not None:
        if isinstance(valuation_date, ql.Date):
            return valuation_date
        if isinstance(valuation_date, dt.datetime):
            return to_ql_date(valuation_date)
        return to_ql_date(dt.datetime.combine(valuation_date, dt.time()))
    return curve.referenceDate()


def _ql_date(value: dt.date | dt.datetime | ql.Date) -> ql.Date:
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


def _export_config(
    value: CurveObservationExportConfig | Mapping[str, Any] | None,
) -> CurveObservationExportConfig:
    if value is None:
        return CurveObservationExportConfig()
    if isinstance(value, CurveObservationExportConfig):
        return value
    return CurveObservationExportConfig.model_validate(dict(value))


def _export_quote_convention(building_details: object) -> Literal["zero_rate", "discount_factor"]:
    quote_convention = _normalized_token(getattr(building_details, "quote_convention", None))
    if quote_convention in {"helper_quote", "key_node_quote"}:
        quote_convention = _first_payload_token(
            _builder_payload(building_details),
            "output_quote_convention",
            "output_quote_type",
            "runtime_quote_convention",
            "runtime_quote_type",
            "observation_quote_convention",
            "observation_quote_type",
        )
    if quote_convention in {"zero", "zero_rate"}:
        return "zero_rate"
    if quote_convention in {"discount_factor", "discount"}:
        return "discount_factor"
    raise ValueError(
        "Curve observation export requires quote_convention zero_rate or "
        f"discount_factor, got {quote_convention!r}."
    )


def _export_rate_unit(building_details: object) -> Literal["decimal", "percent"]:
    rate_unit = _normalized_token(getattr(building_details, "rate_unit", None))
    if rate_unit in {"helper_unit", "key_node_unit"}:
        rate_unit = _first_payload_token(
            _builder_payload(building_details),
            "output_rate_unit",
            "output_quote_unit",
            "runtime_rate_unit",
            "runtime_quote_unit",
            "observation_rate_unit",
            "observation_quote_unit",
        )
    if rate_unit in {"decimal", "decimals"}:
        return "decimal"
    if rate_unit in {"percent", "percentage"}:
        return "percent"
    raise ValueError(
        f"Curve observation export requires rate_unit decimal or percent, got {rate_unit!r}."
    )


def _export_compounding_and_frequency(
    building_details: object,
) -> tuple[Literal["simple", "continuous", "compounded"], str]:
    compounding = _normalized_token(getattr(building_details, "compounding", None))
    explicit_frequency = _frequency_token(
        getattr(building_details, "compounding_frequency", None),
        required=False,
    )
    if compounding in {"simple", "simple_compounding"}:
        if explicit_frequency not in {None, "no_frequency"}:
            raise ValueError(
                "compounding_frequency is not supported when compounding='simple'."
            )
        return "simple", "no_frequency"
    if compounding in {"continuous", "continuous_compounding"}:
        if explicit_frequency not in {None, "no_frequency"}:
            raise ValueError(
                "compounding_frequency is not supported when compounding='continuous'."
            )
        return "continuous", "no_frequency"

    implied_frequency: str | None = None
    if compounding in {"compounded", "compound"}:
        pass
    elif compounding in {"compounded_annual", "annual", "annually"}:
        implied_frequency = "annual"
    elif compounding in {"compounded_semiannual", "semiannual", "semi_annual"}:
        implied_frequency = "semiannual"
    elif compounding in {"compounded_quarterly", "quarterly"}:
        implied_frequency = "quarterly"
    elif compounding in {"compounded_monthly", "monthly"}:
        implied_frequency = "monthly"
    else:
        raise ValueError(
            f"Unsupported compounding={getattr(building_details, 'compounding', None)!r}. "
            "Supported values: simple, continuous, compounded, compounded_annual, "
            "compounded_semiannual, compounded_quarterly, compounded_monthly."
        )

    if explicit_frequency is not None and implied_frequency is not None:
        if explicit_frequency != implied_frequency:
            raise ValueError(
                f"compounding={getattr(building_details, 'compounding', None)!r} conflicts "
                f"with compounding_frequency="
                f"{getattr(building_details, 'compounding_frequency', None)!r}."
            )
        frequency = implied_frequency
    else:
        frequency = explicit_frequency or implied_frequency
    if frequency in {None, "no_frequency"}:
        raise ValueError(
            "compounded curve observation export requires compounding_frequency unless "
            "the compounding value encodes one, such as 'compounded_annual'."
        )
    return "compounded", frequency


def _frequency_token(value: object, *, required: bool) -> str | None:
    token = _normalized_token(value)
    if not token:
        if required:
            raise ValueError("compounding_frequency is required.")
        return None
    frequency_by_token = {
        "nofrequency": "no_frequency",
        "no_frequency": "no_frequency",
        "none": "no_frequency",
        "annual": "annual",
        "annually": "annual",
        "semiannual": "semiannual",
        "semi_annual": "semiannual",
        "quarterly": "quarterly",
        "monthly": "monthly",
        "daily": "daily",
    }
    try:
        return frequency_by_token[token]
    except KeyError as exc:
        raise ValueError(f"Unsupported compounding_frequency={value!r}.") from exc


def _builder_payload(building_details: object) -> Mapping[str, Any]:
    payload = getattr(building_details, "builder_payload", None)
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("CurveBuildingDetails.builder_payload must be a mapping.")
    return payload


def _first_payload_token(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        token = _normalized_token(payload.get(key))
        if token:
            return token
    raise ValueError(
        "Curve observation export requires explicit output/runtime convention metadata "
        f"in builder_payload; checked keys: {', '.join(keys)}."
    )


def _normalized_token(value: object) -> str:
    return str(value or "").strip().lower()


def _compounding(value: str) -> int:
    token = value.strip().lower()
    if token == "simple":
        return ql.Simple
    if token == "continuous":
        return ql.Continuous
    if token == "compounded":
        return ql.Compounded
    raise ValueError(f"Unsupported compounding={value!r}.")


def _frequency(value: str) -> int:
    token = value.strip().lower()
    if token == "no_frequency":
        return ql.NoFrequency
    if token == "annual":
        return ql.Annual
    if token == "semiannual":
        return ql.Semiannual
    if token == "quarterly":
        return ql.Quarterly
    if token == "monthly":
        return ql.Monthly
    if token == "daily":
        return ql.Daily
    raise ValueError(f"Unsupported compounding_frequency={value!r}.")


__all__ = [
    "CurveObservationExportConfig",
    "CurveObservationNode",
    "curve_observation_value",
    "export_curve_observation_nodes",
]
