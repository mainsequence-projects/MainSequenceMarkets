from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.v1.schemas.portfolio_groups import (
    Portfolio,
    PortfolioGroup,
    PortfolioGroupDeleteResponse,
    PortfolioGroupMembership,
)
from msm.api.base import operation_result_rows


def list_portfolio_groups(
    *,
    search: str = "",
    unique_identifier: str | None = None,
    display_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PortfolioGroup]:
    runtime = _get_runtime()
    result = _search_portfolio_groups(
        runtime.context,
        search=search,
        unique_identifier=unique_identifier,
        display_name=display_name,
        limit=limit,
        offset=offset,
    )
    return [PortfolioGroup.model_validate(row) for row in operation_result_rows(result)]


def get_portfolio_group(*, uid: str) -> PortfolioGroup | None:
    runtime = _get_runtime()
    result = _get_portfolio_group_by_uid(runtime.context, uid=uid)
    rows = operation_result_rows(result)
    if not rows:
        return None
    return PortfolioGroup.model_validate(rows[0])


def create_portfolio_group(*, payload: Mapping[str, Any]) -> PortfolioGroup:
    runtime = _get_runtime()
    result = _upsert_portfolio_group(runtime.context, **dict(payload))
    rows = operation_result_rows(result)
    if not rows:
        raise LookupError("Portfolio group upsert did not return a row.")
    return PortfolioGroup.model_validate(rows[0])


def update_portfolio_group(*, uid: str, payload: Mapping[str, Any]) -> PortfolioGroup | None:
    runtime = _get_runtime()
    result = _update_portfolio_group(runtime.context, uid=uid, **dict(payload))
    rows = operation_result_rows(result)
    if not rows:
        return None
    return PortfolioGroup.model_validate(rows[0])


def delete_portfolio_group(*, uid: str) -> PortfolioGroupDeleteResponse:
    runtime = _get_runtime()
    result = _bulk_delete_portfolio_groups(runtime.context, uids=[uid])
    return PortfolioGroupDeleteResponse.model_validate(result)


def bulk_delete_portfolio_groups(*, payload: Mapping[str, Any]) -> PortfolioGroupDeleteResponse:
    runtime = _get_runtime()
    result = _bulk_delete_portfolio_groups(
        runtime.context,
        uids=[str(uid) for uid in payload.get("uids", [])],
        unique_identifiers=list(payload.get("unique_identifiers", [])),
    )
    return PortfolioGroupDeleteResponse.model_validate(result)


def add_portfolio_to_group(
    *,
    portfolio_group_uid: str,
    payload: Mapping[str, Any],
) -> PortfolioGroupMembership:
    _get_runtime()
    return PortfolioGroup.add_portfolio(
        portfolio_group_uid=portfolio_group_uid,
        portfolio_uid=payload.get("portfolio_uid"),
        portfolio_unique_identifier=payload.get("portfolio_unique_identifier"),
    )


def remove_portfolio_from_group(
    *,
    portfolio_group_uid: str,
    portfolio_uid: str,
) -> PortfolioGroupDeleteResponse:
    _get_runtime()
    result = PortfolioGroup.remove_portfolio(
        portfolio_group_uid=portfolio_group_uid,
        portfolio_uid=portfolio_uid,
    )
    return PortfolioGroupDeleteResponse.model_validate(result)


def bulk_delete_portfolio_group_memberships(
    *,
    payload: Mapping[str, Any],
) -> PortfolioGroupDeleteResponse:
    runtime = _get_runtime()
    result = _bulk_delete_portfolio_group_memberships(
        runtime.context,
        uids=[str(uid) for uid in payload.get("uids", [])],
        portfolio_group_uids=[str(uid) for uid in payload.get("portfolio_group_uids", [])],
        portfolio_uids=[str(uid) for uid in payload.get("portfolio_uids", [])],
    )
    return PortfolioGroupDeleteResponse.model_validate(result)


def list_portfolios_in_group(
    *,
    portfolio_group_uid: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Portfolio]:
    _get_runtime()
    return PortfolioGroup.get_portfolios(
        portfolio_group_uid=portfolio_group_uid,
        limit=limit,
        offset=offset,
    )


def list_groups_for_portfolio(
    *,
    portfolio_uid: str,
    limit: int = 50,
    offset: int = 0,
) -> list[PortfolioGroup]:
    _get_runtime()
    return PortfolioGroup.get_groups_for_portfolio(
        portfolio_uid=portfolio_uid,
        limit=limit,
        offset=offset,
    )


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_portfolio_runtime

    return resolve_apps_v1_portfolio_runtime(
        models=[
            "Calendar",
            "IndexType",
            "Index",
            "SignalMetadata",
            "Portfolio",
            "PortfolioGroup",
            "PortfolioGroupMembership",
        ],
        row_model_name="PortfolioGroup apps/v1",
    )


def _search_portfolio_groups(context, **kwargs):
    from msm.services import search_portfolio_groups

    return search_portfolio_groups(context, **kwargs)


def _get_portfolio_group_by_uid(context, **kwargs):
    from msm.services import get_portfolio_group_by_uid

    return get_portfolio_group_by_uid(context, **kwargs)


def _upsert_portfolio_group(context, **kwargs):
    from msm.services import upsert_portfolio_group

    return upsert_portfolio_group(context, **kwargs)


def _update_portfolio_group(context, **kwargs):
    from msm.services import update_portfolio_group

    return update_portfolio_group(context, **kwargs)


def _bulk_delete_portfolio_groups(context, **kwargs):
    from msm.services import bulk_delete_portfolio_groups

    return bulk_delete_portfolio_groups(context, **kwargs)


def _bulk_delete_portfolio_group_memberships(context, **kwargs):
    from msm.services import bulk_delete_portfolio_group_memberships

    return bulk_delete_portfolio_group_memberships(context, **kwargs)
