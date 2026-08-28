from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Query, status

from apps.v1.schemas.bulk_actions import (
    BULK_ACTION_PREFLIGHT_CONTRACT,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
)
from apps.v1.schemas.command_center import TabularFrameResponse
from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary
from apps.v1.schemas.portfolios import (
    PortfolioBulkCascadeDeleteResponse,
    PortfolioBulkDeleteResponse,
    PortfolioDeleteRequest,
    PortfolioDeleteResponse,
    PortfolioDetailResponse,
    Portfolio,
    PortfolioWeightsDeleteResponse,
    PortfolioWeightsSnapshotResponse,
)
from apps.v1.schemas.resource_contracts import (
    RESOURCE_COLLECTION_CONTRACT,
    ResourceCollection,
)
from apps.v1.services.portfolios import (
    PortfolioDataIntegrityError,
    bulk_cascade_delete_portfolios,
    bulk_delete_portfolios,
    delete_portfolio,
    delete_portfolio_weights,
    get_portfolio_detail,
    get_portfolio_signal_weights_frame,
    get_portfolio_summary,
    get_portfolio_values_frame,
    get_portfolio_weights,
    list_portfolios,
    preflight_bulk_delete_portfolios,
)
from apps.v1.services.resource_collections import resource_collection_response
from apps.v1.services.bulk_actions import (
    blocked_preflight_detail,
    explicit_uuid_selection,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)


@router.get(
    "/",
    response_model=ResourceCollection[Portfolio],
    summary="List portfolios",
    description=("Return portfolios in the canonical Command Center resource collection contract."),
    operation_id="listPortfolios",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid resource collection request.",
        },
        409: {
            "model": ErrorResponse,
            "description": "A stored portfolio row violates the current portfolio contract.",
        },
    },
)
def get_portfolios(
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across portfolio uid, unique identifier, "
                "calendar uid, published-index uid, and signal uid fields."
            ),
        ),
    ] = "",
    calendar_uid: Annotated[
        str | None,
        Query(description="Optional exact Calendar uid filter."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of portfolio rows to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered portfolio list."),
    ] = 0,
) -> ResourceCollection[Portfolio]:
    try:
        response = list_portfolios(
            search=search,
            calendar_uid=calendar_uid,
            limit=limit,
            offset=offset,
        )
    except PortfolioDataIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return resource_collection_response(
        items=response["results"],
        total_items=int(response["count"]),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/bulk-delete/",
    response_model=PortfolioBulkDeleteResponse,
    summary="Bulk delete portfolios",
    description=(
        "Delete multiple portfolio identity rows by uid. Rows referenced by protected "
        "tables are reported in `failed` and are not silently removed."
    ),
    operation_id="bulkDeletePortfolios",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio bulk-delete payload.",
        },
        409: {
            "model": ErrorResponse,
            "description": "One or more portfolios could not be deleted.",
        },
    },
)
def bulk_delete_portfolio_rows(
    payload: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request."),
    ],
) -> PortfolioBulkDeleteResponse:
    try:
        uids = explicit_uuid_selection(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preflight = BulkActionPreflightResponse.model_validate(
        preflight_bulk_delete_portfolios(uids=uids)
    )
    if not preflight.allowed:
        raise HTTPException(status_code=409, detail=blocked_preflight_detail(preflight))
    response = bulk_delete_portfolios(uids=uids)
    if response.failed:
        detail = _portfolio_bulk_delete_error_detail(response)
        logger.warning(
            "Portfolio bulk delete failed.",
            extra={
                "failed": [failure.model_dump(mode="json") for failure in response.failed],
                "deleted_count": response.deleted_count,
                "deleted_weights_count": response.deleted_weights_count,
                "deleted_values_count": response.deleted_values_count,
            },
        )
        raise HTTPException(status_code=409, detail=detail)
    return response


@router.post(
    "/bulk-delete/preflight/",
    response_model=BulkActionPreflightResponse,
    summary="Preflight portfolio bulk deletion",
    description=(
        "Reauthorize an explicit portfolio selection and report missing rows or protected "
        "references without deleting data."
    ),
    operation_id="preflightBulkDeletePortfolios",
    openapi_extra={"x-ui-contract": BULK_ACTION_PREFLIGHT_CONTRACT},
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def preflight_portfolio_bulk_delete(
    payload: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request to preflight."),
    ],
) -> BulkActionPreflightResponse:
    try:
        uids = explicit_uuid_selection(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkActionPreflightResponse.model_validate(preflight_bulk_delete_portfolios(uids=uids))


@router.post(
    "/bulk-cascade-delete/",
    response_model=PortfolioBulkCascadeDeleteResponse,
    summary="Cascade delete portfolios",
    description=(
        "Delete multiple portfolio identity rows by uid and cascade-delete dependent "
        "portfolio values, portfolio weights, target-position rows, virtual funds, "
        "virtual-fund holdings sets, and virtual-fund holdings storage rows."
    ),
    operation_id="bulkCascadeDeletePortfolios",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio cascade-delete payload.",
        },
        409: {
            "model": ErrorResponse,
            "description": "One or more portfolios could not be cascade deleted.",
        },
    },
)
def bulk_cascade_delete_portfolio_rows(
    payload: PortfolioDeleteRequest,
) -> PortfolioBulkCascadeDeleteResponse:
    try:
        response = bulk_cascade_delete_portfolios(uids=payload.uids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response.failed:
        detail = _portfolio_bulk_delete_error_detail(response)
        logger.warning(
            "Portfolio bulk cascade delete failed.",
            extra={
                "failed": [failure.model_dump(mode="json") for failure in response.failed],
                "deleted_count": response.deleted_count,
                "deleted_weights_count": response.deleted_weights_count,
                "deleted_values_count": response.deleted_values_count,
                "deleted_target_positions_count": response.deleted_target_positions_count,
                "deleted_virtual_funds_count": response.deleted_virtual_funds_count,
                "deleted_virtual_fund_holdings_sets_count": (
                    response.deleted_virtual_fund_holdings_sets_count
                ),
                "deleted_virtual_fund_holdings_count": (
                    response.deleted_virtual_fund_holdings_count
                ),
            },
        )
        raise HTTPException(status_code=409, detail=detail)
    return response


def _portfolio_bulk_delete_error_detail(response: PortfolioBulkDeleteResponse) -> str:
    failed_reasons = "; ".join(f"{failure.uid}: {failure.reason}" for failure in response.failed)
    if failed_reasons:
        return f"{response.detail} Failed: {failed_reasons}"
    return response.detail


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get portfolio summary",
    description="Return the reusable frontend detail summary payload for one portfolio.",
    operation_id="getPortfolioSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        }
    },
)
def get_portfolio_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_portfolio_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return summary


