"""Primitive QuantLib rate-helper builders for curve reconstruction."""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import QuantLib as ql

from msm_pricing.instruments.json_codec import (
    bdc_from_json,
    calendar_from_json,
    daycount_from_json,
)
from msm_pricing.pricing_engine.curves.bond_helpers import (
    BondHelperSpec,
    FixedRateBondHelperSpec,
    ZeroCouponBondHelperSpec,
    build_bond_helper,
)
from msm_pricing.pricing_engine.curves.cross_currency_helpers import (
    ConstNotionalCrossCurrencyBasisSwapRateHelperSpec,
    CrossCurrencyRateHelperSpec,
    FxSwapRateHelperSpec,
    build_cross_currency_rate_helper,
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
    discounting_curve: ql.YieldTermStructureHandle | None = None
    telescopic_value_dates: bool = False
    payment_lag: int = 0
    payment_convention: int | str = ql.Following
    payment_frequency: int | str = ql.Annual
    payment_calendar: ql.Calendar | str | Mapping[str, Any] | None = None
    forward_start: str | ql.Period = field(default_factory=lambda: ql.Period(0, ql.Days))
    overnight_spread: float = 0.0
    pillar: int | str = ql.Pillar.LastRelevantDate
    custom_pillar_date: ql.Date | dt.date | dt.datetime | str | None = None
    averaging_method: int | str = ql.RateAveraging.Compound
    end_of_month: bool | None = None
    fixed_payment_frequency: int | str | None = None
    fixed_calendar: ql.Calendar | str | Mapping[str, Any] | None = None
    lookback_days: int | None = None
    lockout_days: int = 0
    apply_observation_shift: bool = False
    pricer: ql.FloatingRateCouponPricer | None = None
    rule: int | str = ql.DateGeneration.Backward
    overnight_calendar: ql.Calendar | str | Mapping[str, Any] | None = None
    date_generation_convention: int | str = ql.ModifiedFollowing


@dataclass(frozen=True, slots=True)
class InterestRateFutureHelperSpec:
    """Inputs required to build a QuantLib interest-rate futures helper."""

    quote: float
    reference_month: int | str
    reference_year: int
    reference_frequency: int | str
    future_family: str = "sofr"
    convexity_adjustment: float = 0.0
    pillar: int | str = ql.Pillar.LastRelevantDate
    custom_pillar_date: ql.Date | dt.date | dt.datetime | str | None = None


RateHelperSpec = (
    OvernightDepositHelperSpec
    | OISRateHelperSpec
    | InterestRateFutureHelperSpec
    | BondHelperSpec
    | CrossCurrencyRateHelperSpec
)


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

    args: list[Any] = [
        int(spec.settlement_days),
        ql_period_from_tenor(spec.tenor),
        ql.QuoteHandle(ql.SimpleQuote(float(spec.quote))),
        spec.overnight_index,
        spec.discounting_curve or ql.YieldTermStructureHandle(),
        bool(spec.telescopic_value_dates),
        int(spec.payment_lag),
        _business_day_convention(spec.payment_convention),
        _frequency(spec.payment_frequency),
        _optional_calendar(spec.payment_calendar),
        _ql_period_from_nonnegative_tenor(spec.forward_start),
        float(spec.overnight_spread),
        _pillar(spec.pillar),
        _date(spec.custom_pillar_date),
        _rate_averaging(spec.averaging_method),
        spec.end_of_month,
        _optional_frequency(spec.fixed_payment_frequency),
        _optional_calendar(spec.fixed_calendar),
    ]
    if _uses_observation_shift_overload(spec):
        if spec.lookback_days is None:
            raise ValueError(
                "lookback_days is required when using OIS observation-shift overload fields."
            )
        args.extend(
            [
                int(spec.lookback_days),
                int(spec.lockout_days),
                bool(spec.apply_observation_shift),
                spec.pricer,
                _date_generation_rule(spec.rule),
                _optional_calendar(spec.overnight_calendar),
                _business_day_convention(spec.date_generation_convention),
            ]
        )
    return ql.OISRateHelper(*args)


def build_interest_rate_future_helper(spec: InterestRateFutureHelperSpec) -> ql.RateHelper:
    """Build a QuantLib interest-rate futures helper from primitive inputs."""

    family = _normalize_token(spec.future_family)
    if family not in {"sofr", "sofr_future", "sofr_future_rate_helper"}:
        raise ValueError(
            f"Unsupported interest-rate futures helper family {spec.future_family!r}."
        )
    return ql.SofrFutureRateHelper(
        float(spec.quote),
        _month(spec.reference_month),
        int(spec.reference_year),
        _frequency(spec.reference_frequency),
        float(spec.convexity_adjustment),
        _pillar(spec.pillar),
        _date(spec.custom_pillar_date),
    )


def build_rate_helper(spec: RateHelperSpec) -> ql.RateHelper:
    """Build a QuantLib helper for one supported primitive helper spec."""

    if isinstance(spec, OvernightDepositHelperSpec):
        return build_overnight_deposit_helper(spec)
    if isinstance(spec, OISRateHelperSpec):
        return build_ois_rate_helper(spec)
    if isinstance(spec, InterestRateFutureHelperSpec):
        return build_interest_rate_future_helper(spec)
    if isinstance(spec, ZeroCouponBondHelperSpec | FixedRateBondHelperSpec):
        return build_bond_helper(spec)
    if isinstance(
        spec,
        FxSwapRateHelperSpec | ConstNotionalCrossCurrencyBasisSwapRateHelperSpec,
    ):
        return build_cross_currency_rate_helper(spec)
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


def _optional_calendar(value: ql.Calendar | str | Mapping[str, Any] | None) -> ql.Calendar:
    if value is None:
        return ql.NullCalendar()
    return _calendar(value)


def _business_day_convention(value: int | str) -> int:
    return bdc_from_json(value)


def _ql_period_from_nonnegative_tenor(tenor: str | ql.Period) -> ql.Period:
    if isinstance(tenor, ql.Period):
        return tenor
    match = re.match(r"^\s*(?P<count>[0-9]+)\s*(?P<unit>[DWMY])\s*$", str(tenor or ""), re.I)
    if match is None:
        raise ValueError(
            f"Unsupported tenor={tenor!r}. Expected a non-negative integer plus D, W, M, or Y."
        )
    count = int(match.group("count"))
    unit = match.group("unit").upper()
    units = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}
    return ql.Period(count, units[unit])


