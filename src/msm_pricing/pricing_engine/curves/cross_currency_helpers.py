"""Primitive QuantLib cross-currency helper builders."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import QuantLib as ql

from msm_pricing.instruments.json_codec import bdc_from_json, calendar_from_json

_TENOR_RE = re.compile(r"^\s*(?P<count>[1-9][0-9]*)\s*(?P<unit>[DWMY])\s*$", re.I)


@dataclass(frozen=True, slots=True)
class FxSwapRateHelperSpec:
    """Inputs required to build a QuantLib FX swap rate helper."""

    forward_points: float
    spot: float
    tenor: str | ql.Period
    fixing_days: int
    collateral_curve: ql.YieldTermStructureHandle
    calendar: ql.Calendar | str | Mapping[str, Any] = field(default_factory=ql.TARGET)
    convention: int | str = ql.ModifiedFollowing
    end_of_month: bool = False
    is_fx_base_currency_collateral_currency: bool = True
    trading_calendar: ql.Calendar | str | Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ConstNotionalCrossCurrencyBasisSwapRateHelperSpec:
    """Inputs required for a constant-notional cross-currency basis helper."""

    basis: float
    tenor: str | ql.Period
    fixing_days: int
    base_currency_index: ql.IborIndex | ql.OvernightIndex
    quote_currency_index: ql.IborIndex | ql.OvernightIndex
    collateral_curve: ql.YieldTermStructureHandle
    calendar: ql.Calendar | str | Mapping[str, Any] = field(default_factory=ql.TARGET)
    convention: int | str = ql.ModifiedFollowing
    end_of_month: bool = False
    is_fx_base_currency_collateral_currency: bool = True
    is_basis_on_fx_base_currency_leg: bool = True
    payment_frequency: int | str = ql.NoFrequency
    payment_lag: int = 0


CrossCurrencyRateHelperSpec = (
    FxSwapRateHelperSpec | ConstNotionalCrossCurrencyBasisSwapRateHelperSpec
)


def build_fx_swap_rate_helper(spec: FxSwapRateHelperSpec) -> ql.RateHelper:
    """Build a QuantLib ``FxSwapRateHelper`` from primitive inputs."""

    return ql.FxSwapRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(float(spec.forward_points))),
        ql.QuoteHandle(ql.SimpleQuote(float(spec.spot))),
        _ql_period_from_tenor(spec.tenor),
        int(spec.fixing_days),
        _calendar(spec.calendar),
        _business_day_convention(spec.convention),
        bool(spec.end_of_month),
        bool(spec.is_fx_base_currency_collateral_currency),
        spec.collateral_curve,
        _optional_calendar(spec.trading_calendar),
    )


def build_const_notional_cross_currency_basis_swap_rate_helper(
    spec: ConstNotionalCrossCurrencyBasisSwapRateHelperSpec,
) -> ql.RateHelper:
    """Build a QuantLib constant-notional cross-currency basis helper."""

    return ql.ConstNotionalCrossCurrencyBasisSwapRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(float(spec.basis))),
        _ql_period_from_tenor(spec.tenor),
        int(spec.fixing_days),
        _calendar(spec.calendar),
        _business_day_convention(spec.convention),
        bool(spec.end_of_month),
        spec.base_currency_index,
        spec.quote_currency_index,
        spec.collateral_curve,
        bool(spec.is_fx_base_currency_collateral_currency),
        bool(spec.is_basis_on_fx_base_currency_leg),
        _frequency(spec.payment_frequency),
        int(spec.payment_lag),
    )


def build_cross_currency_rate_helper(spec: CrossCurrencyRateHelperSpec) -> ql.RateHelper:
    """Build a QuantLib helper for one supported cross-currency helper spec."""

    if isinstance(spec, FxSwapRateHelperSpec):
        return build_fx_swap_rate_helper(spec)
    if isinstance(spec, ConstNotionalCrossCurrencyBasisSwapRateHelperSpec):
        return build_const_notional_cross_currency_basis_swap_rate_helper(spec)
    raise TypeError(f"Unsupported cross-currency helper spec type: {type(spec).__name__}.")


def _ql_period_from_tenor(tenor: str | ql.Period) -> ql.Period:
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


def _frequency(value: int | str) -> int:
    if isinstance(value, int):
        return int(value)
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    frequency_by_token = {
        "nofrequency": ql.NoFrequency,
        "no_frequency": ql.NoFrequency,
        "once": ql.Once,
        "annual": ql.Annual,
        "annually": ql.Annual,
        "semiannual": ql.Semiannual,
        "semi_annual": ql.Semiannual,
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


__all__ = [
    "ConstNotionalCrossCurrencyBasisSwapRateHelperSpec",
    "CrossCurrencyRateHelperSpec",
    "FxSwapRateHelperSpec",
    "build_const_notional_cross_currency_basis_swap_rate_helper",
    "build_cross_currency_rate_helper",
    "build_fx_swap_rate_helper",
]