@router.get(
    "/{uid}/weights/",
    response_model=PortfolioWeightsSnapshotResponse,
    summary="Get portfolio weights snapshot",
    description=(
        "Return one portfolio weights snapshot. When `weights_date` is provided, "
        "the endpoint returns the exact timestamp snapshot. Otherwise it returns "
        "the latest or earliest snapshot according to `order`. Missing weight rows "
        "return 200 with an empty `weights` list when the portfolio exists."
    ),
    operation_id="getPortfolioWeights",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio weights request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
    },
)
def get_portfolio_weights_by_uid(
    uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Snapshot ordering used when weights_date is omitted."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1,
            description="Number of snapshots to return. The current contract returns one snapshot.",
        ),
    ] = 1,
    include_asset_detail: Annotated[
        bool,
        Query(
            description=(
                "When true, include asset.uid, asset.unique_identifier, and latest "
                "AssetSnapshotsStorage name/ticker labels for weight rows."
            ),
        ),
    ] = True,
    weights_date: Annotated[
        dt.datetime | None,
        Query(description="Exact portfolio weights timestamp to fetch. Use ISO 8601."),
    ] = None,
) -> PortfolioWeightsSnapshotResponse:
    try:
        snapshot = get_portfolio_weights(
            uid=uid,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
            weights_date=weights_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return snapshot


@router.get(
    "/{uid}/signals_weights/",
    response_model=TabularFrameResponse,
    summary="Get portfolio signal weights frame",
    description=(
        "Return raw signal-weight rows for the signal TimeIndexTableUpdater linked from the "
        "portfolio row as a canonical Command Center tabular frame."
    ),
    operation_id="getPortfolioSignalWeightsFrame",
    response_model_exclude_none=True,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The portfolio has no signal TimeIndexTableUpdater link or the request is invalid.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
    },
    openapi_extra={"x-ui-contract": "core.tabular_frame@v1"},
)
def get_portfolio_signal_weights_frame_by_uid(
    uid: str,
    start_date: Annotated[
        dt.datetime | None,
        Query(description="Optional inclusive lower time_index bound. Use ISO 8601."),
    ] = None,
    end_date: Annotated[
        dt.datetime | None,
        Query(description="Optional inclusive upper time_index bound. Use ISO 8601."),
    ] = None,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Ordering by time_index."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum rows to return."),
    ] = 50,
) -> TabularFrameResponse:
    try:
        frame = get_portfolio_signal_weights_frame(
            uid=uid,
            start_date=start_date,
            end_date=end_date,
            order=order,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if frame is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return frame


@router.get(
    "/{uid}/portfolio_values/",
    response_model=TabularFrameResponse,
    summary="Get portfolio values frame",
    description=(
        "Return portfolio value rows keyed by the portfolio unique identifier as "
        "a canonical Command Center tabular frame."
    ),
    operation_id="getPortfolioValuesFrame",
    response_model_exclude_none=True,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio values request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
    },
    openapi_extra={"x-ui-contract": "core.tabular_frame@v1"},
)
def get_portfolio_values_frame_by_uid(
    uid: str,
    start_date: Annotated[
        dt.datetime | None,
        Query(description="Optional inclusive lower time_index bound. Use ISO 8601."),
    ] = None,
    end_date: Annotated[
        dt.datetime | None,
        Query(description="Optional inclusive upper time_index bound. Use ISO 8601."),
    ] = None,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Ordering by time_index."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum rows to return."),
    ] = 50,
) -> TabularFrameResponse:
    try:
        frame = get_portfolio_values_frame(
            uid=uid,
            start_date=start_date,
            end_date=end_date,
            order=order,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if frame is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return frame


@router.delete(
    "/{uid}/weights/",
    response_model=PortfolioWeightsDeleteResponse,
    summary="Delete portfolio weights",
    description=(
        "Delete historical portfolio weight rows for one portfolio through the "
        "TimeIndexMetaTable tail-delete API. When `weights_date` is provided, "
        "rows at or after that timestamp are deleted. Without `weights_date`, "
        "all weight rows for the portfolio identifier are deleted."
    ),
    operation_id="deletePortfolioWeights",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
    },
)
def remove_portfolio_weights(
    uid: str,
    weights_date: Annotated[
        dt.datetime | None,
        Query(description="Inclusive portfolio weights cutoff timestamp. Use ISO 8601."),
    ] = None,
) -> PortfolioWeightsDeleteResponse:
    try:
        response = delete_portfolio_weights(uid=uid, weights_date=weights_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return response


@router.get(
    "/{uid}/",
    response_model=PortfolioDetailResponse,
    summary="Get portfolio detail",
    description=(
        "Return one portfolio detail payload containing the core portfolio row, "
        "optional portfolio metadata, tab definitions, and route links."
    ),
    operation_id="getPortfolio",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "The stored portfolio row violates the current portfolio contract.",
        },
    },
)
def get_portfolio_by_uid(uid: str) -> PortfolioDetailResponse:
    try:
        detail = get_portfolio_detail(uid=uid)
    except PortfolioDataIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return detail


@router.delete(
    "/{uid}/",
    response_model=PortfolioDeleteResponse,
    summary="Delete portfolio",
    description=(
        "Delete one portfolio identity row. The route returns 409 when protected "
        "rows, such as account target-position history, still reference the portfolio."
    ),
    operation_id="deletePortfolio",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "The portfolio is referenced by protected rows.",
        },
    },
)
def remove_portfolio(uid: str) -> PortfolioDeleteResponse:
    try:
        response = delete_portfolio(uid=uid)
    except ValueError as exc:
        if exc.__class__.__name__ == "PortfolioDeleteConflictError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return response
