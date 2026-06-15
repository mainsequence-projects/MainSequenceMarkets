from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from mainsequence.client.command_center.contracts.tabular import TabularFrameResponse

from apps.v1.schemas.assets import Asset, AssetCurrentPricingDetailsResponse, AssetDetailResponse
from apps.v1.schemas.common import (
    ErrorResponse,
    FrontEndDetailSummary,
    PaginatedResponse,
    build_paginated_response,
)
from apps.v1.services.assets import (
    delete_asset,
    get_asset,
    get_asset_monitor_frame,
    get_asset_pricing_details,
    get_asset_summary,
    list_assets,
)

router = APIRouter(prefix="/asset", tags=["asset"])


@router.get(
    "/",
    response_model=PaginatedResponse[Asset],
    summary="List assets",
    description=(
        "Return core library asset rows. The `response_format` query parameter is "
        "accepted for compatibility, but rows use the `msm.api.assets.Asset` contract."
    ),
    operation_id="listAssets",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        }
    },
)
def get_assets(
    request: Request,
    response_format: Annotated[
        str,
        Query(
            description="Supported value for this endpoint is `frontend_list`.",
        ),
    ] = "frontend_list",
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across asset identifiers and available detail fields.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of assets to return.",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered asset list.",
        ),
    ] = 0,
    categories__uid: Annotated[
        str | None,
        Query(
            description="Optional asset category uid filter used by nested category asset tables.",
        ),
    ] = None,
) -> PaginatedResponse[Asset]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/asset/.",
        )
    rows = list_assets(
        search=search,
        limit=limit + 1,
        offset=offset,
        category_uid=categories__uid,
    )
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/monitor/frame/",
    response_model=TabularFrameResponse,
    summary="Get asset monitor frame",
    description=(
        "Return a Command Center `core.tabular_frame@v1` payload for the "
        "ms-markets Asset Monitor / Asset Screener widget. The frame publishes "
        "`AssetTable.unique_identifier` as the ms-markets stable asset key without "
        "adding a synthetic `Symbol` column."
    ),
    operation_id="getAssetMonitorFrame",
    openapi_extra={
        "x-ui-contract": "core.tabular_frame@v1",
        "x-ui-output-root": "response:$",
    },
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid request boundary input.",
        }
    },
)
def get_asset_monitor_frame_route(
    request: Request,
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across asset identifiers and available ticker "
                "detail fields."
            ),
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of asset monitor rows to return.",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered asset monitor rows.",
        ),
    ] = 0,
    asset_type: Annotated[
        str | None,
        Query(
            description="Optional asset_type filter applied before frame construction.",
        ),
    ] = None,
    unique_identifiers: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional repeated unique_identifier filter. Use "
                "`?unique_identifiers=ASSET_A&unique_identifiers=ASSET_B` to scope the "
                "frame to selected assets."
            ),
        ),
    ] = None,
) -> TabularFrameResponse:
    return get_asset_monitor_frame(
        search=search,
        limit=limit,
        offset=offset,
        asset_type=asset_type,
        unique_identifiers=unique_identifiers,
        request_url=str(request.url),
    )


@router.get(
    "/{uid}/",
    response_model=AssetDetailResponse,
    summary="Get asset",
    description=(
        "Return one asset detail row by uid, including the latest "
        "AssetSnapshotsStorage row as `current_snapshot` when available."
    ),
    operation_id="getAsset",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested asset uid was not found.",
        },
    },
)
def get_asset_by_uid(
    uid: str,
    response_format: Annotated[
        str,
        Query(
            description="Supported value for this endpoint is `frontend_detail`.",
        ),
    ] = "frontend_detail",
) -> AssetDetailResponse:
    if response_format != "frontend_detail":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_detail is implemented for GET /api/v1/asset/{uid}/.",
        )
    record = get_asset(uid=uid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Asset {uid!r} was not found.")
    return record


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get asset summary",
    description=(
        "Return a reusable frontend detail summary payload for one asset. "
        "This contract is intended for detail-page summary cards."
    ),
    operation_id="getAssetSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested asset uid was not found.",
        }
    },
)
def get_asset_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_asset_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Asset {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/get_pricing_details/",
    response_model=AssetCurrentPricingDetailsResponse,
    summary="Get asset pricing details",
    description=(
        "Return the current pricing details row for one asset. "
        "The response mirrors `msm_pricing.api.AssetCurrentPricingDetails`."
    ),
    operation_id="getAssetPricingDetails",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No current pricing details row exists for the requested asset uid.",
        }
    },
)
def get_asset_pricing_details_by_uid(uid: str) -> AssetCurrentPricingDetailsResponse:
    details = get_asset_pricing_details(uid=uid)
    if details is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing details for asset {uid!r} were not found.",
        )
    return details


@router.delete(
    "/{uid}/",
    response_model=Asset | None,
    summary="Delete asset",
    description=(
        "Delete one asset identity row by uid. This route returns `null` on success. "
        "Related rows are governed by the backend table constraints."
    ),
    operation_id="deleteAsset",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested asset uid was not found.",
        }
    },
)
def remove_asset(uid: str) -> Asset | None:
    deleted = delete_asset(uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Asset {uid!r} was not found.")
    return None
