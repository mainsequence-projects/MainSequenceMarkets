from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary, build_paginated_response
from apps.v1.schemas.pricing_curves import CurveListResponse, DiscountCurveResponse
from apps.v1.services.pricing_curves import (
    get_pricing_curve_discount_curve,
    get_pricing_curve_summary,
    list_pricing_curves,
)

router = APIRouter(prefix="/pricing/curves", tags=["pricing-curve"])


@router.get(
    "/",
    response_model=CurveListResponse,
    summary="List pricing curves",
    description=(
        "Return paginated pricing curve registry rows from `msm_pricing.api.Curve`. "
        "These are curve identity rows, not timestamped curve observations."
    ),
    operation_id="listPricingCurves",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing curve list request.",
        }
    },
)
def get_pricing_curves(
    request: Request,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of pricing curve registry rows to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered curve list.",
        ),
    ] = 0,
    search: Annotated[
        str | None,
        Query(description="Optional contains search on curve unique_identifier."),
    ] = None,
    curve_type: Annotated[
        str | None,
        Query(description="Optional exact curve_type filter, such as discount or projection."),
    ] = None,
    index_uid: Annotated[
        str | None,
        Query(description="Optional exact index_uid filter."),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="Optional exact source filter."),
    ] = None,
) -> CurveListResponse:
    try:
        response = CurveListResponse.model_validate(
            list_pricing_curves(
                limit=limit,
                offset=offset,
                search=search,
                curve_type=curve_type,
                index_uid=index_uid,
                source=source,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CurveListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get pricing curve summary",
    description=(
        "Return the reusable frontend detail summary payload for one pricing curve "
        "registry row. This does not return timestamped curve observations."
    ),
    operation_id="getPricingCurveSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing curve uid was not found.",
        }
    },
)
def get_pricing_curve_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_pricing_curve_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Pricing curve {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/discount-curve/",
    response_model=DiscountCurveResponse,
    summary="Get pricing discount curve",
    description=(
        "Return discount-curve nodes for one pricing curve and pricing market-data set. "
        "When `valuation_date` is omitted, the latest available curve observation is returned."
    ),
    operation_id="getPricingDiscountCurve",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing curve or market-data set request.",
        },
        404: {
            "model": ErrorResponse,
            "description": (
                "The curve, market-data set, discount-curve binding, or requested "
                "curve observation was not found."
            ),
        },
    },
)
def get_pricing_discount_curve_by_uid(
    uid: str,
    market_data_set: Annotated[
        str,
        Query(
            description=(
                "Pricing market-data set selector. Accepts a set uid or set_key, "
                "such as `default`, `eod`, or `live`."
            ),
        ),
    ],
    valuation_date: Annotated[
        dt.datetime | None,
        Query(
            description=(
                "Optional valuation datetime. When omitted, the latest available "
                "discount-curve observation is returned."
            ),
        ),
    ] = None,
) -> DiscountCurveResponse:
    try:
        response = get_pricing_curve_discount_curve(
            uid=uid,
            market_data_set=market_data_set,
            valuation_date=valuation_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Pricing curve {uid!r} was not found.")
    return response
