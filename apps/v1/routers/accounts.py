from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from apps.v1.schemas.accounts import (
    AccountAddHoldingsRequest,
    AccountAddTargetPositionsRequest,
    AccountHoldingsByFundResponse,
    AccountHoldingsSnapshotResponse,
    AccountListResponse,
    AccountTargetAllocationCandidateResponse,
    AccountTargetAllocationTargetSearchType,
    AccountTargetPositionsSnapshotResponse,
)
from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary, build_paginated_response
from apps.v1.services.accounts import (
    add_account_holdings,
    add_account_target_positions,
    get_account_holdings,
    get_account_holdings_by_fund,
    get_account_summary,
    get_account_target_positions,
    list_accounts,
    search_account_target_allocation_targets,
)

router = APIRouter(prefix="/account", tags=["account"])


@router.get(
    "/",
    response_model=AccountListResponse,
    summary="List accounts",
    description=(
        "Return accounts in a frontend list wrapper with total count and paginated results."
    ),
    operation_id="listAccounts",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid account list request.",
        }
    },
)
def get_accounts(
    request: Request,
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across account uid, unique identifier, and display name.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of accounts to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered account list.",
        ),
    ] = 0,
) -> AccountListResponse:
    response = AccountListResponse.model_validate(
        list_accounts(search=search, limit=limit, offset=offset)
    )
    return AccountListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get account summary",
    description=("Return the reusable frontend detail summary payload for one account."),
    operation_id="getAccountSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_account_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Account {uid!r} was not found.")
    return summary


@router.get(
    "/target-allocation/targets/",
    response_model=AccountTargetAllocationCandidateResponse,
    summary="Search account target-allocation targets",
    description=(
        "Search asset and portfolio rows that can be assigned as account target "
        "positions. Returned rows include the concrete target fields needed by "
        "TargetPositionsStorage."
    ),
    operation_id="searchAccountTargetAllocationTargets",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid target-allocation target search request.",
        }
    },
)
def search_account_target_allocation_target_rows(
    request: Request,
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across asset identifiers, latest asset "
                "snapshot labels, portfolio identifiers, and target UIDs."
            ),
        ),
    ] = "",
    target_type: Annotated[
        AccountTargetAllocationTargetSearchType,
        Query(description="Candidate kind to return: all, asset, or portfolio."),
    ] = "all",
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of target candidates to return."),
    ] = 25,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered candidate list."),
    ] = 0,
) -> AccountTargetAllocationCandidateResponse:
    try:
        response = AccountTargetAllocationCandidateResponse.model_validate(
            search_account_target_allocation_targets(
                search=search,
                target_type=target_type,
                limit=limit,
                offset=offset,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AccountTargetAllocationCandidateResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=response.results,
            count=response.count,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/{account_uid}/holdings/",
    response_model=AccountHoldingsSnapshotResponse,
    summary="Get account holdings snapshot",
    description=(
        "Return one account holdings snapshot. When the account exists but no holdings "
        "snapshot matches the request, the response is 200 with an empty holdings list."
    ),
    operation_id="getAccountHoldings",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_holdings_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(
            description="Snapshot ordering used when holdings_date is omitted.",
        ),
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
                "When true, include asset.uid, asset_identifier, and current_snapshot labels "
                "when the asset registry rows are available."
            ),
        ),
    ] = True,
    holdings_date: Annotated[
        dt.datetime | None,
        Query(
            description="Exact holdings snapshot timestamp to fetch. Use ISO 8601.",
        ),
    ] = None,
) -> AccountHoldingsSnapshotResponse:
    snapshot = get_account_holdings(
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        holdings_date=holdings_date,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.get(
    "/{account_uid}/holdings/by-fund/",
    response_model=AccountHoldingsByFundResponse,
    summary="Get account holdings grouped by virtual fund",
    description=(
        "Return one account holdings snapshot grouped by persisted virtual-fund "
        "allocation rows. The response uses VirtualFundHoldingsStorage for fund "
        "allocations and the selected source AccountHoldingsStorage snapshot to "
        "derive residual signed quantities. It does not rerun or apply the "
        "allocation planner."
    ),
    operation_id="getAccountHoldingsByFund",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid account holdings by fund request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
    },
)
def get_account_holdings_by_fund_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Snapshot ordering used when holdings_date is omitted."),
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
                "When true, include asset.uid, asset_identifier, and latest "
                "AssetSnapshotsStorage name/ticker labels for grouped holdings "
                "and residual rows."
            ),
        ),
    ] = True,
    holdings_date: Annotated[
        dt.datetime | None,
        Query(description="Exact source account holdings timestamp to fetch. Use ISO 8601."),
    ] = None,
) -> AccountHoldingsByFundResponse:
    try:
        snapshot = get_account_holdings_by_fund(
            account_uid=account_uid,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
            holdings_date=holdings_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.post(
    "/{account_uid}/add-holdings/",
    response_model=AccountHoldingsSnapshotResponse,
    summary="Add account holdings snapshot",
    description=(
        "Create or replace one account holdings snapshot and return it using the "
        "same response contract as the holdings read endpoint."
    ),
    operation_id="addAccountHoldings",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid holdings payload.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "A holdings snapshot already exists and overwrite is false.",
        },
    },
)
def add_account_holdings_by_uid(
    account_uid: str,
    payload: AccountAddHoldingsRequest,
) -> AccountHoldingsSnapshotResponse:
    try:
        snapshot = add_account_holdings(account_uid=account_uid, payload=payload)
    except ValueError as exc:
        if exc.__class__.__name__ == "AccountHoldingsSnapshotExistsError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.post(
    "/{account_uid}/add-target-positions/",
    response_model=AccountTargetPositionsSnapshotResponse,
    summary="Add account target positions snapshot",
    description=(
        "Create or replace one account target-position snapshot and return it using "
        "the same response contract as the target-positions read endpoint. Parent "
        "allocation rows are derived from the account uid in the path."
    ),
    operation_id="addAccountTargetPositions",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid target-position payload.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "A target-position snapshot already exists and overwrite is false.",
        },
    },
)
def add_account_target_positions_by_uid(
    account_uid: str,
    payload: AccountAddTargetPositionsRequest,
) -> AccountTargetPositionsSnapshotResponse:
    try:
        snapshot = add_account_target_positions(account_uid=account_uid, payload=payload)
    except ValueError as exc:
        if exc.__class__.__name__ == "AccountTargetPositionsSnapshotExistsError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.get(
    "/{account_uid}/target-positions/",
    response_model=AccountTargetPositionsSnapshotResponse,
    summary="Get account target positions snapshot",
    description=(
        "Return one account target-position snapshot. When the account exists but no "
        "target-position snapshot matches the request, the response is 200 with an "
        "empty positions list."
    ),
    operation_id="getAccountTargetPositions",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_target_positions_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(
            description="Position-set ordering used when target_positions_date is omitted.",
        ),
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
                "When true, include asset.uid, asset.unique_identifier, and the latest "
                "AssetSnapshotsStorage name/ticker labels when available."
            ),
        ),
    ] = True,
    target_positions_date: Annotated[
        dt.datetime | None,
        Query(
            description="Exact target-position snapshot timestamp to fetch. Use ISO 8601.",
        ),
    ] = None,
) -> AccountTargetPositionsSnapshotResponse:
    snapshot = get_account_target_positions(
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        target_positions_date=target_positions_date,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot
