from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from apps.v1.schemas.command_center import TabularFrameResponse
from apps.v1.schemas.common import ErrorResponse
from apps.v1.schemas.pricing_assets import (
    AssetPricingOperationRequest,
    BondAnalyticsResponse,
    BondCarryRollDownResponse,
    BondCashflowsResponse,
    BondCurvePreviewResponse,
    BondDurationResponse,
    BondFixingsAvailabilityResponse,
    BondNetCashflowsResponse,
    BondPriceResponse,
    BondYieldResponse,
    BondZSpreadResponse,
)
from apps.v1.services.pricing_assets import (
    execute_pricing_asset_cashflows_frame,
    execute_pricing_asset_net_cashflows_frame,
    execute_pricing_asset_operation,
)

router = APIRouter(prefix="/pricing/assets", tags=["pricing-asset"])


def _execute(
    asset_uid: str, operation: str, payload: AssetPricingOperationRequest
) -> dict[str, Any]:
    try:
        return execute_pricing_asset_operation(
            asset_uid=asset_uid,
            operation=operation,
            valuation_date=payload.valuation_date,
            market_data_set=payload.market_data_set,
            parameters=payload.parameters,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _raise_pricing_http_exception(exc)
        raise


def _raise_pricing_http_exception(exc: Exception) -> None:
    from msm_pricing.api import (
        AssetPricingDependencyError,
        AssetPricingNotFoundError,
        UnsupportedAssetPricingOperationError,
    )

    if isinstance(exc, AssetPricingNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, UnsupportedAssetPricingOperationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, AssetPricingDependencyError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{asset_uid}/price/",
    response_model=BondPriceResponse,
    summary="Price fixed income asset",
    description="Load the asset instrument and return `instrument.price(...)`.",
    operation_id="priceFixedIncomeAsset",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def price_fixed_income_asset(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondPriceResponse:
    return BondPriceResponse.model_validate(_execute(asset_uid, "price", payload))


@router.post(
    "/{asset_uid}/analytics/",
    response_model=BondAnalyticsResponse,
    summary="Get fixed income asset analytics",
    description="Load the asset instrument and return `instrument.analytics(...)`.",
    operation_id="getFixedIncomeAssetAnalytics",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_analytics(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondAnalyticsResponse:
    return BondAnalyticsResponse.model_validate(_execute(asset_uid, "analytics", payload))


@router.post(
    "/{asset_uid}/duration/",
    response_model=BondDurationResponse,
    summary="Get fixed income asset duration",
    description="Load the asset instrument and return `instrument.duration(...)`.",
    operation_id="getFixedIncomeAssetDuration",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_duration(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondDurationResponse:
    return BondDurationResponse.model_validate(_execute(asset_uid, "duration", payload))


@router.post(
    "/{asset_uid}/yield/",
    response_model=BondYieldResponse,
    summary="Get fixed income asset yield",
    description="Load the asset instrument and return `instrument.get_yield(...)`.",
    operation_id="getFixedIncomeAssetYield",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_yield(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondYieldResponse:
    return BondYieldResponse.model_validate(_execute(asset_uid, "yield", payload))


@router.post(
    "/{asset_uid}/z-spread/",
    response_model=BondZSpreadResponse,
    summary="Get fixed income asset z-spread",
    description="Load the asset instrument and return `instrument.z_spread(...)`.",
    operation_id="getFixedIncomeAssetZSpread",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_z_spread(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondZSpreadResponse:
    return BondZSpreadResponse.model_validate(_execute(asset_uid, "z-spread", payload))


@router.post(
    "/{asset_uid}/cashflows/",
    response_model=BondCashflowsResponse,
    summary="Get fixed income asset cashflows",
    description="Load the asset instrument and return `instrument.get_cashflows(...)`.",
    operation_id="getFixedIncomeAssetCashflows",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_cashflows(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondCashflowsResponse:
    return BondCashflowsResponse.model_validate(_execute(asset_uid, "cashflows", payload))


@router.post(
    "/{asset_uid}/cashflows/frame/",
    response_model=TabularFrameResponse,
    summary="Get fixed income asset cashflows as a tabular frame",
    description=(
        "Load the asset instrument, run `instrument.get_cashflows(...)`, and return "
        "the result as the SDK `core.tabular_frame@v1` contract."
    ),
    operation_id="getFixedIncomeAssetCashflowsFrame",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    openapi_extra={
        "x-ui-contract": "core.tabular_frame@v1",
        "x-ui-output-root": "response:$",
    },
)
def get_fixed_income_asset_cashflows_frame(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> TabularFrameResponse:
    try:
        return execute_pricing_asset_cashflows_frame(
            asset_uid=asset_uid,
            valuation_date=payload.valuation_date,
            market_data_set=payload.market_data_set,
            parameters=payload.parameters,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _raise_pricing_http_exception(exc)
        raise


@router.post(
    "/{asset_uid}/net-cashflows/",
    response_model=BondNetCashflowsResponse,
    summary="Get fixed income asset net cashflows",
    description="Load the asset instrument and serialize `instrument.get_net_cashflows(...)`.",
    operation_id="getFixedIncomeAssetNetCashflows",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_net_cashflows(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondNetCashflowsResponse:
    return BondNetCashflowsResponse.model_validate(_execute(asset_uid, "net-cashflows", payload))


@router.post(
    "/{asset_uid}/net-cashflows/frame/",
    response_model=TabularFrameResponse,
    summary="Get fixed income asset net cashflows as a tabular frame",
    description=(
        "Load the asset instrument, run `instrument.get_net_cashflows(...)`, and return "
        "the result as the SDK `core.tabular_frame@v1` contract."
    ),
    operation_id="getFixedIncomeAssetNetCashflowsFrame",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    openapi_extra={
        "x-ui-contract": "core.tabular_frame@v1",
        "x-ui-output-root": "response:$",
    },
)
def get_fixed_income_asset_net_cashflows_frame(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> TabularFrameResponse:
    try:
        return execute_pricing_asset_net_cashflows_frame(
            asset_uid=asset_uid,
            valuation_date=payload.valuation_date,
            market_data_set=payload.market_data_set,
            parameters=payload.parameters,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _raise_pricing_http_exception(exc)
        raise


@router.post(
    "/{asset_uid}/carry-roll-down/",
    response_model=BondCarryRollDownResponse,
    summary="Get fixed income asset carry and roll-down",
    description="Load the asset instrument and return `instrument.carry_roll_down(...)`.",
    operation_id="getFixedIncomeAssetCarryRollDown",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_fixed_income_asset_carry_roll_down(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondCarryRollDownResponse:
    return BondCarryRollDownResponse.model_validate(_execute(asset_uid, "carry-roll-down", payload))


@router.post(
    "/{asset_uid}/curve-preview/",
    response_model=BondCurvePreviewResponse,
    summary="Preview fixed income asset curve context",
    description="Load the asset instrument and return method-backed curve diagnostics.",
    operation_id="previewFixedIncomeAssetCurve",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def preview_fixed_income_asset_curve(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondCurvePreviewResponse:
    return BondCurvePreviewResponse.model_validate(_execute(asset_uid, "curve-preview", payload))


@router.post(
    "/{asset_uid}/fixings-availability/",
    response_model=BondFixingsAvailabilityResponse,
    summary="Check fixed income asset fixings availability",
    description="Load the asset instrument and return method-backed fixings diagnostics.",
    operation_id="checkFixedIncomeAssetFixingsAvailability",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def check_fixed_income_asset_fixings_availability(
    asset_uid: str,
    payload: AssetPricingOperationRequest,
) -> BondFixingsAvailabilityResponse:
    return BondFixingsAvailabilityResponse.model_validate(
        _execute(asset_uid, "fixings-availability", payload)
    )
