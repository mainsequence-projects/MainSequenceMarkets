from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status as http_status

from apps.v1.schemas.common import ErrorResponse, build_paginated_response
from apps.v1.schemas.pricing_market_data import (
    PricingMarketDataBindingResolveResponse,
    PricingMarketDataCardResponse,
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
    PricingMarketDataSetBindingCreate,
    PricingMarketDataSetBindingDeleteResponse,
    PricingMarketDataSetBindingListResponse,
    PricingMarketDataSetBindingUpdate,
    PricingMarketDataSetBindingUpsert,
    PricingMarketDataSetCreate,
    PricingMarketDataSetDeleteResponse,
    PricingMarketDataSetListResponse,
    PricingMarketDataSetUpdate,
    PricingMarketDataSetUpsert,
)
from apps.v1.services.pricing_market_data import (
    create_pricing_market_data_binding,
    create_pricing_market_data_set,
    delete_pricing_market_data_binding,
    delete_pricing_market_data_set,
    get_pricing_market_data_binding,
    get_pricing_market_data_set,
    get_pricing_market_data_set_by_key,
    list_pricing_market_data_bindings,
    list_pricing_market_data_set_bindings,
    list_pricing_market_data_sets,
    pricing_market_data_card,
    resolve_pricing_market_data_binding,
    update_pricing_market_data_binding,
    update_pricing_market_data_set,
    upsert_pricing_market_data_binding,
    upsert_pricing_market_data_set,
)

router = APIRouter(prefix="/pricing/market_data", tags=["pricing-market-data"])


@router.get(
    "/",
    response_model=PricingMarketDataCardResponse,
    summary="Get pricing market-data API card",
    description=(
        "Return a small discoverability card for pricing market-data set and "
        "binding operations."
    ),
    operation_id="getPricingMarketDataCard",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data discoverability request.",
        }
    },
)
def get_pricing_market_data_card() -> PricingMarketDataCardResponse:
    return PricingMarketDataCardResponse.model_validate(pricing_market_data_card())


@router.get(
    "/sets/",
    response_model=PricingMarketDataSetListResponse,
    summary="List pricing market-data sets",
    description=(
        "Return paginated pricing market-data set rows from `msm_pricing.api`."
    ),
    operation_id="listPricingMarketDataSets",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set list request.",
        }
    },
)
def get_pricing_market_data_sets(
    request: Request,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of pricing market-data sets to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered set list.",
        ),
    ] = 0,
    status: Annotated[
        str | None,
        Query(description="Optional exact status filter."),
    ] = None,
    set_key: Annotated[
        str | None,
        Query(description="Optional exact set_key filter."),
    ] = None,
) -> PricingMarketDataSetListResponse:
    try:
        response = PricingMarketDataSetListResponse.model_validate(
            list_pricing_market_data_sets(
                limit=limit,
                offset=offset,
                status=status,
                set_key=set_key,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PricingMarketDataSetListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/sets/by-key/{set_key}/",
    response_model=PricingMarketDataSet,
    summary="Get pricing market-data set by key",
    description="Return one pricing market-data set row by exact `set_key`.",
    operation_id="getPricingMarketDataSetByKey",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data set key was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set key lookup.",
        },
    },
)
def get_pricing_market_data_set_by_set_key(set_key: str) -> PricingMarketDataSet:
    try:
        row = get_pricing_market_data_set_by_key(set_key=set_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing market-data set {set_key!r} was not found.",
        )
    return row


@router.get(
    "/sets/{uid}/",
    response_model=PricingMarketDataSet,
    summary="Get pricing market-data set",
    description="Return one pricing market-data set row by uid.",
    operation_id="getPricingMarketDataSet",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data set uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set lookup.",
        },
    },
)
def get_pricing_market_data_set_by_uid(uid: str) -> PricingMarketDataSet:
    try:
        row = get_pricing_market_data_set(uid=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing market-data set {uid!r} was not found.",
        )
    return row


