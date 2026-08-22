from __future__ import annotations

import datetime as dt

from apps.v1.schemas.accounts import (
    AccountAddHoldingsRequest,
    AccountAddTargetPositionsRequest,
    Account,
    AccountHoldingsByFundResponse,
    AccountHoldingsSnapshotResponse,
    AccountTargetAllocationCandidate,
    AccountTargetAllocationTargetSearchType,
    AccountTargetPositionsSnapshotResponse,
)
from apps.v1.schemas.common import FrontEndDetailSummary


def list_accounts(
    *,
    search: str = "",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, object]:
    runtime = _get_runtime()
    response = _list_account_rows_response(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [Account.model_validate(row) for row in response["results"]],
    }


def get_account(*, uid: str) -> Account | None:
    runtime = _get_runtime()
    rows = _operation_result_rows(_get_account_by_uid(runtime.context, uid=uid))
    if not rows:
        return None
    return Account.model_validate(rows[0])


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


def get_account_holdings_by_fund(
    *,
    account_uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | None = None,
) -> AccountHoldingsByFundResponse | None:
    runtime = _get_holdings_by_fund_runtime()
    snapshot = _get_account_holdings_by_fund_response(
        runtime.context,
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        holdings_date=holdings_date,
    )
    if snapshot is None:
        return None
    return AccountHoldingsByFundResponse.model_validate(snapshot)


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


def add_account_target_positions(
    *,
    account_uid: str,
    payload: AccountAddTargetPositionsRequest,
) -> AccountTargetPositionsSnapshotResponse | None:
    runtime = _get_target_positions_runtime()
    snapshot = _add_account_target_positions_snapshot_response(
        runtime.context,
        account_uid=account_uid,
        target_positions_date=payload.target_positions_date,
        overwrite=payload.overwrite,
        positions=[position.model_dump() for position in payload.positions],
        include_asset_detail=True,
    )
    if snapshot is None:
        return None
    return AccountTargetPositionsSnapshotResponse.model_validate(snapshot)


def search_account_target_allocation_targets(
    *,
    search: str = "",
    target_type: AccountTargetAllocationTargetSearchType = "all",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, object]:
    runtime = _get_target_allocation_candidates_runtime()
    response = _search_account_target_allocation_candidates(
        runtime.context,
        search=search,
        target_type=target_type,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [
            AccountTargetAllocationCandidate.model_validate(row) for row in response["results"]
        ],
    }


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


def _get_holdings_by_fund_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "AccountHoldingsSet",
            "AccountHoldingsStorage",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
            "Asset",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/account/{account_uid}/holdings/by-fund/",
    )


def _get_target_positions_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "AccountAllocationModel",
            "AccountTargetAllocation",
            "PositionSet",
            "Portfolio",
            "TargetPositionsStorage",
            "Asset",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/account/{account_uid}/target-positions/",
    )


def _get_target_allocation_candidates_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Asset",
            "AssetSnapshotsStorage",
            "Portfolio",
        ],
        row_model_name="GET /api/v1/account/target-allocation/targets/",
    )


def _list_account_rows_response(context, **kwargs):
    from msm.services import list_account_rows_response

    return list_account_rows_response(context, **kwargs)


def _get_account_frontend_detail_summary(context, **kwargs):
    from msm.services import get_account_frontend_detail_summary

    return get_account_frontend_detail_summary(context, **kwargs)


def _get_account_by_uid(context, **kwargs):
    from msm.services import get_account_by_uid

    return get_account_by_uid(context, **kwargs)


def _operation_result_rows(value):
    from msm.api.base import operation_result_rows

    return operation_result_rows(value)


def _get_account_holdings_snapshot_response(context, **kwargs):
    from msm.services import get_account_holdings_snapshot_response

    return get_account_holdings_snapshot_response(context, **kwargs)


def _get_account_holdings_by_fund_response(context, **kwargs):
    from msm.services import get_account_holdings_by_fund_response

    return get_account_holdings_by_fund_response(context, **kwargs)


def _add_account_holdings_snapshot_response(context, **kwargs):
    from msm.services import add_account_holdings_snapshot_response

    return add_account_holdings_snapshot_response(context, **kwargs)


def _get_account_target_positions_snapshot_response(context, **kwargs):
    from msm.services import get_account_target_positions_snapshot_response

    return get_account_target_positions_snapshot_response(context, **kwargs)


def _add_account_target_positions_snapshot_response(context, **kwargs):
    from msm.services import add_account_target_positions_snapshot_response

    return add_account_target_positions_snapshot_response(context, **kwargs)


def _search_account_target_allocation_candidates(context, **kwargs):
    from msm.services import search_account_target_allocation_candidates

    return search_account_target_allocation_candidates(context, **kwargs)
