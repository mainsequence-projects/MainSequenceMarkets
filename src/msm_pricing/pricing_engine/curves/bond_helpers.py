"""Primitive QuantLib bond-helper builders for curve reconstruction."""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import QuantLib as ql

from msm_pricing.instruments.json_codec import (
    bdc_from_json,
    calendar_from_json,
    daycount_from_json,
    schedule_from_json,
)

BondQuoteType = Literal["clean_price", "dirty_price"]
BondQuoteUnit = Literal["price", "price_per_face", "price_per_100"]

_TENOR_RE = re.compile(r"^\s*(?P<count>[1-9][0-9]*)\s*(?P<unit>[DWMY])\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ZeroCouponBondHelperSpec:
    """Inputs required to build a QuantLib zero-coupon bond helper.

    The quote is a clean or dirty bond price. ``price`` and
    ``price_per_face`` are passed to QuantLib unchanged; ``price_per_100`` is
    scaled to the submitted ``face_value``. The spec is runtime-only and does
    not read persisted curve rows or provider-specific source records.
    """

    quote: float
    maturity_date: ql.Date | dt.date | dt.datetime | str
    quote_type: BondQuoteType = "clean_price"
    quote_unit: BondQuoteUnit = "price_per_face"
    settlement_days: int = 0
    calendar: ql.Calendar | str | Mapping[str, Any] = field(default_factory=ql.TARGET)
    face_value: float = 100.0
    payment_convention: int | str = ql.Following
    redemption: float | None = None
    issue_date: ql.Date | dt.date | dt.datetime | str | None = None


@dataclass(frozen=True, slots=True)
class FixedRateBondHelperSpec:
    """Inputs required to build a QuantLib fixed-rate bond helper.

    The quote is a clean or dirty bond price. Callers may supply an explicit
    QuantLib schedule, explicit schedule dates, or enough issue/maturity and
    coupon-period fields to build a schedule. This spec is provider-neutral;
    source row parsing and vendor price scaling happen before constructing it.
    """

    quote: float
    coupon_rate: float
    issue_date: ql.Date | dt.date | dt.datetime | str
    maturity_date: ql.Date | dt.date | dt.datetime | str
    quote_type: BondQuoteType = "clean_price"
    quote_unit: BondQuoteUnit = "price_per_100"
    settlement_days: int = 0
    face_value: float = 100.0
    calendar: ql.Calendar | str | Mapping[str, Any] = field(default_factory=ql.TARGET)
    tenor: str | ql.Period | None = None
    coupon_period_days: int | None = None
    coupon_frequency: int | str | None = None
    schedule: ql.Schedule | Mapping[str, Any] | Sequence[str | ql.Date] | None = None
    schedule_dates: Sequence[ql.Date | dt.date | dt.datetime | str] | None = None
    day_counter: ql.DayCounter | str | Mapping[str, Any] = field(default_factory=ql.Actual360)
    payment_convention: int | str = ql.Following
    business_day_convention: int | str = ql.Following
    termination_business_day_convention: int | str | None = None
    redemption: float | None = None
    payment_calendar: ql.Calendar | str | Mapping[str, Any] | None = None
    end_of_month: bool = False
    date_generation_rule: int | str = ql.DateGeneration.Backward
    first_date: ql.Date | dt.date | dt.datetime | str | None = None
    next_to_last_date: ql.Date | dt.date | dt.datetime | str | None = None
    ex_coupon_period: str | ql.Period | None = None
    ex_coupon_calendar: ql.Calendar | str | Mapping[str, Any] | None = None
    ex_coupon_convention: int | str = ql.Unadjusted
    ex_coupon_end_of_month: bool = False


BondHelperSpec = ZeroCouponBondHelperSpec | FixedRateBondHelperSpec


def build_zero_coupon_bond_helper(spec: ZeroCouponBondHelperSpec) -> ql.RateHelper:
    """Build a QuantLib ``BondHelper`` for a zero-coupon bond."""

    face_value = _positive_float(spec.face_value, field_name="face_value")
    redemption = face_value if spec.redemption is None else _positive_float(
        spec.redemption,
        field_name="redemption",
    )
    quote = normalize_bond_price_value(
        spec.quote,
        spec.quote_unit,
        face_value=face_value,
        field_name="quote",
    )
    bond = ql.ZeroCouponBond(
        int(spec.settlement_days),
        _calendar(spec.calendar),
        face_value,
        _date(spec.maturity_date),
        _business_day_convention(spec.payment_convention),
        redemption,
        _date(spec.issue_date),
    )
    return ql.BondHelper(
        ql.QuoteHandle(ql.SimpleQuote(quote)),
        bond,
        _bond_price_type(spec.quote_type),
    )


def build_fixed_rate_bond_helper(spec: FixedRateBondHelperSpec) -> ql.RateHelper:
    """Build a QuantLib ``FixedRateBondHelper`` from provider-neutral inputs."""

    face_value = _positive_float(spec.face_value, field_name="face_value")
    redemption = face_value if spec.redemption is None else _positive_float(
        spec.redemption,
        field_name="redemption",
    )
    quote = normalize_bond_price_value(
        spec.quote,
        spec.quote_unit,
        face_value=face_value,
        field_name="quote",
    )
    return ql.FixedRateBondHelper(
        ql.QuoteHandle(ql.SimpleQuote(quote)),
        int(spec.settlement_days),
        face_value,
        _schedule(spec),
        [float(spec.coupon_rate)],
        _day_counter(spec.day_counter),
        _business_day_convention(spec.payment_convention),
        redemption,
        _date(spec.issue_date),
        _optional_calendar(spec.payment_calendar),
        _optional_period(spec.ex_coupon_period),
        _optional_calendar(spec.ex_coupon_calendar),
        _business_day_convention(spec.ex_coupon_convention),
        bool(spec.ex_coupon_end_of_month),
        _bond_price_type(spec.quote_type),
    )


def build_bond_helper(spec: BondHelperSpec) -> ql.RateHelper:
    """Build a QuantLib bond helper for one supported bond-helper spec."""

    if isinstance(spec, ZeroCouponBondHelperSpec):
        return build_zero_coupon_bond_helper(spec)
    if isinstance(spec, FixedRateBondHelperSpec):
        return build_fixed_rate_bond_helper(spec)
    raise TypeError(f"Unsupported bond helper spec type: {type(spec).__name__}.")


def build_bond_helpers(specs: Sequence[BondHelperSpec]) -> tuple[ql.RateHelper, ...]:
    """Build QuantLib bond helpers from primitive helper specs."""

    return tuple(build_bond_helper(spec) for spec in specs)


def normalize_bond_price_value(
    value: object,
    unit: object,
    *,
    face_value: float,
    field_name: str = "price",
) -> float:
    """Normalize a raw clean/dirty bond price for QuantLib helper input."""

    raw = _finite_float(value, field_name=field_name)
    face = _positive_float(face_value, field_name="face_value")
    token = str(unit or "").strip().lower()
    if token in {"price", "price_per_face"}:
        return raw
    if token == "price_per_100":
        return raw * face / 100.0
    raise ValueError(
        f"Unsupported or missing bond price unit {unit!r}. "
        "Supported units: price, price_per_face, price_per_100."
    )


def _schedule(spec: FixedRateBondHelperSpec) -> ql.Schedule:
    if spec.schedule is not None:
        schedule = schedule_from_json(spec.schedule)
        if schedule is None:
            raise ValueError("Fixed-rate bond helper schedule cannot be None.")
        return schedule
    if spec.schedule_dates is not None:
        return _schedule_from_dates(
            spec.schedule_dates,
            calendar=_calendar(spec.calendar),
            convention=_business_day_convention(spec.business_day_convention),
        )

    tenor = _schedule_tenor(spec)
    calendar = _calendar(spec.calendar)
    convention = _business_day_convention(spec.business_day_convention)
    termination_convention = _business_day_convention(
        spec.termination_business_day_convention
        if spec.termination_business_day_convention is not None
        else spec.business_day_convention
    )
    return ql.Schedule(
        _date(spec.issue_date),
        _date(spec.maturity_date),
        tenor,
        calendar,
        convention,
        termination_convention,
        _date_generation_rule(spec.date_generation_rule),
        bool(spec.end_of_month),
        _date(spec.first_date),
        _date(spec.next_to_last_date),
    )


def _schedule_from_dates(
    schedule_dates: Sequence[ql.Date | dt.date | dt.datetime | str],
    *,
    calendar: ql.Calendar,
    convention: int,
) -> ql.Schedule:
    if isinstance(schedule_dates, str | bytes) or not isinstance(schedule_dates, Sequence):
        raise TypeError("schedule_dates must be a sequence of dates.")
    if not schedule_dates:
        raise ValueError("schedule_dates must contain at least one date.")
    date_vector = ql.DateVector()
    for value in schedule_dates:
        date_vector.push_back(_date(value))
    return ql.Schedule(date_vector, calendar, convention)


def _schedule_tenor(spec: FixedRateBondHelperSpec) -> ql.Period:
    if spec.tenor not in (None, ""):
        return _period(spec.tenor)
    if spec.coupon_period_days is not None:
        days = int(spec.coupon_period_days)
        if days <= 0:
            raise ValueError("coupon_period_days must be positive.")
        return ql.Period(days, ql.Days)
    if spec.coupon_frequency not in (None, ""):
        return _period_from_frequency(spec.coupon_frequency)
    raise ValueError(
        "Fixed-rate bond helper requires tenor, coupon_period_days, "
        "coupon_frequency, schedule, or schedule_dates."
    )


def _period_from_frequency(value: int | str) -> ql.Period:
    if isinstance(value, int):
        periods_per_year = int(value)
        if periods_per_year <= 0 or 12 % periods_per_year != 0:
            raise ValueError(f"Unsupported coupon_frequency={value!r}.")
        return ql.Period(12 // periods_per_year, ql.Months)
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    period_by_frequency = {
        "annual": ql.Period(1, ql.Years),
        "annually": ql.Period(1, ql.Years),
        "semiannual": ql.Period(6, ql.Months),
        "semi_annual": ql.Period(6, ql.Months),
        "semiannually": ql.Period(6, ql.Months),
        "quarterly": ql.Period(3, ql.Months),
        "monthly": ql.Period(1, ql.Months),
        "every_fourth_week": ql.Period(4, ql.Weeks),
        "everyfourthweek": ql.Period(4, ql.Weeks),
        "biweekly": ql.Period(2, ql.Weeks),
        "weekly": ql.Period(1, ql.Weeks),
    }
    try:
        return period_by_frequency[token]
    except KeyError as exc:
        raise ValueError(f"Unsupported coupon_frequency={value!r}.") from exc


def _period(value: str | ql.Period) -> ql.Period:
    if isinstance(value, ql.Period):
        return value
    match = _TENOR_RE.match(str(value or ""))
    if match is None:
        raise ValueError(
            f"Unsupported tenor={value!r}. Expected a positive integer plus D, W, M, or Y."
        )
    count = int(match.group("count"))
    unit = match.group("unit").upper()
    units = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}
    return ql.Period(count, units[unit])


def _optional_period(value: str | ql.Period | None) -> ql.Period:
    if value in (None, ""):
        return ql.Period()
    return _period(value)


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


def _bond_price_type(value: object) -> int:
    token = str(value or "").strip().lower()
    if token == "clean_price":
        return int(ql.BondPrice.Clean)
    if token == "dirty_price":
        return int(ql.BondPrice.Dirty)
    raise ValueError(
        f"Unsupported bond helper quote_type={value!r}. "
        "Supported values: clean_price, dirty_price."
    )


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


def _date_generation_rule(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
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


def _positive_float(value: object, *, field_name: str) -> float:
    out = _finite_float(value, field_name=field_name)
    if out <= 0.0:
        raise ValueError(f"{field_name} must be positive.")
    return out


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be a finite number.")
    return out


__all__ = [
    "BondHelperSpec",
    "BondQuoteType",
    "BondQuoteUnit",
    "FixedRateBondHelperSpec",
    "ZeroCouponBondHelperSpec",
    "build_bond_helper",
    "build_bond_helpers",
    "build_fixed_rate_bond_helper",
    "build_zero_coupon_bond_helper",
    "normalize_bond_price_value",
]
