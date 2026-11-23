from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Query, status

from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.portfolios import (
    PortfolioBulkDeleteResponse,
    PortfolioDeletePreflightResponse,
    PortfolioDeleteResponse,
    PortfolioDetailResponse,
    Portfolio,
    PortfolioWeightsDeleteResponse,
    PortfolioWeightsSnapshotResponse,
)
from apps.v1.services.portfolios import (
    PortfolioDataIntegrityError,
    bulk_delete_portfolios,
    delete_portfolio,
    delete_portfolio_weights,
    get_portfolio_detail,
    get_portfolio_signal_weights_frame,
    get_portfolio_summary,
    get_portfolio_values_frame,
    get_portfolio_weights,
    get_portfolios_by_uids,
    get_portfolios_values_frame,
    get_portfolios_weights_frame,
    list_portfolio_account_targets,
    list_portfolios,
    plan_bulk_delete_portfolios,
    preflight_bulk_delete_portfolios,
    reinstate_portfolio,
    retire_portfolio,
)
from msm.api.accounts import PortfolioAccountTarget
from msm.api.http import (
    BULK_ACTION_PREFLIGHT_CONTRACT,
    CORE_TABULAR_FRAME_CONTRACT,
    RESOURCE_COLLECTION_CONTRACT,
    BulkActionExecutionRequest,
    ErrorResponse,
    ResourceCollection,
    TabularFrameResponse,
    explicit_uuid_selection,
    resource_collection_response,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)

_PORTFOLIO_DELETE_DESCRIPTION = (
    "Each portfolio is deleted with its rows in its seven datasets (weights, values, "
    "rebalance state, analytics, event ledger, state and cash flows) in one transaction, "
    "or not at all (ADR 0049, issue 93); `deleted_rows` counts them per dataset. It is "
    "refused with 409 while virtual funds or account target rows name the portfolio, or "
    "when the database refuses it: an application's own table whose RESTRICT key "
    "references the portfolio still holds rows of it (ADR 0060). Only the portfolio's "
    "manager may delete it (403 otherwise)."
)


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
    include_retired: Annotated[
        bool,
        Query(description="Include retired portfolios (ADR 0049). Off by default."),
    ] = False,
) -> ResourceCollection[Portfolio]:
    try:
        response = list_portfolios(
            search=search,
            calendar_uid=calendar_uid,
            limit=limit,
            offset=offset,
            include_retired=include_retired,
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


@router.get(
    "/by-uids/",
    response_model=ResourceCollection[Portfolio],
    summary="Look up portfolios by uid",
    description=(
        "Return the portfolio identity rows whose uid is listed in `uid__in` (repeated or "
        "comma-separated, at most 500), in request order. Unknown uids are omitted. A bounded "
        "batch lookup, not a browsable collection."
    ),
    operation_id="getPortfoliosByUids",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid `uid__in`."},
        409: {
            "model": ErrorResponse,
            "description": "A stored portfolio row is invalid.",
        },
    },
)
def get_portfolios_by_uid_list(
    uid__in: Annotated[
        list[str],
        Query(alias="uid__in", description="Portfolio uids, repeated or comma-separated."),
    ],
) -> ResourceCollection[Portfolio]:
    try:
        items = get_portfolios_by_uids(uids=uid__in)
    except PortfolioDataIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resource_collection_response(
        items=items, total_items=len(items), limit=max(len(items), 1), offset=0
    )


