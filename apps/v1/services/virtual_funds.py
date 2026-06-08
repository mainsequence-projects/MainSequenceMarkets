from __future__ import annotations

import datetime as dt

from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.virtual_funds import (
    VirtualFundDetailResponse,
    VirtualFundHoldingsSnapshotResponse,
    VirtualFundListResponse,
)


def list_virtual_funds(
    *,
    search: str = "",
    account_uid: str | None = None,
    portfolio_uid: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> VirtualFundListResponse:
    runtime = _get_runtime()
    response = _list_virtual_fund_rows_response(
        runtime.context,
        search=search,
        account_uid=account_uid,
        portfolio_uid=portfolio_uid,
        limit=limit,
        offset=offset,
    )
    return VirtualFundListResponse.model_validate(response)


def get_virtual_fund_detail(*, uid: str) -> VirtualFundDetailResponse | None:
    runtime = _get_runtime()
    detail = _get_virtual_fund_detail_response(runtime.context, uid=uid)
    if detail is None:
        return None
    return VirtualFundDetailResponse.model_validate(detail)


def get_virtual_fund_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    summary = _get_virtual_fund_frontend_detail_summary(runtime.context, uid=uid)
    if summary is None:
        return None
    return FrontEndDetailSummary.model_validate(summary)


def get_virtual_fund_holdings(
    *,
    uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | None = None,
) -> VirtualFundHoldingsSnapshotResponse | None:
    runtime = _get_holdings_runtime()
    snapshot = _get_virtual_fund_holdings_snapshot_response(
        runtime.context,
        uid=uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        holdings_date=holdings_date,
    )
    if snapshot is None:
        return None
    return VirtualFundHoldingsSnapshotResponse.model_validate(snapshot)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=["Account", "Portfolio", "VirtualFund"],
        row_model_name="GET /api/v1/virtualfund/",
    )


def _get_holdings_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Account",
            "Portfolio",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
            "Asset",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/virtualfund/{uid}/holdings/",
    )


def _list_virtual_fund_rows_response(context, **kwargs):
    from msm.services import list_virtual_fund_rows_response

    return list_virtual_fund_rows_response(context, **kwargs)


def _get_virtual_fund_detail_response(context, **kwargs):
    from msm.services import get_virtual_fund_detail_response

    return get_virtual_fund_detail_response(context, **kwargs)


def _get_virtual_fund_frontend_detail_summary(context, **kwargs):
    from msm.services import get_virtual_fund_frontend_detail_summary

    return get_virtual_fund_frontend_detail_summary(context, **kwargs)


def _get_virtual_fund_holdings_snapshot_response(context, **kwargs):
    from msm.services import get_virtual_fund_holdings_snapshot_response

    return get_virtual_fund_holdings_snapshot_response(context, **kwargs)
