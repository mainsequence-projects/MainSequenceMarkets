from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.v1.schemas.assets import Asset, AssetCurrentPricingDetailsResponse, AssetDetailResponse
from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary
from apps.v1.services.assets import (
    get_asset,
    get_asset_pricing_details,
    get_asset_summary,
    list_assets,
)

router = APIRouter(prefix="/asset", tags=["asset"])


@router.get(
    "/",
    response_model=list[Asset],
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
) -> list[Asset]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/asset/.",
        )
    return list_assets(
        search=search,
        limit=limit,
        offset=offset,
        category_uid=categories__uid,
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
