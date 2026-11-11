from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from apps.v1.identity import registry_write
from apps.v1.schemas.accounts import (
    AccountAddHoldingsRequest,
    AccountAddTargetPositionsRequest,
    Account,
    AccountCreate,
    AccountUpdate,
    AccountWithIncludes,
    AccountHoldingsByFundResponse,
    AccountHoldingsSnapshotResponse,
    AccountTargetAllocationCandidate,
    AccountTargetAllocationTargetSearchType,
    AccountTargetPositionsSnapshotResponse,
    AccountVirtualFundAllocationRequest,
    AccountVirtualFundAllocationResponse,
    AccountBulkDeleteResponse,
    AccountDeletePreflightResponse,
    AccountDeleteResponse,
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


def get_accounts_by_uids(
    *, uids: Sequence[str], include: Sequence[str] | None = None
) -> list[AccountWithIncludes]:
    """Return the accounts whose uid is listed, in request order; unknown uids are omitted.

    ``include`` names provider sidecar MetaTables keyed by `Account.uid` whose rows
    are attached under ``includes`` (ADR 0047 `include` hydration).
    """

    from apps.v1.services.includes import hydrate
    from apps.v1.services.lookups import normalize_lookup_uids, rows_by_uids
    from msm.models import AccountTable

    runtime = _get_runtime()
    rows = rows_by_uids(runtime.context, model=AccountTable, uids=normalize_lookup_uids(uids))
    return hydrate(
        runtime.context,
        model_cls=AccountWithIncludes,
        core_model=AccountTable,
        items=[Account.model_validate(row) for row in rows],
        include=include,
    )


@registry_write("account", "create")
def create_account(*, payload: AccountCreate) -> Account:
    """Create one account row through the typed row API (ADR 0047: the Markets API is the boundary)."""

    _get_runtime()
    return Account.create(payload)


@registry_write("account", "update")
def update_account(*, uid: str, payload: AccountUpdate) -> Account | None:
    if get_account(uid=uid) is None:
        return None
    return Account.update(uid, payload)


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


@registry_write("account", "add:account-holdings")
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


@registry_write("account", "add:account-target-positions")
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


def allocate_account_virtual_funds(
    *,
    account_uid: str,
    payload: AccountVirtualFundAllocationRequest,
) -> AccountVirtualFundAllocationResponse | None:
    """Plan the snapshot's virtual-fund allocation; write it only when ``payload.apply``."""

    if payload.apply:
        return apply_account_virtual_fund_allocation(account_uid=account_uid, payload=payload)
    return _run_account_virtual_fund_allocation(account_uid=account_uid, payload=payload)


@registry_write("account", "apply:account-virtual-fund-allocation")
def apply_account_virtual_fund_allocation(
    *,
    account_uid: str,
    payload: AccountVirtualFundAllocationRequest,
) -> AccountVirtualFundAllocationResponse | None:
    return _run_account_virtual_fund_allocation(account_uid=account_uid, payload=payload)


def _run_account_virtual_fund_allocation(
    *,
    account_uid: str,
    payload: AccountVirtualFundAllocationRequest,
) -> AccountVirtualFundAllocationResponse | None:
    from msm.services.accounts import account_allocation_policy

    runtime = _get_virtual_fund_allocation_runtime()
    result = _allocate_account_holdings_set(
        runtime.context,
        account_uid=account_uid,
        holdings_set_uid=payload.holdings_set_uid,
        valuation_asset_uid=payload.valuation_asset_uid,
        position_set_uid=payload.position_set_uid,
        allocation_policy=account_allocation_policy(
            mode=payload.allocation_policy.mode,
            stale_data_policy=payload.allocation_policy.stale_data_policy,
        ),
        portfolio_weights_reader=_portfolio_weights_reader(runtime.context),
        apply=payload.apply,
    )
    if result is None:
        return None
    return AccountVirtualFundAllocationResponse.model_validate(result)


def search_account_target_allocation_targets(
    *,
    search: str = "",
    target_type: AccountTargetAllocationTargetSearchType = "all",
    limit: int = 25,
    offset: int = 0,
    include_retired: bool = False,
) -> dict[str, object]:
    runtime = _get_target_allocation_candidates_runtime()
    response = _search_account_target_allocation_candidates(
        runtime.context,
        search=search,
        target_type=target_type,
        limit=limit,
        offset=offset,
        include_retired=include_retired,
    )
    return {
        "count": int(response["count"]),
        "results": [
            AccountTargetAllocationCandidate.model_validate(row) for row in response["results"]
        ],
    }


@registry_write("account", "delete")
def delete_account(*, uid: str) -> AccountDeleteResponse | None:
    """Delete one account with its whole history (ADR 0050)."""

    from msm.services import delete_account as delete_account_record

    runtime = _get_delete_runtime()
    deleted = delete_account_record(runtime.context, uid=uid)
    if deleted is None:
        return None
    return AccountDeleteResponse.model_validate(deleted)


@registry_write("account", "bulk-delete")
def bulk_delete_accounts(*, uids: list[str]) -> AccountBulkDeleteResponse:
    from msm.services import bulk_delete_accounts as bulk_delete_account_records

    runtime = _get_delete_runtime()
    return AccountBulkDeleteResponse.model_validate(
        bulk_delete_account_records(runtime.context, uids=uids)
    )


def preflight_bulk_delete_accounts(*, uids: list[str]) -> AccountDeletePreflightResponse:
    from msm.services import preflight_bulk_delete_accounts as preflight_account_records

    runtime = _get_delete_runtime()
    return AccountDeletePreflightResponse.model_validate(
        preflight_account_records(runtime.context, uids=uids)
    )


def _get_delete_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "AccountHoldingsSet",
            "AccountHoldingsStorage",
            "AccountTargetAllocation",
            "PositionSet",
            "TargetPositionsStorage",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
            "OrderManager",
            "OrdersStorage",
            "TradesStorage",
            "OrderEventsStorage",
        ],
        row_model_name="DELETE /api/v1/account/{uid}/",
    )


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


def _get_virtual_fund_allocation_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_portfolio_runtime

    return resolve_apps_v1_portfolio_runtime(
        models=[
            "Account",
            "AccountHoldingsSet",
            "AccountHoldingsStorage",
            "AccountTargetAllocation",
            "PositionSet",
            "TargetPositionsStorage",
            "Asset",
            "Portfolio",
            "PortfolioDatasetAvailability",
            "SignalMetadata",
            "PortfolioWeightsStorage",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
        ],
        row_model_name="POST /api/v1/account/{account_uid}/virtual-fund-allocations/",
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


def _allocate_account_holdings_set(context, **kwargs):
    from msm.services.accounts import allocate_account_holdings_set

    return allocate_account_holdings_set(context, **kwargs)


def _portfolio_weights_reader(context):
    """Each target portfolio's latest weights at or before a time, from its catalogued table."""

    from msm_portfolios.services import latest_portfolio_weights

    def read(portfolio_identifiers, valuation_time):
        return latest_portfolio_weights(
            list(portfolio_identifiers),
            weights_date=valuation_time,
            as_of=True,
            repository_context=context,
        )

    return read