@router.post(
    "/sets/",
    response_model=PricingMarketDataSet,
    summary="Create pricing market-data set",
    description="Create one pricing market-data set through `msm_pricing.api`.",
    operation_id="createPricingMarketDataSet",
    status_code=http_status.HTTP_201_CREATED,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set payload or unsupported source API state.",
        }
    },
)
def post_pricing_market_data_set(
    payload: PricingMarketDataSetCreate,
) -> PricingMarketDataSet:
    try:
        return create_pricing_market_data_set(payload)
    except (LookupError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sets/upsert/",
    response_model=PricingMarketDataSet,
    summary="Upsert pricing market-data set",
    description=(
        "Create or update one pricing market-data set by `set_key` through "
        "`msm_pricing.api`."
    ),
    operation_id="upsertPricingMarketDataSet",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set payload or unsupported source API state.",
        }
    },
)
def upsert_pricing_market_data_set_by_key(
    payload: PricingMarketDataSetUpsert,
) -> PricingMarketDataSet:
    try:
        return upsert_pricing_market_data_set(payload)
    except (LookupError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/sets/{uid}/",
    response_model=PricingMarketDataSet,
    summary="Update pricing market-data set",
    description="Update mutable pricing market-data set fields by uid.",
    operation_id="updatePricingMarketDataSet",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data set uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set update payload.",
        },
    },
)
def patch_pricing_market_data_set(
    uid: str,
    payload: PricingMarketDataSetUpdate,
) -> PricingMarketDataSet:
    try:
        return update_pricing_market_data_set(uid=uid, payload=payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/sets/{uid}/",
    response_model=PricingMarketDataSetDeleteResponse,
    summary="Delete pricing market-data set",
    description=(
        "Delete one pricing market-data set by uid through `msm_pricing.api`. "
        "Related bindings are removed by backend cascade behavior."
    ),
    operation_id="deletePricingMarketDataSet",
    status_code=http_status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data set uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set delete request.",
        },
    },
)
def remove_pricing_market_data_set(uid: str) -> PricingMarketDataSetDeleteResponse:
    try:
        response = PricingMarketDataSetDeleteResponse.model_validate(
            delete_pricing_market_data_set(uid=uid)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing market-data set {uid!r} was not found.",
        )
    return response


@router.get(
    "/bindings/",
    response_model=PricingMarketDataSetBindingListResponse,
    summary="List pricing market-data bindings",
    description=(
        "Return paginated pricing market-data concept binding rows from "
        "`msm_pricing.api`."
    ),
    operation_id="listPricingMarketDataBindings",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding list request.",
        }
    },
)
def get_pricing_market_data_bindings(
    request: Request,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of pricing market-data bindings to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered binding list.",
        ),
    ] = 0,
    market_data_set_uid: Annotated[
        str | None,
        Query(description="Optional exact pricing market-data set uid filter."),
    ] = None,
    concept_key: Annotated[
        str | None,
        Query(description="Optional exact pricing concept key filter."),
    ] = None,
) -> PricingMarketDataSetBindingListResponse:
    try:
        response = PricingMarketDataSetBindingListResponse.model_validate(
            list_pricing_market_data_bindings(
                limit=limit,
                offset=offset,
                market_data_set_uid=market_data_set_uid,
                concept_key=concept_key,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PricingMarketDataSetBindingListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/sets/{market_data_set_uid}/bindings/",
    response_model=PricingMarketDataSetBindingListResponse,
    summary="List pricing market-data set bindings",
    description="Return paginated concept bindings owned by one pricing market-data set.",
    operation_id="listPricingMarketDataSetBindings",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data set binding list request.",
        }
    },
)
def get_pricing_market_data_bindings_by_set(
    request: Request,
    market_data_set_uid: str,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of pricing market-data bindings to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered binding list.",
        ),
    ] = 0,
) -> PricingMarketDataSetBindingListResponse:
    try:
        response = PricingMarketDataSetBindingListResponse.model_validate(
            list_pricing_market_data_set_bindings(
                market_data_set_uid=market_data_set_uid,
                limit=limit,
                offset=offset,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PricingMarketDataSetBindingListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/bindings/resolve/",
    response_model=PricingMarketDataBindingResolveResponse,
    summary="Resolve pricing market-data binding",
    description=(
        "Resolve the DataNode storage uid used by one pricing concept in a "
        "market-data set."
    ),
    operation_id="resolvePricingMarketDataBinding",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No pricing market-data binding exists for the request.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding resolution request.",
        },
    },
)
def resolve_pricing_market_data_binding_row(
    concept_key: Annotated[
        str,
        Query(
            min_length=1,
            description="Pricing concept key to resolve, such as `discount_curves`.",
        ),
    ],
    market_data_set: Annotated[
        str | None,
        Query(
            description=(
                "Optional pricing market-data set key or uid. When omitted, "
                "`msm_pricing` resolves its configured default."
            ),
        ),
    ] = None,
) -> PricingMarketDataBindingResolveResponse:
    try:
        return PricingMarketDataBindingResolveResponse.model_validate(
            resolve_pricing_market_data_binding(
                market_data_set=market_data_set,
                concept_key=concept_key,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/bindings/{uid}/",
    response_model=PricingMarketDataSetBinding,
    summary="Get pricing market-data binding",
    description="Return one pricing market-data binding row by uid.",
    operation_id="getPricingMarketDataBinding",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data binding uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding lookup.",
        },
    },
)
def get_pricing_market_data_binding_by_uid(uid: str) -> PricingMarketDataSetBinding:
    try:
        row = get_pricing_market_data_binding(uid=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing market-data binding {uid!r} was not found.",
        )
    return row


