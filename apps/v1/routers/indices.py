from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from apps.v1.schemas.common import ErrorResponse
from apps.v1.schemas.indices import IndexListRow, IndexRecord
from apps.v1.services.indices import delete_index, get_index, list_indices

router = APIRouter(prefix="/index", tags=["index"])


@router.get(
    "/",
    response_model=list[IndexListRow],
    summary="List indexes",
    description=(
        "Return index registry rows in the same simple frontend list shape used "
        "for the migrated asset catalog route."
    ),
    operation_id="listIndexes",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid request boundary input.",
        }
    },
)
def get_indexes(
    response_format: Annotated[
        str,
        Query(
            description="Supported value for this endpoint is `frontend_list`.",
        ),
    ] = "frontend_list",
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across index uid, unique identifier, display name, description, and provider.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of index rows to return.",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered index list.",
        ),
    ] = 0,
) -> list[IndexListRow]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail="Only response_format=frontend_list is implemented for GET /api/v1/index/.",
        )
    return list_indices(search=search, limit=limit, offset=offset)


@router.get(
    "/{uid}/",
    response_model=IndexRecord,
    summary="Get index",
    description="Return one index registry record by uid.",
    operation_id="getIndex",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested index uid was not found.",
        }
    },
)
def get_index_by_uid(uid: str) -> IndexRecord:
    record = get_index(uid=uid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return record


@router.delete(
    "/{uid}/",
    response_model=IndexRecord | None,
    summary="Delete index",
    description="Delete one index registry record. This route returns `null` on success.",
    operation_id="deleteIndex",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested index uid was not found.",
        }
    },
)
def remove_index(uid: str) -> IndexRecord | None:
    deleted = delete_index(uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return None