@router.get(
    "/values/",
    response_model=TabularFrameResponse,
    summary="Get values frame for several portfolios",
    description=(
        "Return portfolio value rows for every portfolio in `portfolio_uid__in` as one canonical "
        "Command Center tabular frame, read from Markets' own PortfoliosTS table whoever "
        "published the portfolios (ADR 0060)."
    ),
    operation_id="getPortfoliosValuesFrame",
    response_model_exclude_none=True,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    openapi_extra={"x-ui-contract": CORE_TABULAR_FRAME_CONTRACT},
)
def get_portfolios_values_frame_route(
    portfolio_uid__in: Annotated[
        list[str],
        Query(alias="portfolio_uid__in", description="Portfolio uids, repeated or comma-separated."),
    ],
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
        Query(description="Ordering by time_index across all portfolios."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(ge=1, le=5000, description="Maximum rows to return across all portfolios."),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Rows of the ordered frame to skip; pages through long windows."),
    ] = 0,
) -> TabularFrameResponse:
    try:
        return get_portfolios_values_frame(
            uids=portfolio_uid__in,
            start_date=start_date,
            end_date=end_date,
            order=order,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/weights/",
    response_model=TabularFrameResponse,
    summary="Get weights frame for several portfolios",
    description=(
        "Return one weight snapshot per portfolio in `portfolio_uid__in` as one canonical "
        "Command Center tabular frame: the latest snapshot, the latest at or before "
        "`weights_date` with `as_of=true`, or the exact `weights_date` snapshot with "
        "`as_of=false`, read from Markets' own PortfolioWeightsTS table (ADR 0060)."
    ),
    operation_id="getPortfoliosWeightsFrame",
    response_model_exclude_none=True,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    openapi_extra={"x-ui-contract": CORE_TABULAR_FRAME_CONTRACT},
)
def get_portfolios_weights_frame_route(
    portfolio_uid__in: Annotated[
        list[str],
        Query(alias="portfolio_uid__in", description="Portfolio uids, repeated or comma-separated."),
    ],
    weights_date: Annotated[
        dt.datetime | None,
        Query(description="Snapshot timestamp. Omit for the latest snapshot of each portfolio."),
    ] = None,
    as_of: Annotated[
        bool,
        Query(description="With weights_date: true selects the latest snapshot at or before it."),
    ] = True,
) -> TabularFrameResponse:
    try:
        return get_portfolios_weights_frame(
            uids=portfolio_uid__in,
            weights_date=weights_date,
            as_of=as_of,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/bulk-delete/",
    response_model=PortfolioBulkDeleteResponse,
    summary="Bulk delete portfolios",
    description=(
        "Delete every selected portfolio that may go, each with its rows in its seven "
        "datasets (ADR 0049, issues 93 and 127); `deleted_rows` counts them per dataset. The "
        "selection is counted once, and the portfolios that may go are deleted together in "
        "one transaction. A portfolio that is missing, that virtual funds or account target "
        "rows name, that the caller does not manage, or whose delete the database refuses "
        "(an application's own table whose RESTRICT key references it still holds rows of "
        "it, ADR 0060) never stops the others: the answer lists each deleted portfolio in "
        "`deleted` and each one that was not deleted, with the reason, in `failed`."
    ),
    operation_id="bulkDeletePortfolios",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid portfolio bulk-delete payload.",
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
    # One counting read: the delete uses the preflight's plan (issue 96).
    plan = plan_bulk_delete_portfolios(uids=uids)
    response = bulk_delete_portfolios(uids=uids, plan=plan)
    if response.failed:
        logger.info(
            "Portfolio bulk delete kept some portfolios.",
            extra={
                "failed": [failure.model_dump(mode="json") for failure in response.failed],
                "deleted_count": response.deleted_count,
            },
        )
    return response


@router.post(
    "/bulk-delete/preflight/",
    response_model=PortfolioDeletePreflightResponse,
    summary="Preflight portfolio bulk deletion",
    description=(
        "Run the delete's checks for an explicit portfolio selection without deleting: per "
        "portfolio the rows each of its seven datasets would lose (`portfolios[].row_counts`) "
        "and its blockers (account history that names it, and tables of other applications "
        "whose RESTRICT keys reference it and that hold rows of it or cannot be checked), "
        "missing portfolios, and the MetaTables delete impact."
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
) -> PortfolioDeletePreflightResponse:
    try:
        uids = explicit_uuid_selection(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PortfolioDeletePreflightResponse.model_validate(
        preflight_bulk_delete_portfolios(uids=uids)
    )


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
    openapi_extra={"x-ui-contract": CORE_TABULAR_FRAME_CONTRACT},
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
    openapi_extra={"x-ui-contract": CORE_TABULAR_FRAME_CONTRACT},
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
        "all weight rows for the portfolio identifier are deleted. Only the portfolio's "
        "manager may delete them (ADR 0060)."
    ),
    operation_id="deletePortfolioWeights",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
        403: {
            "model": ErrorResponse,
            "description": "The caller does not manage the portfolio.",
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
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return response


@router.get(
    "/{uid}/account-targets/",
    response_model=ResourceCollection[PortfolioAccountTarget],
    summary="List accounts whose current target names the portfolio",
    description=(
        "Page the accounts whose current target has a portfolio row for this portfolio, "
        "ordered by account uid. The current target is the latest PositionSet across the "
        "account's active target allocations, as GET /api/v1/account/{account_uid}/"
        "target-positions/ reads it; an account that named the portfolio only in an earlier "
        "snapshot, or whose target was cleared, is not returned. Each item gives the account, "
        "its target allocation, the snapshot's PositionSet uid and time, and the exposure."
    ),
    operation_id="listPortfolioAccountTargets",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {"model": ErrorResponse, "description": "Invalid paging request."},
        404: {"model": ErrorResponse, "description": "The requested portfolio uid was not found."},
    },
)
def get_portfolio_account_targets(
    uid: str,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of accounts to return."),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the account list."),
    ] = 0,
) -> ResourceCollection[PortfolioAccountTarget]:
    try:
        response = list_portfolio_account_targets(uid=uid, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return resource_collection_response(
        items=response["results"],
        total_items=int(response["count"]),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{uid}/retire/",
    response_model=Portfolio,
    summary="Retire portfolio",
    description=(
        "Retire the portfolio from now on (ADR 0049) and return it with retired_at. Nothing "
        "is deleted: account target snapshots, virtual funds and the portfolio's weights and "
        "values stay. While retired, no target snapshot may name it, no virtual-fund holdings "
        "are written for it from retired_at on, lists and target search leave it out, and the "
        "portfolio updaters write nothing from retired_at on. Refused with 409 while any "
        "account's current target names it; GET /api/v1/portfolio/{uid}/account-targets/ "
        "lists those accounts. Retiring a retired portfolio returns it unchanged."
    ),
    operation_id="retirePortfolio",
    responses={
        404: {"model": ErrorResponse, "description": "The requested portfolio uid was not found."},
        409: {
            "model": ErrorResponse,
            "description": "An account's current target names the portfolio.",
        },
    },
)
def retire_portfolio_by_uid(uid: str) -> Portfolio:
    try:
        portfolio = retire_portfolio(uid=uid)
    except ValueError as exc:
        if exc.__class__.__name__ == "PortfolioRetirementConflictError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return portfolio


@router.post(
    "/{uid}/reinstate/",
    response_model=Portfolio,
    summary="Reinstate portfolio",
    description=(
        "Clear the portfolio's retired_at (ADR 0049) and return it. Target snapshots may name "
        "it again, and the portfolio updaters fill the retired period on their next run. "
        "Reinstating a live portfolio returns it unchanged."
    ),
    operation_id="reinstatePortfolio",
    responses={
        404: {"model": ErrorResponse, "description": "The requested portfolio uid was not found."},
    },
)
def reinstate_portfolio_by_uid(uid: str) -> Portfolio:
    try:
        portfolio = reinstate_portfolio(uid=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return portfolio


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
    description="Delete one portfolio. " + _PORTFOLIO_DELETE_DESCRIPTION,
    operation_id="deletePortfolio",
    status_code=status.HTTP_200_OK,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": (
                "Account history references the portfolio, or the database refused the "
                "delete. Nothing was deleted."
            ),
        },
        403: {
            "model": ErrorResponse,
            "description": "The caller does not manage the portfolio.",
        },
    },
)
def remove_portfolio(uid: str) -> PortfolioDeleteResponse:
    try:
        response = delete_portfolio(uid=uid)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        if exc.__class__.__name__ == "PortfolioDeleteConflictError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {uid!r} was not found.")
    return response
