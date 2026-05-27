from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from apps.v1.schemas.common import ErrorResponse
from apps.v1.schemas.assets import AssetListRow
from apps.v1.services.assets import list_assets

router = APIRouter(prefix="/asset", tags=["asset"])


@router.get(
    "/",
    response_model=list[AssetListRow],
    summary="List assets",
    description=(
        "Return asset catalog rows in the legacy-compatible `frontend_list` shape. "
        "This endpoint currently supports only `response_format=frontend_list`."
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
) -> list[AssetListRow]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/asset/.",
        )
    return list_assets(search=search, limit=limit, offset=offset)
