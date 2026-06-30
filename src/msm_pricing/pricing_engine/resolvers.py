from __future__ import annotations

import datetime
import math
import uuid
from dataclasses import dataclass
from typing import Any

import QuantLib as ql

from msm.api.indices import Index
from msm_pricing.api.curve_building_details import CurveBuildingDetails
from msm_pricing.api.curves import Curve
from msm_pricing.api.index_convention_details import IndexConventionDetails
from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding
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


def resolve_curve_building_details(curve_uid: uuid.UUID | str) -> CurveBuildingDetails:
    """Load curve-owned build details for a CurveTable row."""

    curve_uid = _coerce_uuid(curve_uid, field_name="curve_uid")
    details = CurveBuildingDetails.get_by_curve_uid(curve_uid)
    if details is None:
        raise LookupError(f"No curve building details found for curve_uid={curve_uid}.")
    return details


@dataclass(frozen=True)
class CurveSelectionContext:
    """Normalized market-data curve binding selector.

    This object carries binding identity only. It deliberately does not store
    QuantLib handles or resolved curve rows.
    """

    market_data_set: Any | None
    role_key: str
    selector_type: str
    selector_key: str
    quote_side: str | None = None
    curve_uid: uuid.UUID | str | None = None
    curve_unique_identifier: str | None = None
    expected_curve_type: str | None = None
    source: str | None = None

    @classmethod
    def for_index(
        cls,
        *,
        index_uid: uuid.UUID | str,
        role_key: str,
        market_data_set: Any | None = None,
        quote_side: str | None = None,
        curve_uid: uuid.UUID | str | None = None,
        curve_unique_identifier: str | None = None,
        expected_curve_type: str | None = None,
        source: str | None = None,
    ) -> CurveSelectionContext:
        return cls(
            market_data_set=market_data_set,
            role_key=_normalize_curve_selection_part(role_key, field_name="role_key").lower(),
            selector_type="index",
            selector_key=str(_coerce_uuid(index_uid, field_name="index_uid")),
            quote_side=normalize_curve_quote_side(quote_side),
            curve_uid=curve_uid,
            curve_unique_identifier=curve_unique_identifier,
            expected_curve_type=expected_curve_type,
            source=source,
        )

    @classmethod
    def for_projection_index(
        cls,
        *,
        index_uid: uuid.UUID | str,
        market_data_set: Any | None = None,
        quote_side: str | None = None,
        **kwargs: Any,
    ) -> CurveSelectionContext:
        return cls.for_index(
            index_uid=index_uid,
            role_key="projection",
            market_data_set=market_data_set,
            quote_side=quote_side,
            expected_curve_type=kwargs.pop("expected_curve_type", "projection"),
            **kwargs,
        )

    @classmethod
    def for_forwarding_index(
        cls,
        *,
        index_uid: uuid.UUID | str,
        market_data_set: Any | None = None,
        quote_side: str | None = None,
        **kwargs: Any,
    ) -> CurveSelectionContext:
        return cls.for_index(
            index_uid=index_uid,
            role_key="forwarding",
            market_data_set=market_data_set,
            quote_side=quote_side,
            expected_curve_type=kwargs.pop("expected_curve_type", "forwarding"),
            **kwargs,
        )

    @classmethod
    def for_discount_index(
        cls,
        *,
        index_uid: uuid.UUID | str,
        market_data_set: Any | None = None,
        quote_side: str | None = None,
        **kwargs: Any,
    ) -> CurveSelectionContext:
        return cls.for_index(
            index_uid=index_uid,
            role_key="discount",
            market_data_set=market_data_set,
            quote_side=quote_side,
            expected_curve_type=kwargs.pop("expected_curve_type", "discount"),
            **kwargs,
        )

    @classmethod
    def for_z_spread_base_index(
        cls,
        *,
        index_uid: uuid.UUID | str,
        market_data_set: Any | None = None,
        quote_side: str | None = None,
        **kwargs: Any,
    ) -> CurveSelectionContext:
        return cls.for_index(
            index_uid=index_uid,
            role_key="z_spread_base",
            market_data_set=market_data_set,
            quote_side=quote_side,
            **kwargs,
        )

    def cache_key(self) -> str:
        side = self.quote_side or "default"
        curve_override = self.curve_uid or self.curve_unique_identifier or "binding"
        curve_type = self.expected_curve_type or "any"
        return (
            f"mds:{self.market_data_set or 'unresolved'}|role:{self.role_key}|"
            f"selector:{self.selector_type}:{self.selector_key}|side:{side}|"
            f"curve:{curve_override}|expected:{curve_type}|source:{self.source or 'any'}"
        )


