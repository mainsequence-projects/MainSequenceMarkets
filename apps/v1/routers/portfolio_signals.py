from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from apps.v1.schemas.common import ErrorResponse, build_paginated_response
from apps.v1.schemas.portfolio_signals import (
    PortfolioSignalDeleteResponse,
    PortfolioSignalListResponse,
    PortfolioSignalWeightsDeleteResponse,
    SignalMetadata,
    SignalMetadataCreate,
    SignalMetadataUpdate,
)
from apps.v1.services.portfolio_signals import (
    PortfolioSignalDeleteConflictError,
    create_portfolio_signal,
    delete_portfolio_signal,
    delete_portfolio_signal_weights,
    get_portfolio_signal,
    list_portfolio_signals,
    update_portfolio_signal,
)

router = APIRouter(prefix="/portfolio-signal", tags=["portfolio-signal"])


@router.get(
    "/",
    response_model=PortfolioSignalListResponse,
    summary="List portfolio signals",
    description=(
        "Return SignalMetadata rows in the reusable limit-offset pagination envelope. "
        "`search` is a contains filter over signal_uid; `signal_uid` is an exact filter."
    ),
    operation_id="listPortfolioSignals",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio signal list request.",
        }
    },
)
def get_portfolio_signals(
    request: Request,
    search: Annotated[
        str,
        Query(description="Optional contains search over signal_uid."),
    ] = "",
    signal_uid: Annotated[
        str | None,
        Query(description="Optional exact signal_uid filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of signal metadata rows to return."),
    ] = 25,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered signal list."),
    ] = 0,
) -> PortfolioSignalListResponse:
    try:
        response = list_portfolio_signals(
            search=search,
            signal_uid=signal_uid,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PortfolioSignalListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post(
    "/",
    response_model=SignalMetadata,
    summary="Create portfolio signal",
    description="Create one SignalMetadata row. The signal_uid must be stable and unique.",
    operation_id="createPortfolioSignal",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio signal create payload.",
        }
    },
)
def create_portfolio_signal_row(payload: SignalMetadataCreate) -> SignalMetadata:
    try:
        return create_portfolio_signal(payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{uid}/",
    response_model=SignalMetadata,
    summary="Get portfolio signal",
    description="Return one SignalMetadata row by metadata row uid.",
    operation_id="getPortfolioSignal",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested signal metadata uid was not found.",
        }
    },
)
def get_portfolio_signal_by_uid(uid: str) -> SignalMetadata:
    signal = get_portfolio_signal(uid=uid)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"Portfolio signal {uid!r} was not found.")
    return signal


@router.patch(
    "/{uid}/",
    response_model=SignalMetadata,
    summary="Update portfolio signal",
    description=(
        "Update mutable SignalMetadata fields. signal_uid is immutable because "
        "SignalWeightsStorage rows reference it."
    ),
    operation_id="updatePortfolioSignal",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio signal update payload.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested signal metadata uid was not found.",
        },
    },
)
def update_portfolio_signal_by_uid(
    uid: str,
    payload: SignalMetadataUpdate,
) -> SignalMetadata:
    try:
        signal = update_portfolio_signal(uid=uid, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if signal is None:
        raise HTTPException(status_code=404, detail=f"Portfolio signal {uid!r} was not found.")
    return signal


@router.delete(
    "/{uid}/weights/",
    response_model=PortfolioSignalWeightsDeleteResponse,
    summary="Delete portfolio signal weights",
    description=(
        "Delete historical SignalWeightsStorage rows for one signal metadata row "
        "through the TimeIndexMetaTable tail-delete API. When weights_date is "
        "provided, rows at or after that timestamp are deleted. Without "
        "weights_date, all storage rows for the signal_uid are deleted."
    ),
    operation_id="deletePortfolioSignalWeights",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested signal metadata uid was not found.",
        }
    },
)
def remove_portfolio_signal_weights(
    uid: str,
    weights_date: Annotated[
        dt.datetime | None,
        Query(description="Inclusive signal weights cutoff timestamp. Use ISO 8601."),
    ] = None,
) -> PortfolioSignalWeightsDeleteResponse:
    try:
        response = delete_portfolio_signal_weights(uid=uid, weights_date=weights_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio signal {uid!r} was not found.")
    return response


@router.delete(
    "/{uid}/",
    response_model=PortfolioSignalDeleteResponse,
    summary="Delete portfolio signal",
    description=(
        "Delete one SignalMetadata row and its historical SignalWeightsStorage rows. "
        "Storage cleanup uses the TimeIndexMetaTable tail-delete API scoped by signal_uid."
    ),
    operation_id="deletePortfolioSignal",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested signal metadata uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "The signal metadata row could not be deleted.",
        },
    },
)
def delete_portfolio_signal_by_uid(uid: str) -> PortfolioSignalDeleteResponse:
    try:
        response = delete_portfolio_signal(uid=uid)
    except PortfolioSignalDeleteConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio signal {uid!r} was not found.")
    return response
