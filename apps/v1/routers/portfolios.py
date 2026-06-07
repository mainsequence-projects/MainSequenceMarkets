from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary, build_paginated_response
from apps.v1.schemas.portfolios import (
    PortfolioBulkDeleteResponse,
    PortfolioDeleteRequest,
    PortfolioDeleteResponse,
    PortfolioDetailResponse,
    PortfolioListResponse,
    PortfolioWeightsSnapshotResponse,
)
from apps.v1.services.portfolios import (
    bulk_delete_portfolios,
    delete_portfolio,
    get_portfolio_detail,
    get_portfolio_summary,
    get_portfolio_weights,
    list_portfolios,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get(
    "/",
    response_model=PortfolioListResponse,
    summary="List portfolios",
    description=(
        "Return core library portfolio rows in the reusable limit-offset pagination "
        "envelope. The `response_format` query parameter is accepted for frontend "
        "compatibility, but rows use the `msm.api.portfolios.Portfolio` contract."
    ),
    operation_id="listPortfolios",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid portfolio list request.",
        }
    },
)
def get_portfolios(
    request: Request,
    response_format: Annotated[
        str,
        Query(description="Supported value for this endpoint is `frontend_list`."),
    ] = "frontend_list",
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across portfolio uid, unique identifier, "
                "calendar, and portfolio index fields."
            ),
        ),
    ] = "",
    calendar_uid: Annotated[
        str | None,
        Query(description="Optional exact Calendar uid filter."),
    ] = None,
    calendar_name: Annotated[
        str | None,
        Query(description="Optional exact legacy calendar name filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of portfolio rows to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered portfolio list."),
    ] = 0,
) -> PortfolioListResponse:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/portfolio/.",
        )
    try:
        response = list_portfolios(
            search=search,
            calendar_uid=calendar_uid,
            calendar_name=calendar_name,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PortfolioListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response["results"],
            count=int(response["count"]),
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post(
    "/bulk-delete/",
    response_model=PortfolioBulkDeleteResponse,
    summary="Bulk delete portfolios",
    description=(
        "Delete multiple portfolio identity rows by uid. Rows referenced by protected "
        "tables are reported in `failed` and are not silently removed."
    ),
    operation_id="bulkDeletePortfolios",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio bulk-delete payload.",
        }
    },
)
def bulk_delete_portfolio_rows(
    payload: PortfolioDeleteRequest,
) -> PortfolioBulkDeleteResponse:
    try:
        return bulk_delete_portfolios(uids=payload.uids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get portfolio summary",
    description="Return the reusable frontend detail summary payload for one portfolio.",
    operation_id="getPortfolioSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        }
    },
)
def get_portfolio_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_portfolio_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/weights/",
    response_model=PortfolioWeightsSnapshotResponse,
    summary="Get portfolio weights snapshot",
    description=(
        "Return one portfolio weights snapshot. When `weights_date` is provided, "
        "the endpoint returns the exact timestamp snapshot. Otherwise it returns "
        "the latest or earliest snapshot according to `order`. Missing weight rows "
        "return 200 with an empty `weights` list when the portfolio exists."
    ),
    operation_id="getPortfolioWeights",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio weights request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
    },
)
def get_portfolio_weights_by_uid(
    uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Snapshot ordering used when weights_date is omitted."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1,
            description="Number of snapshots to return. The current contract returns one snapshot.",
        ),
    ] = 1,
    include_asset_detail: Annotated[
        bool,
        Query(
            description=(
                "When true, include asset.uid, asset.unique_identifier, and latest "
                "AssetSnapshotsStorage name/ticker labels for weight rows."
            ),
        ),
    ] = True,
    weights_date: Annotated[
        dt.datetime | None,
        Query(description="Exact portfolio weights timestamp to fetch. Use ISO 8601."),
    ] = None,
) -> PortfolioWeightsSnapshotResponse:
    try:
        snapshot = get_portfolio_weights(
            uid=uid,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
            weights_date=weights_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return snapshot


@router.get(
    "/{uid}/",
    response_model=PortfolioDetailResponse,
    summary="Get portfolio detail",
    description=(
        "Return one portfolio detail payload containing the core portfolio row, "
        "optional portfolio metadata, tab definitions, and route links."
    ),
    operation_id="getPortfolio",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        }
    },
)
def get_portfolio_by_uid(uid: str) -> PortfolioDetailResponse:
    detail = get_portfolio_detail(uid=uid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return detail


@router.delete(
    "/{uid}/",
    response_model=PortfolioDeleteResponse,
    summary="Delete portfolio",
    description=(
        "Delete one portfolio identity row. The route returns 409 when protected "
        "rows, such as account target-position history, still reference the portfolio."
    ),
    operation_id="deletePortfolio",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "The portfolio is referenced by protected rows.",
        },
    },
)
def remove_portfolio(uid: str) -> PortfolioDeleteResponse:
    try:
        response = delete_portfolio(uid=uid)
    except ValueError as exc:
        if exc.__class__.__name__ == "PortfolioDeleteConflictError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return response