def normalize_curve_quote_side(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return _normalize_curve_selection_part(value, field_name="quote_side").lower()


def _normalize_curve_selection_part(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def select_curve(
    *,
    index_uid: uuid.UUID | str | None = None,
    curve_type: str = "discount",
    expected_curve_type: str | None = None,
    validate_curve_type: bool = True,
    market_data_set: Any | None = None,
    role_key: str | None = None,
    selector_type: str | None = None,
    selector_key: str | None = None,
    quote_side: str | None = None,
    currency_code: str | None = None,
    source: str | None = None,
    curve_uid: uuid.UUID | str | None = None,
    curve_unique_identifier: str | None = None,
) -> Curve:
    """Select a curve identity row through explicit curve binding policy."""

    if curve_uid is not None and curve_unique_identifier is not None:
        raise ValueError("Pass either curve_uid or curve_unique_identifier, not both.")

    if curve_uid is not None:
        curve = Curve.get_by_uid(curve_uid)
        if curve is None:
            raise LookupError(f"No curve row found for uid={curve_uid!r}.")
        return _validate_selected_curve(
            curve,
            curve_type=_curve_type_validation_target(
                curve_type=curve_type,
                expected_curve_type=expected_curve_type,
                validate_curve_type=validate_curve_type,
            ),
            source=source,
        )

    if curve_unique_identifier:
        curve = Curve.get_by_unique_identifier(curve_unique_identifier)
        if curve is None:
            raise LookupError(
                f"No curve row found for unique_identifier={curve_unique_identifier!r}."
            )
        return _validate_selected_curve(
            curve,
            curve_type=_curve_type_validation_target(
                curve_type=curve_type,
                expected_curve_type=expected_curve_type,
                validate_curve_type=validate_curve_type,
            ),
            source=source,
        )

    role_key, selector_type, selector_key = _curve_binding_selector(
        index_uid=index_uid,
        curve_type=curve_type,
        role_key=role_key,
        selector_type=selector_type,
        selector_key=selector_key,
        currency_code=currency_code,
    )
    if str(selector_type).strip().lower() == "index":
        curve_uid = PricingMarketDataSetCurveBinding.resolve_index_curve_uid(
            market_data_set=market_data_set,
            role_key=role_key,
            index_uid=selector_key,
            quote_side=quote_side,
        )
    else:
        curve_uid = PricingMarketDataSetCurveBinding.resolve_curve_uid(
            market_data_set=market_data_set,
            role_key=role_key,
            selector_type=selector_type,
            selector_key=selector_key,
            quote_side=quote_side,
        )
    curve = Curve.get_by_uid(curve_uid)
    if curve is None:
        raise LookupError(
            f"Curve binding selected curve_uid={curve_uid}, but no Curve row was found."
        )
    return _validate_selected_curve(
        curve,
        curve_type=_curve_type_validation_target(
            curve_type=curve_type,
            expected_curve_type=expected_curve_type,
            validate_curve_type=validate_curve_type,
        ),
        source=source,
    )


def resolve_pricing_curve(
    *,
    index_uid: uuid.UUID | str | None = None,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    market_data_set: Any | None = None,
    curve_type: str = "discount",
    expected_curve_type: str | None = None,
    validate_curve_type: bool = True,
    role_key: str | None = None,
    selector_type: str | None = None,
    selector_key: str | None = None,
    quote_side: str | None = None,
    currency_code: str | None = None,
    source: str | None = None,
    curve_uid: uuid.UUID | str | None = None,
    curve_unique_identifier: str | None = None,
) -> ql.YieldTermStructureHandle:
    """Resolve and build a QuantLib curve from pricing MetaTables and curve data."""

    curve = select_curve(
        index_uid=index_uid,
        curve_type=curve_type,
        expected_curve_type=expected_curve_type,
        validate_curve_type=validate_curve_type,
        market_data_set=market_data_set,
        role_key=role_key,
        selector_type=selector_type,
        selector_key=selector_key,
        quote_side=quote_side,
        currency_code=currency_code,
        source=source,
        curve_uid=curve_uid,
        curve_unique_identifier=curve_unique_identifier,
    )
    return build_curve_from_curve_row(
        curve=curve,
        valuation_date=valuation_date,
        market_data_set=market_data_set,
    )


def resolve_curve_for_index_binding(
    *,
    index_uid: uuid.UUID | str,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    market_data_set: Any | None = None,
    role_key: str,
    quote_side: str | None = None,
    curve_uid: uuid.UUID | str | None = None,
    curve_unique_identifier: str | None = None,
    expected_curve_type: str | None = None,
    source: str | None = None,
) -> ql.YieldTermStructureHandle:
    """Resolve a curve directly from an index-scoped market-data curve binding."""

    selection = CurveSelectionContext.for_index(
        index_uid=index_uid,
        role_key=role_key,
        market_data_set=market_data_set,
        quote_side=quote_side,
        curve_uid=curve_uid,
        curve_unique_identifier=curve_unique_identifier,
        expected_curve_type=expected_curve_type,
        source=source,
    )
    return resolve_pricing_curve(
        index_uid=index_uid,
        valuation_date=valuation_date,
        market_data_set=market_data_set,
        curve_type=expected_curve_type or selection.role_key,
        expected_curve_type=expected_curve_type,
        validate_curve_type=expected_curve_type is not None,
        role_key=selection.role_key,
        quote_side=selection.quote_side,
        source=source,
        curve_uid=curve_uid,
        curve_unique_identifier=curve_unique_identifier,
    )


def build_curve_from_curve_row(
    *,
    curve: Curve,
    building_details: CurveBuildingDetails | None = None,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    market_data_set: Any | None = None,
) -> ql.YieldTermStructureHandle:
    """Build a QuantLib discount curve from a curve row and curve-owned build details."""

    target_date = _ensure_datetime(valuation_date)
    nodes, effective_curve_date = data_interface.get_historical_discount_curve(
        curve.unique_identifier,
        target_date,
        market_data_set=market_data_set,
    )
    if building_details is None:
        building_details = resolve_curve_building_details(curve.uid)

    _validate_supported_curve_build(curve=curve, building_details=building_details)

    base_dt = _ensure_datetime(effective_curve_date)
    base = to_ql_date(base_dt)
    day_counter = daycount_from_json(building_details.day_counter_code)
    calendar = _calendar_from_code(building_details.calendar_code)

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
        quote = _curve_node_quote(node, building_details=building_details)
        tenor = day_counter.yearFraction(base, ql_date)
        discounts.append(
            _discount_from_quote(
                quote=quote,
                tenor=tenor,
                building_details=building_details,
            )
        )
        dates.append(ql_date)

    term_structure = ql.DiscountCurve(dates, discounts, day_counter, calendar)
    if _extrapolation_enabled(building_details.extrapolation_policy):
        term_structure.enableExtrapolation()
    return ql.YieldTermStructureHandle(term_structure)


def resolve_quantlib_index(
    index_uid: uuid.UUID | str,
    *,
    valuation_date: datetime.date | datetime.datetime | ql.Date,
    market_data_set: Any | None = None,
    forwarding_curve: ql.YieldTermStructureHandle | ql.YieldTermStructure | None = None,
    hydrate_fixings: bool = True,
    settlement_days: int | None = None,
    curve_type: str = "discount",
    role_key: str | None = None,
    quote_side: str | None = None,
    source: str | None = None,
    curve_uid: uuid.UUID | str | None = None,
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
        selection_role = role_key or _default_index_curve_role(curve_type)
        curve = resolve_pricing_curve(
            index_uid=index_uid,
            valuation_date=valuation_date,
            market_data_set=market_data_set,
            curve_type=selection_role,
            role_key=selection_role,
            quote_side=quote_side,
            source=source,
            curve_uid=curve_uid,
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
            market_data_set=market_data_set,
        )

    return ql_index


def add_historical_fixings(
    target_date: ql.Date | datetime.date | datetime.datetime,
    ibor_index: ql.IborIndex,
    reference_rate_uid: str,
    *,
    market_data_set: Any | None = None,
) -> None:
    """Hydrate a QuantLib index from the configured pricing fixings DataNode."""

    end_date = _ensure_datetime(target_date)
    start_date = end_date - datetime.timedelta(days=365)
    historical_fixings = data_interface.get_historical_fixings(
        reference_rate_uid,
        start_date,
        end_date,
        market_data_set=market_data_set,
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


def _validate_selected_curve(
    curve: Curve,
    *,
    curve_type: str | None,
    source: str | None,
) -> Curve:
    if curve_type and curve.curve_type != curve_type:
        raise ValueError(
            f"Curve {curve.unique_identifier!r} has curve_type={curve.curve_type!r}, "
            f"not {curve_type!r}."
        )
    if source and curve.source != source:
        raise ValueError(
            f"Curve {curve.unique_identifier!r} has source={curve.source!r}, not {source!r}."
        )
    return curve


def _curve_type_validation_target(
    *,
    curve_type: str | None,
    expected_curve_type: str | None,
    validate_curve_type: bool,
) -> str | None:
    if expected_curve_type is not None:
        return expected_curve_type
    if validate_curve_type:
        return curve_type
    return None


def _curve_binding_selector(
    *,
    index_uid: uuid.UUID | str | None,
    curve_type: str,
    role_key: str | None,
    selector_type: str | None,
    selector_key: str | None,
    currency_code: str | None,
) -> tuple[str, str, str]:
    role = role_key or curve_type
    if selector_type is not None or selector_key is not None:
        if selector_type is None or selector_key is None:
            raise ValueError("selector_type and selector_key must be passed together.")
        return role, selector_type, selector_key
    if currency_code:
        return role, "currency", currency_code
    if index_uid is not None:
        return role, "index", str(_coerce_uuid(index_uid, field_name="index_uid"))
    raise ValueError(
        "Curve resolution requires curve_uid, curve_unique_identifier, or a "
        "market-data-set curve binding selector."
    )


def _default_index_curve_role(curve_type: str) -> str:
    if curve_type == "discount":
        return "projection"
    return curve_type


def _validate_supported_curve_build(
    *,
    curve: Curve,
    building_details: CurveBuildingDetails,
) -> None:
    builder_type = building_details.builder_type.lower()
    quote_convention = building_details.quote_convention.lower()
    if builder_type != "zero_rate_curve":
        raise NotImplementedError(
            f"Curve {curve.unique_identifier!r} uses unsupported builder_type="
            f"{building_details.builder_type!r}."
        )
    if quote_convention not in {"zero_rate", "zero"}:
        raise NotImplementedError(
            f"Curve {curve.unique_identifier!r} uses unsupported quote_convention="
            f"{building_details.quote_convention!r}."
        )


def _curve_node_quote(
    node: dict[str, Any],
    *,
    building_details: CurveBuildingDetails,
) -> float:
    quote_convention = building_details.quote_convention.lower()
    if quote_convention in {"zero_rate", "zero"}:
        value = node.get("zero", node.get("zero_rate", node.get("rate")))
    else:
        value = None
    if value is None:
        raise ValueError(
            "Curve observation node is missing the quote required by "
            f"quote_convention={building_details.quote_convention!r}."
        )
    quote = float(value)
    if building_details.rate_unit.lower() in {"percent", "percentage"}:
        quote *= 0.01
    elif building_details.rate_unit.lower() == "decimal":
        pass
    elif abs(quote) > 1.0:
        quote *= 0.01
    return quote


def _discount_from_quote(
    *,
    quote: float,
    tenor: float,
    building_details: CurveBuildingDetails,
) -> float:
    compounding = building_details.compounding.lower()
    if compounding in {"continuous", "continuous_compounding"}:
        return math.exp(-quote * tenor)
    if compounding in {"compounded", "compounded_annual", "annual"}:
        return 1.0 / ((1.0 + quote) ** tenor)
    return 1.0 / (1.0 + quote * tenor)


def _extrapolation_enabled(policy: str) -> bool:
    return policy.lower() in {"enabled", "enable", "true", "yes", "on"}


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


def _calendar_from_code(value: str) -> ql.Calendar:
    return _calendar_from_convention({"calendar_code": value})


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
    code = str(_convention_value(convention_dump, "currency_code", "currency") or "").upper()
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
    "CurveSelectionContext",
    "resolve_curve_building_details",
    "resolve_curve_for_index_binding",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "normalize_curve_quote_side",
    "select_curve",
]
