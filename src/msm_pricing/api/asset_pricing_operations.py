from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from msm.api.assets import Asset
from msm_pricing import Instrument
from msm_pricing.settings import PRICING_MARKET_DATA_SET_DEFAULT

SUPPORTED_BOND_INSTRUMENT_TYPES = frozenset(
    {
        "FixedRateBond",
        "CallableFixedRateBond",
        "AmortizingFixedRateBond",
        "ZeroCouponBond",
        "FloatingRateBond",
        "AmortizingFloatingRateBond",
    }
)


class AssetPricingOperationError(Exception):
    """Base error for asset pricing operation dispatch."""


class AssetPricingNotFoundError(AssetPricingOperationError):
    """Raised when the asset or pricing details cannot be loaded."""


class UnsupportedAssetPricingOperationError(AssetPricingOperationError):
    """Raised when an operation is not available for an instrument type."""


class AssetPricingDependencyError(AssetPricingOperationError):
    """Raised when pricing cannot run because market-data dependencies are missing."""


@dataclass(frozen=True)
class PricingOperationDefinition:
    key: str
    label: str
    response_model: str
    parameter_keys: frozenset[str]
    required_parameter_keys: frozenset[str]
    executor: Callable[[Any, str | None, dict[str, Any]], Any]
    requires_market_data_set: bool = True
    flat_outputs: tuple[str, ...] = ()
    response_mappings: tuple[dict[str, Any], ...] = ()
    frame_response_model: str | None = None


def build_asset_pricing_support(
    *,
    asset_uid: uuid.UUID | str,
    instrument_type: str,
) -> dict[str, Any]:
    """Return frontend discovery metadata for the current instrument type."""

    supported = instrument_type in SUPPORTED_BOND_INSTRUMENT_TYPES
    if not supported:
        return {
            "supported": False,
            "instrument_type": instrument_type,
            "operations": [],
            "reason": ("Instrument type is not registered for the fixed income pricer API."),
        }

    return {
        "supported": True,
        "instrument_type": instrument_type,
        "operations": [
            {
                "key": definition.key,
                "label": definition.label,
                "method": "POST",
                "url": f"/api/v1/pricing/assets/{asset_uid}/{definition.key}/",
                "requires_valuation_date": True,
                "supports_market_data_set": True,
                "requires_market_data_set": definition.requires_market_data_set,
                "request_model": "AssetPricingOperationRequest",
                "response_model": definition.response_model,
                "response_contract": "provider-native-json",
                "app_component": {
                    "output_root": "response:$",
                    "flat_outputs": list(definition.flat_outputs),
                },
                "parameters": [
                    {
                        "key": parameter_key,
                        "required": parameter_key in definition.required_parameter_keys,
                    }
                    for parameter_key in sorted(definition.parameter_keys)
                ],
                "response_mappings": list(definition.response_mappings),
                **(
                    {
                        "frame_url": f"/api/v1/pricing/assets/{asset_uid}/{definition.key}/frame/",
                        "frame_response_model": definition.frame_response_model,
                        "frame_response_contract": "core.tabular_frame@v1",
                    }
                    if definition.frame_response_model is not None
                    else {}
                ),
            }
            for definition in PRICING_OPERATION_DEFINITIONS.values()
        ],
    }


