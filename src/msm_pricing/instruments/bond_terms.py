"""Provider-neutral bond terms used to build pricing instrument models."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, TypeVar

import QuantLib as ql

from msm_pricing.instruments.base_instrument import InstrumentModel
from msm_pricing.instruments.bond import FixedRateBond, FloatingRateBond, ZeroCouponBond
from msm_pricing.utils import to_ql_date

_MISSING = object()
_T = TypeVar("_T")

BondInstrumentType = Literal[
    "zero_coupon_bond",
    "fixed_rate_bond",
    "floating_rate_bond",
]


@dataclass(frozen=True, slots=True)
class BondInstrumentTerms:
    """Provider-neutral terms for constructing existing bond instrument models.

    These terms are an adapter input, not a persisted pricing-detail payload.
    Source adapters should map provider rows into this object, then call
    ``build_bond_instrument_from_terms(...)`` and persist the resulting
    instrument with the normal instrument serialization path.
    """

    instrument_type: BondInstrumentType
    valuation_date: dt.date | dt.datetime
    issue_date: dt.date | dt.datetime
    maturity_date: dt.date | dt.datetime
    face_value: float
    day_count: ql.DayCounter
    calendar: ql.Calendar
    business_day_convention: int
    settlement_days: int
    benchmark_rate_index_uid: uuid.UUID | None = None
    coupon_frequency: ql.Period | None = None
    coupon_rate: float | None = None
    floating_rate_index_uid: uuid.UUID | None = None
    spread: float | None = None
    schedule: ql.Schedule | None = None


@contextmanager
def quantlib_evaluation_settings(
    valuation_date: dt.date | dt.datetime,
    *,
    include_reference_date_events: bool = False,
    enforce_todays_historic_fixings: bool = False,
) -> Iterator[None]:
    """Temporarily apply QuantLib global settings for instrument construction.

    QuantLib stores evaluation settings globally. This context manager restores
    the previous evaluation date and supported boolean settings after the
    construction block exits, including when construction raises.
    """

    settings = ql.Settings.instance()
    previous_evaluation_date = settings.evaluationDate
    previous_include_reference_date_events = settings.includeReferenceDateEvents
    previous_enforce_todays_historic_fixings = getattr(
        settings,
        "enforceTodaysHistoricFixings",
        _MISSING,
    )

    settings.evaluationDate = to_ql_date(valuation_date)
    settings.includeReferenceDateEvents = include_reference_date_events
    if previous_enforce_todays_historic_fixings is not _MISSING:
        settings.enforceTodaysHistoricFixings = enforce_todays_historic_fixings
    try:
        yield
    finally:
        settings.evaluationDate = previous_evaluation_date
        settings.includeReferenceDateEvents = previous_include_reference_date_events
        if previous_enforce_todays_historic_fixings is not _MISSING:
            settings.enforceTodaysHistoricFixings = previous_enforce_todays_historic_fixings


def build_bond_instrument_from_terms(
    terms: BondInstrumentTerms,
    *,
    include_reference_date_events: bool = False,
    enforce_todays_historic_fixings: bool = False,
) -> InstrumentModel:
    """Build an existing ms-markets bond instrument from generic terms.

    The builder performs no asset lookup, provider row parsing, reference-index
    bootstrap, or schedule repair. Floating-rate terms require an explicit
    ``floating_rate_index_uid``. Zero-coupon and fixed-rate terms may omit
    ``benchmark_rate_index_uid`` because that field is benchmark metadata, not
    a cashflow requirement.
    """

    with quantlib_evaluation_settings(
        terms.valuation_date,
        include_reference_date_events=include_reference_date_events,
        enforce_todays_historic_fixings=enforce_todays_historic_fixings,
    ):
        if terms.instrument_type == "zero_coupon_bond":
            instrument: InstrumentModel = ZeroCouponBond(
                face_value=terms.face_value,
                benchmark_rate_index_uid=terms.benchmark_rate_index_uid,
                issue_date=terms.issue_date,
                maturity_date=terms.maturity_date,
                day_count=terms.day_count,
                calendar=terms.calendar,
                business_day_convention=terms.business_day_convention,
                settlement_days=terms.settlement_days,
            )
        elif terms.instrument_type == "fixed_rate_bond":
            instrument = FixedRateBond(
                face_value=terms.face_value,
                coupon_rate=_required(
                    terms.coupon_rate,
                    "coupon_rate",
                    terms.instrument_type,
                ),
                benchmark_rate_index_uid=terms.benchmark_rate_index_uid,
                issue_date=terms.issue_date,
                maturity_date=terms.maturity_date,
                coupon_frequency=_required(
                    terms.coupon_frequency,
                    "coupon_frequency",
                    terms.instrument_type,
                ),
                day_count=terms.day_count,
                calendar=terms.calendar,
                business_day_convention=terms.business_day_convention,
                settlement_days=terms.settlement_days,
                schedule=terms.schedule,
            )
        elif terms.instrument_type == "floating_rate_bond":
            floating_rate_index_uid = _required(
                terms.floating_rate_index_uid,
                "floating_rate_index_uid",
                terms.instrument_type,
            )
            instrument = FloatingRateBond(
                face_value=terms.face_value,
                floating_rate_index_uid=floating_rate_index_uid,
                spread=0.0 if terms.spread is None else terms.spread,
                issue_date=terms.issue_date,
                maturity_date=terms.maturity_date,
                coupon_frequency=_required(
                    terms.coupon_frequency,
                    "coupon_frequency",
                    terms.instrument_type,
                ),
                day_count=terms.day_count,
                calendar=terms.calendar,
                business_day_convention=terms.business_day_convention,
                settlement_days=terms.settlement_days,
                benchmark_rate_index_uid=terms.benchmark_rate_index_uid
                or floating_rate_index_uid,
                schedule=terms.schedule,
            )
        else:
            raise ValueError(f"Unsupported bond instrument type: {terms.instrument_type!r}.")

    instrument.set_valuation_date(terms.valuation_date)
    return instrument


def _required(value: _T | None, field_name: str, instrument_type: str) -> _T:
    if value is None:
        raise ValueError(f"{field_name} is required for {instrument_type}.")
    return value


__all__ = [
    "BondInstrumentTerms",
    "BondInstrumentType",
    "build_bond_instrument_from_terms",
    "quantlib_evaluation_settings",
]
