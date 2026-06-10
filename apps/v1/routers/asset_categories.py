from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Request, status

from apps.v1.schemas.asset_categories import (
    AssetCategory,
    AssetCategoryDetailResponse,
    BulkDeleteAssetCategoriesRequest,
    BulkDeleteAssetCategoriesResponse,
    CreateAssetCategoryRequest,
    PatchAssetCategoryRequest,
)
from apps.v1.schemas.common import ErrorResponse, PaginatedResponse, build_paginated_response
from apps.v1.services.asset_categories import (
    bulk_delete_asset_categories,
    create_asset_category,
    delete_asset_category,
    get_asset_category_detail,
    list_asset_categories,
    update_asset_category,
)

router = APIRouter(prefix="/asset-category", tags=["asset-category"])


@router.get(
    "/",
    response_model=PaginatedResponse[AssetCategory],
    summary="List asset categories",
    description=(
        "Return core library asset category rows. The `response_format` query "
        "parameter is accepted for compatibility, but rows use the "
        "`msm.api.assets.AssetCategory` contract."
    ),
    operation_id="listAssetCategories",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        }
    },
)
def get_asset_categories(
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
            description="Case-insensitive search across category uid, unique identifier, display name, and description.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of category rows to scan and return.",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered category list.",
        ),
    ] = 0,
) -> PaginatedResponse[AssetCategory]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/asset-category/.",
        )
    rows = list_asset_categories(search=search, limit=limit + 1, offset=offset)
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    response_model=AssetCategory,
    summary="Create asset category",
    description="Create an asset category and optionally replace its asset membership set.",
    operation_id="createAssetCategory",
)
def post_asset_category(
    request: Annotated[
        CreateAssetCategoryRequest,
        Body(description="Create payload for a new asset category."),
    ],
) -> AssetCategory:
    return create_asset_category(payload=request.model_dump(exclude_none=True))


@router.post(
    "/bulk-delete/",
    response_model=BulkDeleteAssetCategoriesResponse,
    summary="Bulk delete asset categories",
    description=(
        "Delete asset categories by explicit uid selection or, when `select_all=true`, "
        "by the compatibility filter set from the current list view."
    ),
    operation_id="bulkDeleteAssetCategories",
)
def post_asset_category_bulk_delete(
    request: Annotated[
        BulkDeleteAssetCategoriesRequest,
        Body(description="Bulk delete request for asset categories."),
    ],
) -> BulkDeleteAssetCategoriesResponse:
    return bulk_delete_asset_categories(
        payload=request.model_dump(by_alias=False, exclude_none=True)
    )


@router.get(
    "/{uid}/",
    response_model=AssetCategoryDetailResponse,
    summary="Get asset category detail",
    description=(
        "Return one asset category detail payload, including membership-backed "
        "asset count and the filtered asset-list configuration for the category."
    ),
    operation_id="getAssetCategoryDetail",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested asset category uid was not found.",
        },
    },
)
def get_asset_category(
    uid: str,
    response_format: Annotated[
        str,
        Query(
            description="Supported value for this endpoint is `frontend_detail`.",
        ),
    ] = "frontend_detail",
) -> AssetCategoryDetailResponse:
    if response_format != "frontend_detail":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_detail is implemented for GET /api/v1/asset-category/{uid}/.",
        )
    payload = get_asset_category_detail(uid=uid)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Asset category {uid!r} was not found.")
    return payload


@router.patch(
    "/{uid}/",
    response_model=AssetCategory,
    summary="Update asset category",
    description="Update one asset category and optionally replace its membership set.",
    operation_id="updateAssetCategory",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested asset category uid was not found.",
        }
    },
)
def patch_asset_category(
    uid: str,
    request: Annotated[
        PatchAssetCategoryRequest,
        Body(description="Patch payload for an existing asset category."),
    ],
) -> AssetCategory:
    payload = request.model_dump(exclude_unset=True, exclude_none=False)
    record = update_asset_category(uid=uid, payload=payload)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Asset category {uid!r} was not found.")
    return record


@router.delete(
    "/{uid}/",
    response_model=AssetCategory | None,
    summary="Delete asset category",
    description="Delete one asset category. The migrated API returns `null` on success.",
    operation_id="deleteAssetCategory",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested asset category uid was not found.",
        }
    },
)
def remove_asset_category(uid: str) -> AssetCategory | None:
    deleted = delete_asset_category(uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Asset category {uid!r} was not found.")
    return None
