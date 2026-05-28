from __future__ import annotations

import datetime
import uuid
from typing import Any

import QuantLib as ql

from msm.api.indices import Index
from msm_pricing.api.curves import Curve
from msm_pricing.api.index_convention_details import IndexConventionDetails
from msm_pricing.data_interface import data_interface
from msm_pricing.instruments.json_codec import (
    bdc_from_json,
    calendar_from_json,
    daycount_from_json,
    period_from_json,
)
from msm_pricing.utils import to_py_date, to_ql_date


def resolve_index_convention(index_uid: uuid.UUID | str) -> IndexConventionDetails:
    """Load pricing convention details for a canonical ``IndexTable.uid``."""

    index_uid = _coerce_uuid(index_uid, field_name="index_uid")
    convention = IndexConventionDetails.get_by_index_uid(index_uid)
    if convention is None:
        raise LookupError(f"No pricing convention details found for index_uid={index_uid}.")
    return convention


def select_curve(
    *,
    index_uid: uuid.UUID | str,
    curve_type: str = "discount",
    source: str | None = None,
    curve_unique_identifier: str | None = None,
) -> Curve:
    """Select a curve identity row for an index UID using strict default rules."""

    index_uid = _coerce_uuid(index_uid, field_name="index_uid")
    if curve_unique_identifier:
        curve = Curve.get_by_unique_identifier(curve_unique_identifier)
        if curve is None:
            raise LookupError(
                f"No curve row found for unique_identifier={curve_unique_identifier!r}."
            )
        if curve.index_uid != index_uid:
            raise ValueError(
                f"Curve {curve.unique_identifier!r} belongs to index_uid={curve.index_uid}, "
                f"not index_uid={index_uid}."
            )
        if curve_type and curve.curve_type != curve_type:
            raise ValueError(
                f"Curve {curve.unique_identifier!r} has curve_type={curve.curve_type!r}, "
                f"not {curve_type!r}."
            )
        if source and curve.source != source:
            raise ValueError(
                f"Curve {curve.unique_identifier!r} has source={curve.source!r}, "
                f"not {source!r}."
            )
        return curve

    filters: dict[str, Any] = {
        "index_uid": index_uid,
        "curve_type": curve_type,
    }
    if source is not None:
        filters["source"] = source

    matches = Curve.filter(limit=2, **filters)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(
            f"No curve row found for index_uid={index_uid}, curve_type={curve_type!r}"
            + (f", source={source!r}." if source else ".")
        )
    raise ValueError(
        f"Multiple curve rows match index_uid={index_uid}, curve_type={curve_type!r}. "
        "Pass source or curve_unique_identifier to select one explicitly."
    )


def resolve_pricing_curve(
    *,
    index_uid: uuid.UUID | str,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    curve_type: str = "discount",
    source: str | None = None,
    curve_unique_identifier: str | None = None,
) -> ql.YieldTermStructureHandle:
    """Resolve and build a QuantLib curve from pricing MetaTables and curve data."""

    index_uid = _coerce_uuid(index_uid, field_name="index_uid")
    convention = resolve_index_convention(index_uid)
    curve = select_curve(
        index_uid=index_uid,
        curve_type=curve_type,
        source=source,
        curve_unique_identifier=curve_unique_identifier,
    )
    return build_curve_from_curve_row(
        curve=curve,
        convention=convention,
        valuation_date=valuation_date,
    )


def build_curve_from_curve_row(
    *,
    curve: Curve,
    convention: IndexConventionDetails,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
) -> ql.YieldTermStructureHandle:
    """Build a QuantLib discount curve from a curve row and convention payload."""

    target_date = _ensure_datetime(valuation_date)
    nodes, effective_curve_date = data_interface.get_historical_discount_curve(
        curve.unique_identifier,
        target_date,
    )

    base_dt = _ensure_datetime(effective_curve_date)
    base = to_ql_date(base_dt)
    convention_dump = convention.convention_dump
    day_counter = _day_counter_from_convention(convention_dump)
    calendar = _calendar_from_convention(convention_dump)

    dates = [base]
    discounts = [1.0]
    seen = {base.serialNumber()}
    for node in sorted(nodes, key=lambda item: int(item["days_to_maturity"])):
        days = int(node["days_to_maturity"])
        if days <= 0:
            continue
        ql_date = to_ql_date(base_dt + datetime.timedelta(days=days))
        if ql_date.serialNumber() in seen:
            continue
        seen.add(ql_date.serialNumber())
        zero = float(node.get("zero", node.get("zero_rate", node.get("rate"))))
        if zero > 1.0:
            zero *= 0.01
        tenor = day_counter.yearFraction(base, ql_date)
        discounts.append(1.0 / (1.0 + zero * tenor))
        dates.append(ql_date)

    term_structure = ql.DiscountCurve(dates, discounts, day_counter, calendar)
    term_structure.enableExtrapolation()
    return ql.YieldTermStructureHandle(term_structure)


