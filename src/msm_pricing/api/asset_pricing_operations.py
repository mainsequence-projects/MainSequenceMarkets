from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from msm.api.assets import Asset
from msm_pricing import Instrument

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

    asset = _load_asset(asset_uid)
    instrument = _load_instrument(asset)
    instrument_type = type(instrument).__name__
    if instrument_type not in SUPPORTED_BOND_INSTRUMENT_TYPES:
        raise UnsupportedAssetPricingOperationError(
            f"Instrument type {instrument_type!r} is not registered for the fixed income pricer API."
        )

    instrument.set_valuation_date(valuation_date)
    validated_parameters = _validate_parameters(
        operation=operation,
        definition=definition,
        parameters=parameters or {},
    )

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
    if market_data_set is not None:
        instrument.get_cashflows(market_data_set=market_data_set)
    net_cashflows = instrument.get_net_cashflows(**parameters)
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
        for key in ("with_yield", "flat_compounding", "flat_frequency")
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
    return {
        "pricing_engine_id": instrument.pricing_engine_id(),
    }


def _fixings_availability(
    instrument: Any,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> Mapping[str, Any]:
    instrument.price(**_market_kwargs(market_data_set, parameters))
    return {
        "status": "available",
        "fixings": [],
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
        return {**base, "curves": [], "diagnostics": _json_safe(result)}
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


PRICING_OPERATION_DEFINITIONS = {
    "price": PricingOperationDefinition(
        key="price",
        label="Price",
        response_model="BondPriceResponse",
        parameter_keys=frozenset({"with_yield", "flat_compounding", "flat_frequency"}),
        required_parameter_keys=frozenset(),
        executor=_price,
        flat_outputs=("price", "units"),
    ),
    "analytics": PricingOperationDefinition(
        key="analytics",
        label="Analytics",
        response_model="BondAnalyticsResponse",
        parameter_keys=frozenset({"with_yield", "flat_compounding", "flat_frequency"}),
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
            {"with_yield", "duration_type", "flat_compounding", "flat_frequency"}
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
        parameter_keys=frozenset({"target_dirty_ccy", "use_quantlib", "tol", "max_iter"}),
        required_parameter_keys=frozenset({"target_dirty_ccy"}),
        executor=_z_spread,
        flat_outputs=("z_spread", "target_dirty_ccy", "units"),
    ),
    "cashflows": PricingOperationDefinition(
        key="cashflows",
        label="Cashflows",
        response_model="BondCashflowsResponse",
        parameter_keys=frozenset(),
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
        parameter_keys=frozenset(),
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
            {"horizon_days", "clean", "with_yield", "flat_compounding", "flat_frequency"}
        ),
        required_parameter_keys=frozenset({"horizon_days"}),
        executor=_carry_roll_down,
        flat_outputs=("horizon_days", "metrics"),
    ),
    "curve-preview": PricingOperationDefinition(
        key="curve-preview",
        label="Curve Preview",
        response_model="BondCurvePreviewResponse",
        parameter_keys=frozenset({"with_yield", "flat_compounding", "flat_frequency"}),
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
