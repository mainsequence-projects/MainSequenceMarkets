from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext
from msm.repositories import portfolios as portfolio_repository


def create_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.create_portfolio(context, **kwargs)


def get_portfolio_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.get_portfolio_by_unique_identifier(context, **kwargs)


def search_portfolios(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.search_portfolios(context, **kwargs)


def update_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.update_portfolio(context, **kwargs)


def delete_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio(context, **kwargs)


def create_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.create_portfolio_group(context, **kwargs)


def upsert_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.upsert_portfolio_group(context, **kwargs)


def get_portfolio_group_by_uid(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.get_portfolio_group_by_uid(context, **kwargs)


def get_portfolio_group_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.get_portfolio_group_by_unique_identifier(context, **kwargs)


def search_portfolio_groups(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.search_portfolio_groups(context, **kwargs)


def update_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.update_portfolio_group(context, **kwargs)


def delete_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio_group(context, **kwargs)


def bulk_delete_portfolio_groups(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None = None,
    unique_identifiers: Sequence[str] | None = None,
) -> dict[str, Any]:
    target_uids = _portfolio_group_target_uids(
        context,
        uids=uids,
        unique_identifiers=unique_identifiers,
    )
    deleted_count = 0
    for uid in dict.fromkeys(target_uids):
        if _delete_existing_portfolio_group(context, uid=uid):
            deleted_count += 1
    detail = (
        "No portfolio groups matched the deletion request."
        if deleted_count == 0
        else f"Deleted {deleted_count} portfolio group{'s' if deleted_count != 1 else ''}."
    )
    return {"detail": detail, "deleted_count": deleted_count}


def upsert_portfolio_group_membership(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.upsert_portfolio_group_membership(context, **kwargs)


def search_portfolio_group_memberships(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.search_portfolio_group_memberships(context, **kwargs)


def delete_portfolio_group_membership(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio_group_membership(context, **kwargs)


def delete_portfolio_group_membership_by_pair(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio_group_membership_by_pair(context, **kwargs)


def bulk_delete_portfolio_group_memberships(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None = None,
    portfolio_group_uids: Sequence[str] | None = None,
    portfolio_uids: Sequence[str] | None = None,
) -> dict[str, Any]:
    target_uids = _portfolio_group_membership_target_uids(
        context,
        uids=uids,
        portfolio_group_uids=portfolio_group_uids,
        portfolio_uids=portfolio_uids,
    )
    deleted_count = 0
    for uid in dict.fromkeys(target_uids):
        if _delete_existing_portfolio_group_membership(context, uid=uid):
            deleted_count += 1
    detail = (
        "No portfolio group memberships matched the deletion request."
        if deleted_count == 0
        else (
            f"Deleted {deleted_count} portfolio group "
            f"membership{'s' if deleted_count != 1 else ''}."
        )
    )
    return {"detail": detail, "deleted_count": deleted_count}


def list_portfolios_for_group(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.list_portfolios_for_group(context, **kwargs)


def list_portfolios_for_group_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_unique_identifier: str,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    group = _first_operation_row(
        get_portfolio_group_by_unique_identifier(
            context,
            unique_identifier=portfolio_group_unique_identifier,
        )
    )
    if group is None:
        raise LookupError(f"PortfolioGroup {portfolio_group_unique_identifier!r} was not found.")
    return list_portfolios_for_group(
        context,
        portfolio_group_uid=str(group["uid"]),
        limit=limit,
        offset=offset,
    )


def list_portfolio_groups_for_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.list_portfolio_groups_for_portfolio(context, **kwargs)


def list_portfolio_groups_for_portfolio_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    portfolio_unique_identifier: str,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    portfolio = _first_operation_row(
        get_portfolio_by_unique_identifier(
            context,
            unique_identifier=portfolio_unique_identifier,
        )
    )
    if portfolio is None:
        raise LookupError(f"Portfolio {portfolio_unique_identifier!r} was not found.")
    return list_portfolio_groups_for_portfolio(
        context,
        portfolio_uid=str(portfolio["uid"]),
        limit=limit,
        offset=offset,
    )


def _portfolio_group_target_uids(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None,
    unique_identifiers: Sequence[str] | None,
) -> list[str]:
    target_uids = [str(uid) for uid in (uids or []) if str(uid).strip()]
    for unique_identifier in unique_identifiers or []:
        if not str(unique_identifier).strip():
            continue
        row = _first_operation_row(
            get_portfolio_group_by_unique_identifier(
                context,
                unique_identifier=str(unique_identifier),
            )
        )
        if row is not None:
            target_uids.append(str(row["uid"]))
    return target_uids


def _portfolio_group_membership_target_uids(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None,
    portfolio_group_uids: Sequence[str] | None,
    portfolio_uids: Sequence[str] | None,
) -> list[str]:
    target_uids = [str(uid) for uid in (uids or []) if str(uid).strip()]
    if portfolio_group_uids or portfolio_uids:
        group_filter = {str(uid) for uid in (portfolio_group_uids or []) if str(uid).strip()}
        portfolio_filter = {str(uid) for uid in (portfolio_uids or []) if str(uid).strip()}
        rows = operation_result_rows(
            search_portfolio_group_memberships(
                context,
                limit=5000,
            )
        )
        for row in rows:
            if not _membership_row_matches(
                row,
                portfolio_group_uids=group_filter,
                portfolio_uids=portfolio_filter,
            ):
                continue
            target_uids.append(str(row["uid"]))
    return target_uids


def _membership_row_matches(
    row: Mapping[str, Any],
    *,
    portfolio_group_uids: set[str],
    portfolio_uids: set[str],
) -> bool:
    if portfolio_group_uids and str(row.get("portfolio_group_uid")) not in portfolio_group_uids:
        return False
    if portfolio_uids and str(row.get("portfolio_uid")) not in portfolio_uids:
        return False
    return True


def _delete_existing_portfolio_group(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    if _first_operation_row(get_portfolio_group_by_uid(context, uid=uid)) is None:
        return False
    delete_portfolio_group(context, uid=uid)
    return True


def _delete_existing_portfolio_group_membership(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    existing_rows = operation_result_rows(
        search_portfolio_group_memberships(
            context,
            uid=uid,
            limit=1,
        )
    )
    if not existing_rows:
        return False
    delete_portfolio_group_membership(context, uid=uid)
    return True


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


__all__ = [
    "bulk_delete_portfolio_group_memberships",
    "bulk_delete_portfolio_groups",
    "create_portfolio",
    "create_portfolio_group",
    "delete_portfolio",
    "delete_portfolio_group",
    "delete_portfolio_group_membership",
    "delete_portfolio_group_membership_by_pair",
    "get_portfolio_by_unique_identifier",
    "get_portfolio_group_by_uid",
    "get_portfolio_group_by_unique_identifier",
    "list_portfolio_groups_for_portfolio",
    "list_portfolio_groups_for_portfolio_unique_identifier",
    "list_portfolios_for_group",
    "list_portfolios_for_group_unique_identifier",
    "search_portfolio_group_memberships",
    "search_portfolio_groups",
    "search_portfolios",
    "update_portfolio",
    "update_portfolio_group",
    "upsert_portfolio_group",
    "upsert_portfolio_group_membership",
]