def _frequency(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = _normalize_token(value)
    frequency_by_token = {
        "nofrequency": ql.NoFrequency,
        "no_frequency": ql.NoFrequency,
        "once": ql.Once,
        "annual": ql.Annual,
        "annually": ql.Annual,
        "semiannual": ql.Semiannual,
        "semi_annual": ql.Semiannual,
        "semi-annually": ql.Semiannual,
        "semiannually": ql.Semiannual,
        "every_fourth_month": ql.EveryFourthMonth,
        "everyfourthmonth": ql.EveryFourthMonth,
        "quarterly": ql.Quarterly,
        "bimonthly": ql.Bimonthly,
        "monthly": ql.Monthly,
        "every_fourth_week": ql.EveryFourthWeek,
        "everyfourthweek": ql.EveryFourthWeek,
        "biweekly": ql.Biweekly,
        "weekly": ql.Weekly,
        "daily": ql.Daily,
        "otherfrequency": ql.OtherFrequency,
        "other_frequency": ql.OtherFrequency,
    }
    try:
        return int(frequency_by_token[token])
    except KeyError as exc:
        raise ValueError(f"Unsupported QuantLib frequency {value!r}.") from exc


def _month(value: int | str) -> int:
    if isinstance(value, int):
        if 1 <= value <= 12:
            return int(value)
        raise ValueError(f"Unsupported QuantLib month {value!r}.")
    token = _normalize_token(value).replace("_", "")
    if token.isdigit():
        return _month(int(token))
    month_by_token = {
        "jan": ql.January,
        "january": ql.January,
        "feb": ql.February,
        "february": ql.February,
        "mar": ql.March,
        "march": ql.March,
        "apr": ql.April,
        "april": ql.April,
        "may": ql.May,
        "jun": ql.June,
        "june": ql.June,
        "jul": ql.July,
        "july": ql.July,
        "aug": ql.August,
        "august": ql.August,
        "sep": ql.September,
        "sept": ql.September,
        "september": ql.September,
        "oct": ql.October,
        "october": ql.October,
        "nov": ql.November,
        "november": ql.November,
        "dec": ql.December,
        "december": ql.December,
    }
    try:
        return int(month_by_token[token])
    except KeyError as exc:
        raise ValueError(f"Unsupported QuantLib month {value!r}.") from exc


def _optional_frequency(value: int | str | None) -> int | None:
    if value in (None, ""):
        return None
    return _frequency(value)


def _pillar(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = _normalize_token(value)
    pillar_by_token = {
        "maturitydate": ql.Pillar.MaturityDate,
        "maturity_date": ql.Pillar.MaturityDate,
        "lastrelevantdate": ql.Pillar.LastRelevantDate,
        "last_relevant_date": ql.Pillar.LastRelevantDate,
        "customdate": ql.Pillar.CustomDate,
        "custom_date": ql.Pillar.CustomDate,
    }
    try:
        return int(pillar_by_token[token])
    except KeyError as exc:
        raise ValueError(f"Unsupported QuantLib pillar choice {value!r}.") from exc


def _rate_averaging(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = _normalize_token(value)
    averaging_by_token = {
        "compound": ql.RateAveraging.Compound,
        "compounded": ql.RateAveraging.Compound,
        "simple": ql.RateAveraging.Simple,
    }
    try:
        return int(averaging_by_token[token])
    except KeyError as exc:
        raise ValueError(f"Unsupported QuantLib rate averaging method {value!r}.") from exc


def _date_generation_rule(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = _normalize_token(value)
    rule_by_token = {
        "backward": ql.DateGeneration.Backward,
        "forward": ql.DateGeneration.Forward,
        "zero": ql.DateGeneration.Zero,
        "twentieth": ql.DateGeneration.Twentieth,
        "twentiethimm": ql.DateGeneration.TwentiethIMM,
        "twentieth_imm": ql.DateGeneration.TwentiethIMM,
        "thirdwednesday": ql.DateGeneration.ThirdWednesday,
        "third_wednesday": ql.DateGeneration.ThirdWednesday,
        "thirdwednesdayinclusive": ql.DateGeneration.ThirdWednesdayInclusive,
        "third_wednesday_inclusive": ql.DateGeneration.ThirdWednesdayInclusive,
        "oldcds": ql.DateGeneration.OldCDS,
        "old_cds": ql.DateGeneration.OldCDS,
        "cds": ql.DateGeneration.CDS,
        "cds2015": ql.DateGeneration.CDS2015,
    }
    try:
        return int(rule_by_token[token])
    except KeyError as exc:
        raise ValueError(f"Unsupported QuantLib date-generation rule {value!r}.") from exc


def _date(value: ql.Date | dt.date | dt.datetime | str | None) -> ql.Date:
    if value in (None, ""):
        return ql.Date()
    if isinstance(value, ql.Date):
        return value
    if isinstance(value, dt.datetime):
        return ql.Date(value.day, value.month, value.year)
    if isinstance(value, dt.date):
        return ql.Date(value.day, value.month, value.year)
    if isinstance(value, str):
        year, month, day = (int(part) for part in value.split("-"))
        return ql.Date(day, month, year)
    raise TypeError(f"Unsupported QuantLib date value {value!r}.")


def _normalize_token(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _uses_observation_shift_overload(spec: OISRateHelperSpec) -> bool:
    return (
        spec.lookback_days is not None
        or spec.lockout_days != 0
        or spec.apply_observation_shift
        or spec.pricer is not None
        or int(_date_generation_rule(spec.rule)) != int(ql.DateGeneration.Backward)
        or spec.overnight_calendar is not None
        or int(_business_day_convention(spec.date_generation_convention))
        != int(ql.ModifiedFollowing)
    )


__all__ = [
    "BondHelperSpec",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperSpec",
    "CrossCurrencyRateHelperSpec",
    "FixedRateBondHelperSpec",
    "FxSwapRateHelperSpec",
    "InterestRateFutureHelperSpec",
    "OISRateHelperSpec",
    "OvernightDepositHelperSpec",
    "RateHelperSpec",
    "ZeroCouponBondHelperSpec",
    "build_bond_helper",
    "build_cross_currency_rate_helper",
    "build_interest_rate_future_helper",
    "build_ois_rate_helper",
    "build_overnight_deposit_helper",
    "build_rate_helper",
    "build_rate_helper_vector",
    "build_rate_helpers",
    "ql_period_from_tenor",
]
