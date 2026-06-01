from __future__ import annotations

from apps.v1.schemas.accounts import AccountListResponse
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


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=["Account"],
        row_model_name="GET /api/v1/account/",
    )


def _list_account_rows_response(context, **kwargs):
    from msm.services import list_account_rows_response

    return list_account_rows_response(context, **kwargs)


def _get_account_frontend_detail_summary(context, **kwargs):
    from msm.services import get_account_frontend_detail_summary

    return get_account_frontend_detail_summary(context, **kwargs)
