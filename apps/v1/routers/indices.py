from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from mainsequence.client.models_user import (
    User,
    _CURRENT_AUTH_HEADERS,
    _CURRENT_USER,
)

from apps.v1.schemas.command_center import TabularFrameResponse
from apps.v1.schemas.common import (
    ErrorResponse,
    FrontEndDetailSummary,
    PaginatedResponse,
    build_paginated_response,
)
from apps.v1.schemas.delete_impact import DeleteImpactResponse
from apps.v1.schemas.indices import (
    Index,
    IndexCreate,
    IndexDatasetDescriptor,
    IndexDatasetState,
    IndexDatasetSummary,
    IndexMethodologyDetail,
    IndexMethodologySummary,
    IndexRelatedMetaTable,
    IndexType,
    IndexUpdate,
)
from apps.v1.services.indices import (
    create_index,
    delete_index,
    get_index,
    get_index_dataset_summary,
    get_index_delete_impact,
    get_index_methodology,
    get_index_summary,
    get_index_type,
    get_index_values_frame,
    list_index_datasets,
    list_index_methodologies,
    list_index_related_meta_tables,
    list_index_types,
    list_indices,
    update_index,
)
from msm.services.indices import IndexActor, actor_from_user

router = APIRouter(prefix="/index", tags=["index"])
index_type_router = APIRouter(prefix="/index-type", tags=["index"])


def _request_actor(request: Request) -> IndexActor | None:
    headers = dict(request.headers)
    has_identity = any(key in headers for key in ("x-user-uid", "x-user-id", "authorization"))
    if not has_identity:
        return None
    headers_token = _CURRENT_AUTH_HEADERS.set(headers)
    user_token = _CURRENT_USER.set(None)
    try:
        return actor_from_user(User.get_logged_user())
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail=f"Authenticated user could not be resolved: {exc}"
        ) from exc
    finally:
        _CURRENT_USER.reset(user_token)
        _CURRENT_AUTH_HEADERS.reset(headers_token)


@index_type_router.get(
    "/",
    response_model=PaginatedResponse[IndexType],
    summary="List Index types",
    operation_id="listIndexTypes",
)
def get_index_types(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum rows per page.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Zero-based page offset.")] = 0,
) -> PaginatedResponse[IndexType]:
    count, rows = list_index_types(limit=limit, offset=offset)
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
        count=count,
    )


@index_type_router.get(
    "/{index_type}/",
    response_model=IndexType,
    summary="Get Index type",
    operation_id="getIndexType",
    responses={404: {"model": ErrorResponse}},
)
def get_index_type_by_key(index_type: str) -> IndexType:
    record = get_index_type(index_type=index_type)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Index type {index_type!r} was not found.")
    return record


@router.get(
    "/",
    response_model=PaginatedResponse[Index],
    summary="List indexes",
    operation_id="listIndexes",
    responses={400: {"model": ErrorResponse}},
)
def get_indexes(
    request: Request,
    response_format: Annotated[
        str, Query(description="Compatibility value; only frontend_list is accepted.")
    ] = "frontend_list",
    search: Annotated[str, Query(description="Case-insensitive Index catalog search.")] = "",
    index_type: Annotated[str | None, Query(description="Exact Index type filter.")] = None,
    provider: Annotated[str | None, Query(description="Exact provider filter.")] = None,
    has_definition: Annotated[
        bool | None, Query(description="Filter by presence of core methodology definitions.")
    ] = None,
    has_canonical_values: Annotated[
        bool | None, Query(description="Filter by canonical Index value availability.")
    ] = None,
    cadence: Annotated[
        str | None, Query(description="Filter by a canonical cadence such as 1m or 1d.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum rows per page.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Zero-based page offset.")] = 0,
) -> PaginatedResponse[Index]:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400, detail="Only response_format=frontend_list is supported."
        )
    result = list_indices(
        search=search,
        index_type=index_type,
        provider=provider,
        has_definition=has_definition,
        has_canonical_values=has_canonical_values,
        cadence=cadence,
        limit=limit,
        offset=offset,
    )
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        count, rows = result
    else:  # Compatibility for callers monkeypatching the pre-ADR list service.
        rows = list(result)
        count = offset + len(rows)
    return build_paginated_response(
        request_url=str(request.url),
        results=rows,
        limit=limit,
        offset=offset,
        count=count,
    )


