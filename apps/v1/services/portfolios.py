from __future__ import annotations

import datetime as dt

from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.portfolios import (
    Portfolio,
    PortfolioBulkDeleteResponse,
    PortfolioDeleteResponse,
    PortfolioDetailResponse,
    PortfolioWeightsDeleteResponse,
    PortfolioWeightsSnapshotResponse,
)


def list_portfolios(
    *,
    search: str = "",
    calendar_uid: str | None = None,
    calendar_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    runtime = _get_runtime()
    response = _list_portfolio_rows_response(
        runtime.context,
        search=search,
        calendar_uid=calendar_uid,
        calendar_name=calendar_name,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [Portfolio.model_validate(row) for row in response["results"]],
    }


def get_portfolio_detail(*, uid: str) -> PortfolioDetailResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_detail_response(runtime.context, uid=uid)
    if response is None:
        return None
    return PortfolioDetailResponse.model_validate(response)


def get_portfolio_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    response = _get_portfolio_frontend_detail_summary(runtime.context, uid=uid)
    if response is None:
        return None
    return FrontEndDetailSummary.model_validate(response)


def get_portfolio_weights(
    *,
    uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    weights_date: dt.datetime | None = None,
) -> PortfolioWeightsSnapshotResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_weights_snapshot_response(
        runtime.context,
        uid=uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        weights_date=weights_date,
    )
    if response is None:
        return None
    return PortfolioWeightsSnapshotResponse.model_validate(response)


def delete_portfolio(*, uid: str) -> PortfolioDeleteResponse | None:
    runtime = _get_runtime()
    deleted = _delete_portfolio_record(runtime.context, uid=uid)
    if not deleted:
        return None
    return PortfolioDeleteResponse.model_validate(deleted)


def delete_portfolio_weights(
    *,
    uid: str,
    weights_date: dt.datetime | None = None,
) -> PortfolioWeightsDeleteResponse | None:
    runtime = _get_runtime()
    response = _delete_portfolio_weights(runtime.context, uid=uid, weights_date=weights_date)
    if response is None:
        return None
    return PortfolioWeightsDeleteResponse.model_validate(response)


def bulk_delete_portfolios(*, uids: list[str]) -> PortfolioBulkDeleteResponse:
    runtime = _get_runtime()
    response = _bulk_delete_portfolio_records(runtime.context, uids=uids)
    return PortfolioBulkDeleteResponse.model_validate(response)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_portfolio_runtime

    return resolve_apps_v1_portfolio_runtime(
        models=[
            "Portfolio",
            "Index",
            "Asset",
            "AssetSnapshotsStorage",
            "PortfolioMetadata",
            "PortfolioWeightsStorage",
            "VirtualFund",
        ],
        row_model_name="GET /api/v1/portfolio/",
    )


def _list_portfolio_rows_response(context, **kwargs):
    from msm_portfolios.services import list_portfolio_rows_response

    return list_portfolio_rows_response(context, **kwargs)


def _get_portfolio_detail_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_detail_response

    return get_portfolio_detail_response(context, **kwargs)


def _get_portfolio_frontend_detail_summary(context, **kwargs):
    from msm_portfolios.services import get_portfolio_frontend_detail_summary

    return get_portfolio_frontend_detail_summary(context, **kwargs)


def _get_portfolio_weights_snapshot_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_weights_snapshot_response

    return get_portfolio_weights_snapshot_response(context, **kwargs)


def _delete_portfolio_record(context, **kwargs):
    from msm_portfolios.services import delete_portfolio_record

    return delete_portfolio_record(context, **kwargs)


def _delete_portfolio_weights(context, **kwargs):
    from msm_portfolios.services import delete_portfolio_weights

    return delete_portfolio_weights(context, **kwargs)


def _bulk_delete_portfolio_records(context, **kwargs):
    from msm_portfolios.services import bulk_delete_portfolio_records

    return bulk_delete_portfolio_records(context, **kwargs)
