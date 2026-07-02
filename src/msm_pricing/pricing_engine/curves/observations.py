"""Observation-node export helpers for QuantLib curve handles."""

from __future__ import annotations

import datetime as dt
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
    config: CurveObservationExportConfig | Mapping[str, Any] | None = None,
) -> float:
    """Return one configured observation value from a QuantLib curve."""

    export_config = _export_config(config)
    term_structure = _term_structure(curve)
    ql_date = _ql_date(maturity_date)
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


def _export_config(
    value: CurveObservationExportConfig | Mapping[str, Any] | None,
) -> CurveObservationExportConfig:
    if value is None:
        return CurveObservationExportConfig()
    if isinstance(value, CurveObservationExportConfig):
        return value
    return CurveObservationExportConfig.model_validate(dict(value))


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