@router.post(
    "/bindings/",
    response_model=PricingMarketDataSetBinding,
    summary="Create pricing market-data binding",
    description="Create one pricing market-data concept binding through `msm_pricing.api`.",
    operation_id="createPricingMarketDataBinding",
    status_code=http_status.HTTP_201_CREATED,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding payload or unsupported source API state.",
        }
    },
)
def post_pricing_market_data_binding(
    payload: PricingMarketDataSetBindingCreate,
) -> PricingMarketDataSetBinding:
    try:
        return create_pricing_market_data_binding(payload)
    except (LookupError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/bindings/upsert/",
    response_model=PricingMarketDataSetBinding,
    summary="Upsert pricing market-data binding",
    description=(
        "Create or update one pricing market-data concept binding by "
        "`market_data_set_uid` and `concept_key` through `msm_pricing.api`."
    ),
    operation_id="upsertPricingMarketDataBinding",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding payload or unsupported source API state.",
        }
    },
)
def upsert_pricing_market_data_binding_by_set_and_concept(
    payload: PricingMarketDataSetBindingUpsert,
) -> PricingMarketDataSetBinding:
    try:
        return upsert_pricing_market_data_binding(payload)
    except (LookupError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/bindings/{uid}/",
    response_model=PricingMarketDataSetBinding,
    summary="Update pricing market-data binding",
    description="Update mutable pricing market-data binding fields by uid.",
    operation_id="updatePricingMarketDataBinding",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data binding uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding update payload.",
        },
    },
)
def patch_pricing_market_data_binding(
    uid: str,
    payload: PricingMarketDataSetBindingUpdate,
) -> PricingMarketDataSetBinding:
    try:
        return update_pricing_market_data_binding(uid=uid, payload=payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/bindings/{uid}/",
    response_model=PricingMarketDataSetBindingDeleteResponse,
    summary="Delete pricing market-data binding",
    description="Delete one pricing market-data binding row by uid through `msm_pricing.api`.",
    operation_id="deletePricingMarketDataBinding",
    status_code=http_status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested pricing market-data binding uid was not found.",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid pricing market-data binding delete request.",
        },
    },
)
def remove_pricing_market_data_binding(
    uid: str,
) -> PricingMarketDataSetBindingDeleteResponse:
    try:
        response = PricingMarketDataSetBindingDeleteResponse.model_validate(
            delete_pricing_market_data_binding(uid=uid)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing market-data binding {uid!r} was not found.",
        )
    return response