def resolve_quantlib_index(
    index_uid: uuid.UUID | str,
    *,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    forwarding_curve: ql.YieldTermStructureHandle | ql.YieldTermStructure | None = None,
    hydrate_fixings: bool = True,
    settlement_days: int | None = None,
    curve_type: str = "discount",
    source: str | None = None,
    curve_unique_identifier: str | None = None,
) -> ql.IborIndex:
    """Build a QuantLib Ibor index from a canonical backend index UID."""

    index_uid = _coerce_uuid(index_uid, field_name="index_uid")
    index = Index.get_by_uid(index_uid)
    if index is None:
        raise LookupError(f"No canonical index row found for index_uid={index_uid}.")

    convention = resolve_index_convention(index_uid)
    convention_dump = convention.convention_dump
    curve = _as_curve_handle(forwarding_curve)
    if curve is None:
        curve = resolve_pricing_curve(
            index_uid=index_uid,
            valuation_date=valuation_date,
            curve_type=curve_type,
            source=source,
            curve_unique_identifier=curve_unique_identifier,
        )

    ql_index = ql.IborIndex(
        index.unique_identifier,
        _period_from_convention(convention_dump, index_family=convention.index_family),
        int(settlement_days if settlement_days is not None else _settlement_days(convention_dump)),
        _currency_from_convention(convention_dump),
        _calendar_from_convention(convention_dump),
        _business_day_convention(convention_dump),
        _end_of_month(convention_dump),
        _day_counter_from_convention(convention_dump),
        curve,
    )

    if hydrate_fixings:
        target_date = _ensure_datetime(valuation_date)
        fixings_identifier = str(
            convention_dump.get("fixings_unique_identifier")
            or convention_dump.get("fixings_uid")
            or index.unique_identifier
        )
        add_historical_fixings(
            to_ql_date(target_date),
            ql_index,
            reference_rate_uid=fixings_identifier,
        )

    return ql_index


def add_historical_fixings(
    target_date: ql.Date | datetime.date | datetime.datetime,
    ibor_index: ql.IborIndex,
    reference_rate_uid: str,
) -> None:
    """Hydrate a QuantLib index from the configured pricing fixings DataNode."""

    end_date = _ensure_datetime(target_date)
    start_date = end_date - datetime.timedelta(days=365)
    historical_fixings = data_interface.get_historical_fixings(
        reference_rate_uid,
        start_date,
        end_date,
    )

    ql_dates = ql.DateVector()
    values = ql.DoubleVector()
    seen_serials: set[int] = set()
    for fixing_date, fixing_value in historical_fixings.items():
        ql_date = to_ql_date(fixing_date)
        serial = ql_date.serialNumber()
        if serial in seen_serials:
            continue
        seen_serials.add(serial)
        ql_dates.push_back(ql_date)
        values.push_back(float(fixing_value))

    if len(ql_dates) > 0:
        ibor_index.addFixings(ql_dates, values, True)


def _coerce_uuid(value: uuid.UUID | str, *, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID value.") from exc


def _ensure_datetime(value: datetime.date | datetime.datetime | ql.Date) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())
    return to_py_date(value)


def _as_curve_handle(
    curve: ql.YieldTermStructureHandle | ql.YieldTermStructure | None,
) -> ql.YieldTermStructureHandle | None:
    if curve is None:
        return None
    if isinstance(curve, ql.YieldTermStructureHandle):
        return curve
    return ql.YieldTermStructureHandle(curve)


def _convention_value(convention_dump: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = convention_dump.get(key)
        if value is not None:
            return value
    return None


def _day_counter_from_convention(convention_dump: dict[str, Any]) -> ql.DayCounter:
    value = _convention_value(
        convention_dump,
        "day_counter_code",
        "day_count_code",
        "day_counter",
        "day_count",
    )
    if value is None:
        raise ValueError("Index convention payload must include day_counter_code.")
    return daycount_from_json(value)


def _calendar_from_convention(convention_dump: dict[str, Any]) -> ql.Calendar:
    value = _convention_value(
        convention_dump,
        "fixing_calendar_code",
        "calendar_code",
        "calendar",
    )
    if value is None:
        return ql.TARGET()
    if isinstance(value, str):
        upper = value.upper()
        if upper in {"US", "USD"}:
            return ql.UnitedStates(ql.UnitedStates.Settlement)
        if upper in {"MX", "MXN", "MEXICO"}:
            return ql.Mexico()
        if upper in {"TARGET", "EUR"}:
            return ql.TARGET()
    return calendar_from_json(value)


def _period_from_convention(
    convention_dump: dict[str, Any],
    *,
    index_family: str | None = None,
) -> ql.Period:
    value = _convention_value(
        convention_dump,
        "period",
        "tenor",
        "index_tenor",
        "rate_tenor",
    )
    if value is not None:
        period = period_from_json(value)
        if period is not None:
            return period
    period_days = _convention_value(convention_dump, "period_days", "tenor_days")
    if period_days is not None:
        return ql.Period(int(period_days), ql.Days)
    if str(index_family or convention_dump.get("index_family", "")).lower() == "overnight":
        return ql.Period(1, ql.Days)
    raise ValueError("Index convention payload must include period, tenor, or period_days.")


def _currency_from_convention(convention_dump: dict[str, Any]) -> ql.Currency:
    code = str(
        _convention_value(convention_dump, "currency_code", "currency") or ""
    ).upper()
    factories = {
        "USD": ql.USDCurrency,
        "EUR": ql.EURCurrency,
        "MXN": ql.MXNCurrency,
        "GBP": ql.GBPCurrency,
        "JPY": ql.JPYCurrency,
        "CAD": ql.CADCurrency,
    }
    factory = factories.get(code)
    if factory is None:
        raise ValueError("Index convention payload must include a supported currency_code.")
    return factory()


def _settlement_days(convention_dump: dict[str, Any]) -> int:
    return int(_convention_value(convention_dump, "settlement_days") or 0)


def _business_day_convention(convention_dump: dict[str, Any]) -> int:
    value = _convention_value(convention_dump, "business_day_convention", "bdc")
    return int(bdc_from_json(value or ql.ModifiedFollowing))


def _end_of_month(convention_dump: dict[str, Any]) -> bool:
    return bool(_convention_value(convention_dump, "end_of_month") or False)


__all__ = [
    "add_historical_fixings",
    "build_curve_from_curve_row",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "select_curve",
]
