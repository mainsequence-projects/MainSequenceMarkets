from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from apps.v1.schemas.common import ErrorResponse, build_paginated_response
from apps.v1.schemas.pricing_curves import CurveListResponse
from apps.v1.services.pricing_curves import list_pricing_curves

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
