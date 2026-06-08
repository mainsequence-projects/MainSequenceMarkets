from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary, build_paginated_response
from apps.v1.schemas.virtual_funds import (
    VirtualFundDetailResponse,
    VirtualFundHoldingsSnapshotResponse,
    VirtualFundListResponse,
)
from apps.v1.services.virtual_funds import (
    get_virtual_fund_detail,
    get_virtual_fund_holdings,
    get_virtual_fund_summary,
    list_virtual_funds,
)

router = APIRouter(prefix="/virtualfund", tags=["virtualfund"])


@router.get(
    "/",
    response_model=VirtualFundListResponse,
    summary="List virtual funds",
    description=(
        "Return core library virtual-fund rows in the reusable limit-offset "
        "pagination envelope. `portfolio_uid` filters VirtualFund.target_portfolio_uid."
    ),
    operation_id="listVirtualFunds",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid virtual-fund list request.",
        }
    },
)
def get_virtual_funds(
    request: Request,
    response_format: Annotated[
        str,
        Query(description="Supported value for this endpoint is `frontend_list`."),
    ] = "frontend_list",
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across virtual-fund uid, unique identifier, "
                "account uid, and target portfolio uid."
            ),
        ),
    ] = "",
    account_uid: Annotated[
        str | None,
        Query(description="Optional exact Account uid filter."),
    ] = None,
    portfolio_uid: Annotated[
        str | None,
        Query(description="Optional exact Portfolio uid filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of virtual-fund rows to return."),
    ] = 25,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered virtual-fund list."),
    ] = 0,
) -> VirtualFundListResponse:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only response_format=frontend_list is implemented for "
                "GET /api/v1/virtualfund/."
            ),
        )
    try:
        response = VirtualFundListResponse.model_validate(
            list_virtual_funds(
                search=search,
                account_uid=account_uid,
                portfolio_uid=portfolio_uid,
                limit=limit,
                offset=offset,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return VirtualFundListResponse.model_validate(
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
    summary="Get virtual fund summary",
    description="Return the reusable frontend detail summary payload for one virtual fund.",
    operation_id="getVirtualFundSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested virtual-fund uid was not found.",
        }
    },
)
def get_virtual_fund_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_virtual_fund_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Virtual fund {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/holdings/",
    response_model=VirtualFundHoldingsSnapshotResponse,
    summary="Get virtual fund holdings snapshot",
    description=(
        "Return one virtual-fund holdings snapshot. When the virtual fund exists "
        "but no holdings snapshot matches the request, the response is 200 with "
        "an empty holdings list."
    ),
    operation_id="getVirtualFundHoldings",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid virtual-fund holdings request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested virtual-fund uid was not found.",
        },
    },
)
def get_virtual_fund_holdings_by_uid(
    uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Snapshot ordering used when holdings_date is omitted."),
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
                "AssetSnapshotsStorage name/ticker labels for holdings rows."
            ),
        ),
    ] = True,
    holdings_date: Annotated[
        dt.datetime | None,
        Query(description="Exact virtual-fund holdings timestamp to fetch. Use ISO 8601."),
    ] = None,
) -> VirtualFundHoldingsSnapshotResponse:
    try:
        snapshot = get_virtual_fund_holdings(
            uid=uid,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
            holdings_date=holdings_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Virtual fund {uid!r} was not found.")
    return snapshot


@router.get(
    "/{uid}/",
    response_model=VirtualFundDetailResponse,
    summary="Get virtual fund",
    description=(
        "Return one virtual-fund detail payload containing the core virtual-fund "
        "row, tab definitions, and route links."
    ),
    operation_id="getVirtualFund",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested virtual-fund uid was not found.",
        }
    },
)
def get_virtual_fund_by_uid(uid: str) -> VirtualFundDetailResponse:
    detail = get_virtual_fund_detail(uid=uid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Virtual fund {uid!r} was not found.")
    return detail
