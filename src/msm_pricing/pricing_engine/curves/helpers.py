"""Primitive QuantLib rate-helper builders for curve reconstruction."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import QuantLib as ql

from msm_pricing.instruments.json_codec import (
    bdc_from_json,
    calendar_from_json,
    daycount_from_json,
)

_TENOR_RE = re.compile(r"^\s*(?P<count>[1-9][0-9]*)\s*(?P<unit>[DWMY])\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OvernightDepositHelperSpec:
    """Inputs required to build a QuantLib overnight deposit helper."""

    quote: float
    tenor: str | ql.Period = "1D"
    fixing_days: int = 0
    calendar: ql.Calendar | str | Mapping[str, Any] = field(default_factory=ql.TARGET)
    convention: int | str = ql.Following
    end_of_month: bool = False
    day_counter: ql.DayCounter | str | Mapping[str, Any] = field(default_factory=ql.Actual360)


@dataclass(frozen=True, slots=True)
class OISRateHelperSpec:
    """Inputs required to build a QuantLib overnight-indexed swap helper."""

    quote: float
    tenor: str | ql.Period
    overnight_index: ql.OvernightIndex
    settlement_days: int = 0


RateHelperSpec = OvernightDepositHelperSpec | OISRateHelperSpec


def ql_period_from_tenor(tenor: str | ql.Period) -> ql.Period:
    """Parse a strict tenor label into a QuantLib ``Period``.

    Supported labels use ``D``, ``W``, ``M``, or ``Y`` suffixes, for example
    ``"1D"``, ``"4W"``, ``"13M"``, and ``"30Y"``.
    """

    if isinstance(tenor, ql.Period):
        return tenor
    match = _TENOR_RE.match(str(tenor or ""))
    if match is None:
        raise ValueError(
            f"Unsupported tenor={tenor!r}. Expected a positive integer plus D, W, M, or Y."
        )
    count = int(match.group("count"))
    unit = match.group("unit").upper()
    units = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}
    return ql.Period(count, units[unit])


def build_overnight_deposit_helper(spec: OvernightDepositHelperSpec) -> ql.RateHelper:
    """Build a QuantLib ``DepositRateHelper`` from primitive inputs."""

    return ql.DepositRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(float(spec.quote))),
        ql_period_from_tenor(spec.tenor),
        int(spec.fixing_days),
        _calendar(spec.calendar),
        _business_day_convention(spec.convention),
        bool(spec.end_of_month),
        _day_counter(spec.day_counter),
    )


def build_ois_rate_helper(spec: OISRateHelperSpec) -> ql.RateHelper:
    """Build a QuantLib ``OISRateHelper`` from primitive inputs."""

    return ql.OISRateHelper(
        int(spec.settlement_days),
        ql_period_from_tenor(spec.tenor),
        ql.QuoteHandle(ql.SimpleQuote(float(spec.quote))),
        spec.overnight_index,
    )


def build_rate_helper(spec: RateHelperSpec) -> ql.RateHelper:
    """Build a QuantLib helper for one supported primitive helper spec."""

    if isinstance(spec, OvernightDepositHelperSpec):
        return build_overnight_deposit_helper(spec)
    if isinstance(spec, OISRateHelperSpec):
        return build_ois_rate_helper(spec)
    raise TypeError(f"Unsupported rate helper spec type: {type(spec).__name__}.")


def build_rate_helpers(specs: Sequence[RateHelperSpec]) -> tuple[ql.RateHelper, ...]:
    """Build QuantLib helpers from primitive helper specs."""

    return tuple(build_rate_helper(spec) for spec in specs)


def build_rate_helper_vector(helpers: Sequence[ql.RateHelper] | ql.RateHelperVector) -> ql.RateHelperVector:
    """Collect QuantLib helpers into a ``RateHelperVector``."""

    if isinstance(helpers, ql.RateHelperVector):
        return helpers
    vector = ql.RateHelperVector()
    for helper in helpers:
        vector.push_back(helper)
    if len(vector) == 0:
        raise ValueError("At least one QuantLib rate helper is required.")
    return vector


def _day_counter(value: ql.DayCounter | str | Mapping[str, Any]) -> ql.DayCounter:
    if isinstance(value, ql.DayCounter):
        return value
    return daycount_from_json(value)


def _calendar(value: ql.Calendar | str | Mapping[str, Any]) -> ql.Calendar:
    if isinstance(value, ql.Calendar):
        return value
    return calendar_from_json(value)


def _business_day_convention(value: int | str) -> int:
    return bdc_from_json(value)


__all__ = [
    "OISRateHelperSpec",
    "OvernightDepositHelperSpec",
    "RateHelperSpec",
    "build_ois_rate_helper",
    "build_overnight_deposit_helper",
    "build_rate_helper",
    "build_rate_helper_vector",
    "build_rate_helpers",
    "ql_period_from_tenor",
]
