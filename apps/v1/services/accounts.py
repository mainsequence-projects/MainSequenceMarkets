from __future__ import annotations

import datetime as dt

from apps.v1.schemas.accounts import (
    AccountAddHoldingsRequest,
    AccountHoldingsSnapshotResponse,
    AccountListResponse,
    AccountTargetPositionsSnapshotResponse,
)
from apps.v1.schemas.common import FrontEndDetailSummary


def list_accounts(
    *,
    search: str = "",
    limit: int = 25,
    offset: int = 0,
) -> AccountListResponse:
    runtime = _get_runtime()
    response = _list_account_rows_response(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AccountListResponse.model_validate(response)


def get_account_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    summary = _get_account_frontend_detail_summary(runtime.context, uid=uid)
    if summary is None:
        return None
    return FrontEndDetailSummary.model_validate(summary)


def get_account_holdings(
    *,
    account_uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | None = None,
) -> AccountHoldingsSnapshotResponse | None:
    runtime = _get_holdings_runtime()
    snapshot = _get_account_holdings_snapshot_response(
        runtime.context,
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        holdings_date=holdings_date,
    )
    if snapshot is None:
        return None
    return AccountHoldingsSnapshotResponse.model_validate(snapshot)


def add_account_holdings(
    *,
    account_uid: str,
    payload: AccountAddHoldingsRequest,
) -> AccountHoldingsSnapshotResponse | None:
    runtime = _get_holdings_runtime()
    snapshot = _add_account_holdings_snapshot_response(
        runtime.context,
        account_uid=account_uid,
        holdings_date=payload.holdings_date,
        overwrite=payload.overwrite,
        positions=payload.positions,
        include_asset_detail=True,
    )
    if snapshot is None:
        return None
    return AccountHoldingsSnapshotResponse.model_validate(snapshot)


def get_account_target_positions(
    *,
    account_uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    target_positions_date: dt.datetime | None = None,
) -> AccountTargetPositionsSnapshotResponse | None:
    runtime = _get_target_positions_runtime()
    snapshot = _get_account_target_positions_snapshot_response(
        runtime.context,
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        target_positions_date=target_positions_date,
    )
    if snapshot is None:
        return None
    return AccountTargetPositionsSnapshotResponse.model_validate(snapshot)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=["Account"],
        row_model_name="GET /api/v1/account/",
    )


def _get_holdings_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "Asset",
            "AccountHoldingsSet",
            "AccountHoldingsStorage",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/account/{account_uid}/holdings/",
    )


def _get_target_positions_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "AccountTargetAllocation",
            "PositionSet",
            "Portfolio",
            "TargetPositionsStorage",
            "Asset",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/account/{account_uid}/target-positions/",
    )


def _list_account_rows_response(context, **kwargs):
    from msm.services import list_account_rows_response

    return list_account_rows_response(context, **kwargs)


def _get_account_frontend_detail_summary(context, **kwargs):
    from msm.services import get_account_frontend_detail_summary

    return get_account_frontend_detail_summary(context, **kwargs)


def _get_account_holdings_snapshot_response(context, **kwargs):
    from msm.services import get_account_holdings_snapshot_response

    return get_account_holdings_snapshot_response(context, **kwargs)


def _add_account_holdings_snapshot_response(context, **kwargs):
    from msm.services import add_account_holdings_snapshot_response

    return add_account_holdings_snapshot_response(context, **kwargs)


def _get_account_target_positions_snapshot_response(context, **kwargs):
    from msm.services import get_account_target_positions_snapshot_response

    return get_account_target_positions_snapshot_response(context, **kwargs)