def execute_asset_pricing_operation(
    *,
    asset_uid: uuid.UUID | str,
    operation: str,
    valuation_date: dt.datetime,
    market_data_set: str | None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one registered operation by delegating to the instrument method."""

    definition = PRICING_OPERATION_DEFINITIONS.get(operation)
    if definition is None:
        raise UnsupportedAssetPricingOperationError(f"Unsupported pricing operation {operation!r}.")

    validated_parameters = _validate_parameters(
        operation=operation,
        definition=definition,
        parameters=parameters or {},
    )
    _validate_market_data_set(
        operation=operation,
        definition=definition,
        market_data_set=market_data_set,
    )

    asset = _load_asset(asset_uid)
    instrument = _load_instrument(asset)
    instrument_type = type(instrument).__name__
    if instrument_type not in SUPPORTED_BOND_INSTRUMENT_TYPES:
        raise UnsupportedAssetPricingOperationError(
            f"Instrument type {instrument_type!r} is not registered for the fixed income pricer API."
        )

    instrument.set_valuation_date(valuation_date)

    try:
        result = definition.executor(instrument, market_data_set, validated_parameters)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise AssetPricingDependencyError(str(exc)) from exc

    return _operation_payload(
        asset_uid=asset.uid,
        instrument_type=instrument_type,
        operation=operation,
        valuation_date=valuation_date,
        market_data_set=market_data_set,
        result=result,
        parameters=validated_parameters,
    )


def _load_asset(asset_uid: uuid.UUID | str) -> Asset:
    asset = Asset.get_by_uid(asset_uid)
    if asset is None:
        raise AssetPricingNotFoundError(f"Asset {asset_uid!r} was not found.")
    return asset


def _load_instrument(asset: Asset):
    try:
        return Instrument.load_from_asset(asset)
    except LookupError as exc:
        raise AssetPricingNotFoundError(str(exc)) from exc


def _validate_parameters(
    *,
    operation: str,
    definition: PricingOperationDefinition,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    unknown = sorted(set(parameters).difference(definition.parameter_keys))
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(f"Unsupported parameters for {operation}: {joined}.")

    missing = sorted(
        key
        for key in definition.required_parameter_keys
        if key not in parameters or parameters[key] is None
    )
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required parameters for {operation}: {joined}.")

    return {key: value for key, value in parameters.items() if value is not None}


def _validate_market_data_set(
    *,
    operation: str,
    definition: PricingOperationDefinition,
    market_data_set: str | None,
) -> None:
    if definition.requires_market_data_set and not str(market_data_set or "").strip():
        raise ValueError(f"market_data_set is required for {operation}.")


def _market_kwargs(market_data_set: str | None, parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "market_data_set": market_data_set,
        **dict(parameters),
    }


def _price(instrument: Any, market_data_set: str | None, parameters: dict[str, Any]) -> float:
    return instrument.price(**_market_kwargs(market_data_set, parameters))


def _analytics(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    return instrument.analytics(**_market_kwargs(market_data_set, parameters))


def _duration(instrument: Any, market_data_set: str | None, parameters: dict[str, Any]) -> float:
    resolved_parameters = dict(parameters)
    if "duration_type" in resolved_parameters:
        resolved_parameters["duration_type"] = _duration_type(resolved_parameters["duration_type"])
    return instrument.duration(**_market_kwargs(market_data_set, resolved_parameters))


def _yield(instrument: Any, market_data_set: str | None, parameters: dict[str, Any]) -> float:
    if market_data_set is not None:
        instrument.analytics(market_data_set=market_data_set)
    return instrument.get_yield(**parameters)


def _z_spread(instrument: Any, market_data_set: str | None, parameters: dict[str, Any]) -> float:
    return instrument.z_spread(**_market_kwargs(market_data_set, parameters))


def _cashflows(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    return instrument.get_cashflows(**_market_kwargs(market_data_set, parameters))


def _net_cashflows(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    net_cashflows = instrument.get_net_cashflows(**_market_kwargs(market_data_set, parameters))
    return _serialize_series_like(net_cashflows)


def _carry_roll_down(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    horizon_days = parameters["horizon_days"]
    clean = bool(parameters.get("clean", False))
    price_parameters = {
        key: parameters[key]
        for key in ("with_yield", "flat_compounding", "flat_frequency", "curve_quote_side")
        if key in parameters
    }
    instrument.price(**_market_kwargs(market_data_set, price_parameters))
    return instrument.carry_roll_down(horizon_days, clean=clean)


def _curve_preview(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    instrument.price(**_market_kwargs(market_data_set, parameters))
    curves, warnings = _instrument_curve_references(
        instrument=instrument,
        market_data_set=market_data_set,
        curve_quote_side=parameters.get("curve_quote_side"),
        benchmark_curve_quote_side=parameters.get("benchmark_curve_quote_side"),
    )
    return {
        "curves": curves,
        "diagnostics": {
            "pricing_engine_id": instrument.pricing_engine_id(),
            **({"curve_reference_warnings": warnings} if warnings else {}),
        },
    }


def _fixings_availability(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    del parameters
    fixings = [
        _fixing_availability_for_reference(
            index_uid=index_uid,
            valuation_date=instrument.valuation_date,
            market_data_set=market_data_set,
        )
        for index_uid in _instrument_fixing_reference_candidates(instrument)
    ]
    return {
        "status": _fixings_availability_status(fixings),
        "fixings": fixings,
    }


def _duration_type(value: Any) -> Any:
    if isinstance(value, str):
        import QuantLib as ql

        mapping = {
            "Simple": ql.Duration.Simple,
            "Macaulay": ql.Duration.Macaulay,
            "Modified": ql.Duration.Modified,
            "Effective": ql.Duration.Effective,
        }
        if value not in mapping:
            raise ValueError(f"Unsupported duration_type {value!r}.")
        return mapping[value]
    return value


def _serialize_series_like(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "items"):
        return [
            {
                "payment_date": _json_safe(index),
                "net_cashflow": _json_safe(net_cashflow),
            }
            for index, net_cashflow in value.items()
        ]
    if isinstance(value, list):
        return value
    return [{"payment_date": None, "net_cashflow": _json_safe(value)}]


def _operation_payload(
    *,
    asset_uid: uuid.UUID,
    instrument_type: str,
    operation: str,
    valuation_date: dt.datetime,
    market_data_set: str | None,
    result: Any,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "asset_uid": asset_uid,
        "instrument_type": instrument_type,
        "operation": operation,
        "valuation_date": valuation_date,
        "market_data_set": market_data_set,
    }

    if operation == "price":
        return {**base, "price": _json_safe(result), "units": "npv"}
    if operation == "analytics":
        return {**base, "analytics": _json_safe(result)}
    if operation == "duration":
        return {
            **base,
            "duration_type": str(parameters.get("duration_type", "Modified")),
            "duration": _json_safe(result),
        }
    if operation == "yield":
        return {**base, "yield_value": _json_safe(result)}
    if operation == "z-spread":
        return {
            **base,
            "target_dirty_ccy": _json_safe(parameters.get("target_dirty_ccy")),
            "z_spread": _json_safe(result),
            "units": "decimal",
        }
    if operation == "cashflows":
        return {**base, "legs": _json_safe(result)}
    if operation == "net-cashflows":
        return {**base, "cashflows": _json_safe(result)}
    if operation == "carry-roll-down":
        return {
            **base,
            "horizon_days": int(parameters["horizon_days"]),
            "metrics": _json_safe(result),
        }
    if operation == "curve-preview":
        preview = _json_safe(result)
        return {
            **base,
            "curves": preview.get("curves", []),
            "diagnostics": preview.get("diagnostics", {}),
        }
    if operation == "fixings-availability":
        return {**base, **_json_safe(result)}
    return {**base, "result": _json_safe(result)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _instrument_curve_references(
    *,
    instrument: Any,
    market_data_set: str | None,
    curve_quote_side: str | None = None,
    benchmark_curve_quote_side: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    warnings: list[str] = []

    for role, index_uid in _instrument_curve_reference_candidates(instrument):
        quote_side = benchmark_curve_quote_side if role == "z_spread_base" else curve_quote_side
        try:
            curve = _select_curve_for_reference(
                index_uid=index_uid,
                role_key=role,
                market_data_set=market_data_set,
                quote_side=quote_side,
            )
        except (LookupError, ValueError) as exc:
            warnings.append(f"{role}: {exc}")
            continue
        references.append(
            _curve_reference_payload(
                role=role,
                curve=curve,
                index_uid=index_uid,
                valuation_date=instrument.valuation_date,
                market_data_set=market_data_set,
                quote_side=quote_side,
            )
        )

    return references, warnings


def _instrument_curve_reference_candidates(instrument: Any) -> list[tuple[str, uuid.UUID]]:
    candidates: list[tuple[str, uuid.UUID]] = []
    seen: set[tuple[str, uuid.UUID]] = set()

    floating_rate_index_uid = getattr(instrument, "floating_rate_index_uid", None)
    if floating_rate_index_uid is not None:
        index_uid = uuid.UUID(str(floating_rate_index_uid))
        key = ("projection", index_uid)
        if key not in seen:
            candidates.append(("projection", index_uid))
            seen.add(key)

    benchmark_rate_index_uid = getattr(instrument, "benchmark_rate_index_uid", None)
    if benchmark_rate_index_uid is not None:
        index_uid = uuid.UUID(str(benchmark_rate_index_uid))
        key = ("z_spread_base", index_uid)
        if key not in seen:
            candidates.append(key)
            seen.add(key)

    return candidates


def _select_curve_for_reference(
    *,
    index_uid: uuid.UUID,
    role_key: str,
    market_data_set: str | None,
    quote_side: str | None = None,
):
    from msm_pricing.pricing_engine import select_curve

    expected_curve_type = role_key if role_key != "z_spread_base" else None
    return select_curve(
        index_uid=index_uid,
        curve_type=expected_curve_type or role_key,
        expected_curve_type=expected_curve_type,
        validate_curve_type=expected_curve_type is not None,
        market_data_set=market_data_set,
        role_key=role_key,
        quote_side=quote_side,
    )


def _curve_reference_payload(
    *,
    role: str,
    curve: Any,
    index_uid: uuid.UUID | None,
    valuation_date: dt.datetime | dt.date | None,
    market_data_set: str | None,
    quote_side: str | None,
) -> dict[str, Any]:
    query_params: dict[str, Any] = {
        "market_data_set": str(market_data_set or PRICING_MARKET_DATA_SET_DEFAULT),
    }
    if valuation_date is not None:
        query_params["valuation_date"] = valuation_date.isoformat()

    return {
        "role": role,
        "curve_uid": curve.uid,
        "curve_identifier": curve.unique_identifier,
        "curve_type": curve.curve_type,
        "index_uid": index_uid,
        "binding_quote_side": quote_side,
        "source": getattr(curve, "source", None),
        "discount_curve_url": f"/api/v1/pricing/curves/{curve.uid}/discount-curve/",
        "discount_curve_query_params": query_params,
    }


def _instrument_fixing_reference_candidates(instrument: Any) -> list[uuid.UUID]:
    candidates: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    for attribute in ("floating_rate_index_uid", "float_leg_index_uid"):
        value = getattr(instrument, attribute, None)
        if value is None:
            continue
        index_uid = uuid.UUID(str(value))
        if index_uid in seen:
            continue
        candidates.append(index_uid)
        seen.add(index_uid)

    return candidates


def _fixing_availability_for_reference(
    *,
    index_uid: uuid.UUID,
    valuation_date: dt.datetime | dt.date | None,
    market_data_set: str | None,
) -> dict[str, Any]:
    if valuation_date is None:
        raise ValueError("valuation_date is required for fixings availability.")

    index_identifier = _fixing_identifier_for_index(index_uid)
    required_start, required_end = _required_fixing_range(valuation_date)
    required_dates = set(
        _required_fixing_dates(
            index_uid=index_uid,
            required_start=required_start,
            required_end=required_end,
        )
    )
    observations = _index_fixing_observations(
        index_identifier=index_identifier,
        required_start=required_start,
        required_end=required_end,
        market_data_set=market_data_set,
    )
    available_dates = set(observations)
    missing_count = len(required_dates.difference(available_dates))

    return {
        "index_uid": index_uid,
        "index_identifier": index_identifier,
        "required_start_date": required_start.date(),
        "required_end_date": required_end.date(),
        "available_start_date": min(available_dates) if available_dates else None,
        "available_end_date": max(available_dates) if available_dates else None,
        "missing_count": missing_count,
        "status": _fixing_row_status(
            required_count=len(required_dates),
            available_count=len(available_dates),
            missing_count=missing_count,
        ),
    }


def _fixing_identifier_for_index(index_uid: uuid.UUID) -> str:
    from msm.api.indices import Index
    from msm_pricing.api.index_convention_details import IndexConventionDetails

    index = Index.get_by_uid(index_uid)
    if index is None:
        raise LookupError(f"No canonical index row found for index_uid={index_uid}.")

    convention = IndexConventionDetails.get_by_index_uid(index_uid)
    if convention is None:
        return index.unique_identifier

    convention_dump = convention.convention_dump
    return str(
        convention_dump.get("fixings_unique_identifier")
        or convention_dump.get("fixings_uid")
        or index.unique_identifier
    )


def _required_fixing_range(
    valuation_date: dt.datetime | dt.date,
) -> tuple[dt.datetime, dt.datetime]:
    required_end = _ensure_datetime(valuation_date)
    required_start = required_end - dt.timedelta(days=365)
    return required_start, required_end


def _required_fixing_dates(
    *,
    index_uid: uuid.UUID,
    required_start: dt.datetime,
    required_end: dt.datetime,
) -> list[dt.date]:
    ql_index = _resolve_index_for_fixing_dates(
        index_uid=index_uid,
        valuation_date=required_end,
    )
    dates: list[dt.date] = []
    current = required_start.date()
    end = required_end.date()
    while current <= end:
        if ql_index.isValidFixingDate(_to_ql_date(current)):
            dates.append(current)
        current += dt.timedelta(days=1)
    return dates


def _resolve_index_for_fixing_dates(*, index_uid: uuid.UUID, valuation_date: dt.datetime):
    import QuantLib as ql

    from msm_pricing.pricing_engine.resolvers import resolve_quantlib_index

    valuation_day = _to_ql_date(valuation_date.date())
    flat_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(valuation_day, 0.0, ql.Actual365Fixed())
    )
    return resolve_quantlib_index(
        index_uid=index_uid,
        valuation_date=valuation_date,
        forwarding_curve=flat_curve,
        hydrate_fixings=False,
    )


def _to_ql_date(value: dt.date):
    from msm_pricing.utils import to_ql_date

    return to_ql_date(value)


def _index_fixing_observations(
    *,
    index_identifier: str,
    required_start: dt.datetime,
    required_end: dt.datetime,
    market_data_set: str | None,
) -> dict[dt.date, float]:
    from msm_pricing.data_interface import data_interface

    return data_interface.get_index_fixing_observations(
        index_identifier,
        required_start,
        required_end,
        market_data_set=market_data_set,
    )


def _ensure_datetime(value: dt.datetime | dt.date) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.combine(value, dt.time())


def _fixing_row_status(
    *,
    required_count: int,
    available_count: int,
    missing_count: int,
) -> str:
    if required_count == 0:
        return "complete"
    if available_count == 0:
        return "missing"
    if missing_count == 0:
        return "complete"
    return "partial"


def _fixings_availability_status(fixings: list[dict[str, Any]]) -> str:
    if not fixings:
        return "not_required"
    statuses = {str(row["status"]) for row in fixings}
    if statuses == {"complete"}:
        return "complete"
    if "missing" in statuses:
        return "missing"
    return "partial"


PRICING_OPERATION_DEFINITIONS = {
    "price": PricingOperationDefinition(
        key="price",
        label="Price",
        response_model="BondPriceResponse",
        parameter_keys=frozenset(
            {"with_yield", "flat_compounding", "flat_frequency", "curve_quote_side"}
        ),
        required_parameter_keys=frozenset(),
        executor=_price,
        flat_outputs=("price", "units"),
    ),
    "analytics": PricingOperationDefinition(
        key="analytics",
        label="Analytics",
        response_model="BondAnalyticsResponse",
        parameter_keys=frozenset(
            {"with_yield", "flat_compounding", "flat_frequency", "curve_quote_side"}
        ),
        required_parameter_keys=frozenset(),
        executor=_analytics,
        flat_outputs=(
            "analytics.clean_price",
            "analytics.dirty_price",
            "analytics.accrued_amount",
        ),
    ),
    "duration": PricingOperationDefinition(
        key="duration",
        label="Duration",
        response_model="BondDurationResponse",
        parameter_keys=frozenset(
            {
                "with_yield",
                "duration_type",
                "flat_compounding",
                "flat_frequency",
                "curve_quote_side",
            }
        ),
        required_parameter_keys=frozenset(),
        executor=_duration,
        flat_outputs=("duration", "duration_type"),
    ),
    "yield": PricingOperationDefinition(
        key="yield",
        label="Yield",
        response_model="BondYieldResponse",
        parameter_keys=frozenset({"override_clean_price"}),
        required_parameter_keys=frozenset(),
        executor=_yield,
        flat_outputs=("yield",),
    ),
    "z-spread": PricingOperationDefinition(
        key="z-spread",
        label="Z-Spread",
        response_model="BondZSpreadResponse",
        parameter_keys=frozenset(
            {
                "target_dirty_ccy",
                "use_quantlib",
                "tol",
                "max_iter",
                "curve_quote_side",
                "benchmark_curve_role_key",
                "benchmark_curve_quote_side",
                "benchmark_curve_uid",
                "benchmark_curve_unique_identifier",
                "benchmark_expected_curve_type",
            }
        ),
        required_parameter_keys=frozenset({"target_dirty_ccy"}),
        executor=_z_spread,
        flat_outputs=("z_spread", "target_dirty_ccy", "units"),
    ),
    "cashflows": PricingOperationDefinition(
        key="cashflows",
        label="Cashflows",
        response_model="BondCashflowsResponse",
        parameter_keys=frozenset({"curve_quote_side"}),
        required_parameter_keys=frozenset(),
        executor=_cashflows,
        flat_outputs=("legs",),
        response_mappings=(
            {
                "id": "cashflow_rows_by_leg",
                "label": "Cashflow rows by leg",
                "contract": "core.tabular_frame@v1",
                "statusCode": "200",
                "contentType": "application/json",
                "rowsPath": "$.legs.*[*]",
                "fieldTypes": {
                    "payment_date": "date",
                    "amount": "number",
                    "rate": "number",
                },
            },
        ),
        frame_response_model="TabularFrameResponse",
    ),
    "net-cashflows": PricingOperationDefinition(
        key="net-cashflows",
        label="Net Cashflows",
        response_model="BondNetCashflowsResponse",
        parameter_keys=frozenset({"curve_quote_side"}),
        required_parameter_keys=frozenset(),
        executor=_net_cashflows,
        flat_outputs=("cashflows",),
        response_mappings=(
            {
                "id": "net_cashflows",
                "label": "Net cashflows",
                "contract": "core.tabular_frame@v1",
                "statusCode": "200",
                "contentType": "application/json",
                "rowsPath": "$.cashflows",
                "fieldTypes": {
                    "payment_date": "date",
                    "net_cashflow": "number",
                },
            },
        ),
        frame_response_model="TabularFrameResponse",
    ),
    "carry-roll-down": PricingOperationDefinition(
        key="carry-roll-down",
        label="Carry/Roll-Down",
        response_model="BondCarryRollDownResponse",
        parameter_keys=frozenset(
            {
                "horizon_days",
                "clean",
                "with_yield",
                "flat_compounding",
                "flat_frequency",
                "curve_quote_side",
            }
        ),
        required_parameter_keys=frozenset({"horizon_days"}),
        executor=_carry_roll_down,
        flat_outputs=("horizon_days", "metrics"),
    ),
    "curve-preview": PricingOperationDefinition(
        key="curve-preview",
        label="Curve Preview",
        response_model="BondCurvePreviewResponse",
        parameter_keys=frozenset(
            {
                "with_yield",
                "flat_compounding",
                "flat_frequency",
                "curve_quote_side",
                "benchmark_curve_quote_side",
            }
        ),
        required_parameter_keys=frozenset(),
        executor=_curve_preview,
        flat_outputs=("curves", "diagnostics.pricing_engine_id"),
    ),
    "fixings-availability": PricingOperationDefinition(
        key="fixings-availability",
        label="Fixings Availability",
        response_model="BondFixingsAvailabilityResponse",
        parameter_keys=frozenset({"with_yield", "flat_compounding", "flat_frequency"}),
        required_parameter_keys=frozenset(),
        executor=_fixings_availability,
        flat_outputs=("status", "fixings"),
    ),
}


__all__ = [
    "AssetPricingDependencyError",
    "AssetPricingNotFoundError",
    "AssetPricingOperationError",
    "PricingOperationDefinition",
    "UnsupportedAssetPricingOperationError",
    "build_asset_pricing_support",
    "execute_asset_pricing_operation",
]
