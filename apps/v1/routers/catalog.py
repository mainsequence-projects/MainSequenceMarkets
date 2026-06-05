from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from apps.v1.schemas.catalog import (
    CatalogDeleteResponse,
    CatalogListResponse,
    CatalogRowsResponse,
)
from apps.v1.schemas.common import ErrorResponse, build_paginated_response
from apps.v1.services.catalog import (
    CatalogNotFoundError,
    CatalogUnsupportedError,
    delete_catalog_row,
    list_catalog_rows,
    list_catalogs,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "/",
    response_model=CatalogListResponse,
    summary="List catalogues",
    description=(
        "Return catalogue entries from the markets MetaTable catalogue. "
        "The frontend should call this endpoint first, then use the returned "
        "row endpoints for a specific catalogue entry."
    ),
    operation_id="listCatalogues",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid catalog list request.",
        }
    },
)
def get_catalogues(
    request: Request,
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across catalogue identity and model fields.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of catalogue entries to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered catalogue list.",
        ),
    ] = 0,
) -> CatalogListResponse:
    response = CatalogListResponse.model_validate(
        list_catalogs(search=search, limit=limit, offset=offset)
    )
    return CatalogListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/{catalog_uid}/rows/",
    response_model=CatalogRowsResponse,
    summary="List catalogue rows",
    description=(
        "Return rows for one catalogue entry. The path parameter is the catalogue "
        "row uid returned by GET /api/v1/catalog/."
    ),
    operation_id="listCatalogueRows",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested catalogue entry was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "The requested catalogue entry cannot be resolved to a supported local model.",
        },
    },
)
def get_catalogue_rows(
    request: Request,
    catalog_uid: str,
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across row values.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of rows to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered row list.",
        ),
    ] = 0,
) -> CatalogRowsResponse:
    try:
        response = CatalogRowsResponse.model_validate(
            list_catalog_rows(
                catalog_uid=catalog_uid,
                search=search,
                limit=limit,
                offset=offset,
            )
        )
        page = build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        )
        return CatalogRowsResponse.model_validate(
            {
                "catalog": response.catalog,
                "columns": response.columns,
                **page.model_dump(),
            }
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogUnsupportedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/{catalog_uid}/rows/{uid}/",
    response_model=CatalogDeleteResponse,
    summary="Delete catalogue row",
    description=(
        "Delete one row from a catalogue-backed MetaTable. The deletion is scoped "
        "through the catalogue entry and relies on backend foreign-key cascade behavior."
    ),
    operation_id="deleteCatalogueRow",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested catalogue entry or row uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "The requested catalogue entry cannot be resolved to a supported local model.",
        },
    },
)
def remove_catalogue_row(catalog_uid: str, uid: str) -> CatalogDeleteResponse:
    try:
        response = CatalogDeleteResponse.model_validate(
            delete_catalog_row(catalog_uid=catalog_uid, uid=uid)
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogUnsupportedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if response.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Catalogue row {uid!r} was not found.")
    return response