@router.post(
    "/",
    response_model=Index,
    status_code=status.HTTP_201_CREATED,
    summary="Create Index",
    operation_id="createIndex",
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_index_record(payload: IndexCreate) -> Index:
    try:
        return create_index(payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{uid}/",
    response_model=Index,
    summary="Get index",
    operation_id="getIndex",
    responses={404: {"model": ErrorResponse}},
)
def get_index_by_uid(uid: str) -> Index:
    record = get_index(uid=uid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return record


@router.patch(
    "/{uid}/",
    response_model=Index,
    summary="Update Index",
    operation_id="updateIndex",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_index_record(uid: str, payload: IndexUpdate) -> Index:
    try:
        record = update_index(uid=uid, payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return record


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get Index summary",
    operation_id="getIndexSummary",
    responses={404: {"model": ErrorResponse}},
)
def get_index_summary_by_uid(
    uid: str,
    actor: Annotated[IndexActor | None, Depends(_request_actor)],
) -> FrontEndDetailSummary:
    summary = get_index_summary(uid=uid, actor=actor)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/methodologies/",
    response_model=list[IndexMethodologySummary],
    summary="List Index methodologies",
    operation_id="listIndexMethodologies",
    responses={404: {"model": ErrorResponse}},
)
def get_index_methodologies(uid: str) -> list[IndexMethodologySummary]:
    result = list_index_methodologies(uid=uid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return list(result)


@router.get(
    "/{uid}/methodologies/{definition_uid}/",
    response_model=IndexMethodologyDetail,
    summary="Get Index methodology",
    operation_id="getIndexMethodology",
    responses={404: {"model": ErrorResponse}},
)
def get_index_methodology_by_uid(uid: str, definition_uid: str) -> IndexMethodologyDetail:
    result = get_index_methodology(uid=uid, definition_uid=definition_uid)
    if result is None:
        raise HTTPException(status_code=404, detail="Index methodology was not found.")
    return result


@router.get(
    "/{uid}/datasets/",
    response_model=list[IndexDatasetState],
    summary="List Index datasets",
    description="List cadence-specific canonical datasets verified by an actual foreign key to Index.unique_identifier.",
    operation_id="listIndexDatasets",
    responses={404: {"model": ErrorResponse}},
)
def get_index_datasets(
    uid: str,
    actor: Annotated[IndexActor | None, Depends(_request_actor)],
    include_empty: Annotated[
        bool,
        Query(description="Include compatible canonical datasets with no reconciled rows."),
    ] = False,
) -> list[IndexDatasetState]:
    result = list_index_datasets(uid=uid, actor=actor, include_empty=include_empty)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return list(result)


@router.get(
    "/{uid}/datasets/{meta_table_uid}/",
    response_model=IndexDatasetSummary,
    summary="Get Index dataset summary",
    operation_id="getIndexDatasetSummary",
    responses={404: {"model": ErrorResponse}},
)
def get_index_dataset_summary_by_uid(
    uid: str,
    meta_table_uid: str,
    actor: Annotated[IndexActor | None, Depends(_request_actor)],
) -> IndexDatasetSummary:
    try:
        result = get_index_dataset_summary(
            uid=uid,
            meta_table_uid=meta_table_uid,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return result


@router.get(
    "/{uid}/datasets/{meta_table_uid}/values/",
    response_model=TabularFrameResponse,
    summary="Get Index dataset values frame",
    operation_id="getIndexDatasetValuesFrame",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    openapi_extra={
        "x-ui-contract": "core.tabular_frame@v1",
        "x-ui-output-root": "response:$",
    },
)
def get_index_dataset_values(
    uid: str,
    meta_table_uid: str,
    start: Annotated[dt.datetime, Query(description="Inclusive timezone-aware start timestamp.")],
    end: Annotated[dt.datetime, Query(description="Inclusive timezone-aware end timestamp.")],
    actor: Annotated[IndexActor | None, Depends(_request_actor)],
    order: Annotated[str, Query(pattern="^(asc|desc)$", description="Timestamp order.")] = "desc",
    limit: Annotated[int, Query(ge=1, le=5000, description="Server-enforced row limit.")] = 500,
) -> TabularFrameResponse:
    try:
        result = get_index_values_frame(
            uid=uid,
            meta_table_uid=meta_table_uid,
            start=start,
            end=end,
            order=order,
            limit=limit,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return result


@router.get(
    "/{uid}/related-meta-tables/",
    response_model=list[IndexRelatedMetaTable],
    summary="List related Index MetaTables",
    operation_id="listIndexRelatedMetaTables",
    responses={404: {"model": ErrorResponse}},
)
def get_related_index_meta_tables(uid: str) -> list[IndexRelatedMetaTable]:
    result = list_index_related_meta_tables(uid=uid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return list(result)


@router.get(
    "/{uid}/delete-impact/",
    response_model=DeleteImpactResponse,
    summary="Preview index delete impact",
    description=(
        "Read-only impact metadata for the standard direct Index delete route. "
        "This response does not authorize deletion."
    ),
    operation_id="getIndexDeleteImpact",
    responses={404: {"model": ErrorResponse}},
)
def get_index_delete_impact_by_uid(uid: str) -> DeleteImpactResponse:
    impact = get_index_delete_impact(uid=uid)
    if impact is None:
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return impact


@router.delete(
    "/{uid}/",
    response_model=Index | None,
    summary="Delete Index",
    description=(
        "Delete one Index identity row by uid. This route returns `null` on success. "
        "Related rows are governed by the backend table constraints."
    ),
    operation_id="deleteIndex",
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
)
def remove_index(uid: str) -> Index | None:
    if not delete_index(uid=uid):
        raise HTTPException(status_code=404, detail=f"Index {uid!r} was not found.")
    return None


__all__ = ["index_type_router", "router"]
