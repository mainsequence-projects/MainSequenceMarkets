from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from apps.v1.schemas.accounts import AccountHoldingsSnapshotResponse, AccountListResponse
from apps.v1.schemas.common import ErrorResponse, FrontEndDetailSummary
from apps.v1.services.accounts import get_account_holdings, get_account_summary, list_accounts

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
    return list_accounts(search=search, limit=limit, offset=offset)


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
                "When true, include asset.uid, asset.figi, and current_snapshot labels "
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
