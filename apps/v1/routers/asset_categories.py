from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Request, status

from apps.v1.schemas.asset_categories import (
    AssetCategory,
    AssetCategoryDetailResponse,
    BulkDeleteAssetCategoriesResponse,
    CreateAssetCategoryRequest,
    PatchAssetCategoryRequest,
)
from apps.v1.schemas.bulk_actions import (
    BulkActionDiscoveryResponse,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
)
from apps.v1.schemas.common import ErrorResponse, PaginatedResponse, build_paginated_response
from apps.v1.services.asset_categories import (
    bulk_delete_asset_categories,
    create_asset_category,
    delete_asset_category,
    get_asset_category_detail,
    list_asset_categories,
    preflight_bulk_delete_asset_categories,
    update_asset_category,
)
from apps.v1.services.bulk_actions import (
    blocked_preflight_detail,
    build_bulk_delete_discovery,
    explicit_uuid_selection,
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
    description="Execute the discovered explicit-selection asset-category delete action.",
    operation_id="bulkDeleteAssetCategories",
)
def post_asset_category_bulk_delete(
    request: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request."),
    ],
) -> BulkDeleteAssetCategoriesResponse:
    try:
        uids = explicit_uuid_selection(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preflight = BulkActionPreflightResponse.model_validate(
        preflight_bulk_delete_asset_categories(uids=uids)
    )
    if not preflight.allowed:
        raise HTTPException(status_code=409, detail=blocked_preflight_detail(preflight))
    return bulk_delete_asset_categories(payload={"uids": uids})


@router.get(
    "/bulk-actions/",
    response_model=BulkActionDiscoveryResponse,
    summary="Discover asset-category bulk actions",
    description=(
        "Return the caller-visible Command Center bulk actions for the asset-category "
        "collection. Only explicit UID selection is currently advertised."
    ),
    operation_id="listAssetCategoryBulkActions",
)
def get_asset_category_bulk_actions(
    search: Annotated[
        str,
        Query(description="Normalized collection search forwarded by the resource adapter."),
    ] = "",
) -> BulkActionDiscoveryResponse:
    return build_bulk_delete_discovery(
        action_id="bulk-delete-asset-categories",
        label="Delete selected",
        endpoint="/api/v1/asset-category/bulk-delete/",
        preflight_endpoint="/api/v1/asset-category/bulk-delete/preflight/",
        confirmation_title="Delete asset categories",
        confirmation_warning="Deleted asset categories cannot be restored.",
    )


@router.post(
    "/bulk-delete/preflight/",
    response_model=BulkActionPreflightResponse,
    summary="Preflight asset-category bulk deletion",
    description="Reauthorize and resolve an explicit category selection without deleting rows.",
    operation_id="preflightBulkDeleteAssetCategories",
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def preflight_asset_category_bulk_delete(
    request: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request to preflight."),
    ],
) -> BulkActionPreflightResponse:
    try:
        uids = explicit_uuid_selection(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkActionPreflightResponse.model_validate(
        preflight_bulk_delete_asset_categories(uids=uids)
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
