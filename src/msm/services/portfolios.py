from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import String, cast, func, or_, select

from msm.api.base import operation_result_rows
from msm.models import PortfolioGroupMembershipTable, PortfolioGroupTable, PortfolioTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.base import compile_markets_statement, execute_markets_operation
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


def list_portfolio_group_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    unique_identifier: str | None = None,
    display_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    statement = select(PortfolioGroupTable)
    if unique_identifier not in (None, ""):
        statement = statement.where(PortfolioGroupTable.unique_identifier == unique_identifier)
    if display_name not in (None, ""):
        statement = statement.where(PortfolioGroupTable.display_name == display_name)
    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(PortfolioGroupTable.uid, String)).like(needle),
                func.lower(PortfolioGroupTable.unique_identifier).like(needle),
                func.lower(PortfolioGroupTable.display_name).like(needle),
            )
        )
    statement = statement.order_by(
        func.lower(PortfolioGroupTable.display_name),
        func.lower(PortfolioGroupTable.unique_identifier),
        PortfolioGroupTable.uid,
    )
    return _collection_page(
        context,
        statement=statement,
        limit=limit,
        offset=offset,
    )


def list_portfolios_for_group_response(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    statement = (
        select(PortfolioTable)
        .join(
            PortfolioGroupMembershipTable,
            PortfolioGroupMembershipTable.portfolio_uid == PortfolioTable.uid,
        )
        .where(PortfolioGroupMembershipTable.portfolio_group_uid == portfolio_group_uid)
        .order_by(func.lower(PortfolioTable.unique_identifier), PortfolioTable.uid)
    )
    return _collection_page(
        context,
        statement=statement,
        limit=limit,
        offset=offset,
    )


def list_portfolio_groups_for_portfolio_response(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    statement = (
        select(PortfolioGroupTable)
        .join(
            PortfolioGroupMembershipTable,
            PortfolioGroupMembershipTable.portfolio_group_uid == PortfolioGroupTable.uid,
        )
        .where(PortfolioGroupMembershipTable.portfolio_uid == portfolio_uid)
        .order_by(func.lower(PortfolioGroupTable.display_name), PortfolioGroupTable.uid)
    )
    return _collection_page(
        context,
        statement=statement,
        limit=limit,
        offset=offset,
    )


def _collection_page(
    context: MarketsRepositoryContext,
    *,
    statement: Any,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    count_rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                select(func.count().label("count")).select_from(statement.subquery()),
                context=context,
                operation="select",
            ),
            context=context,
        )
    )
    rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement.limit(limit).offset(offset),
                context=context,
                operation="select",
            ),
            context=context,
        )
    )
    return {"count": int(count_rows[0]["count"]) if count_rows else 0, "results": rows}


def update_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.update_portfolio_group(context, **kwargs)


def delete_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio_group(context, **kwargs)


def bulk_delete_portfolio_groups(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None = None,
    unique_identifiers: Sequence[str] | None = None,
    table_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    """Delete every selected portfolio group that exists, in one statement, and report the
    rest (issue 128). Their memberships go by ``CASCADE``."""

    from msm.models import PortfolioGroupTable
    from msm.services.bulk_deletion import bulk_delete_rows

    target_uids = _portfolio_group_target_uids(
        context,
        uids=uids,
        unique_identifiers=unique_identifiers,
    )
    return bulk_delete_rows(
        context,
        model=PortfolioGroupTable,
        uids=target_uids,
        label="Portfolio group",
        plural="portfolio groups",
        table_blockers=table_blockers,
    )


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
    """Delete the selected memberships in one statement and report the rest (issue 152).

    The selection is the memberships of ``uids``, and those whose group is in
    ``portfolio_group_uids`` and whose portfolio is in ``portfolio_uids``, where an empty
    filter does not narrow the match. The database resolves it, with no row cap. The
    answer is the bulk-delete envelope: each deleted membership in ``deleted``, and each
    of ``uids`` that was not deleted, or whose fate the call cannot tell, with the reason,
    in ``failed``. ``deleted_count`` counts only the deletes the call can confirm.

    MetaTables returns at most 10,000 of the deleted rows. Past that, ``deleted_count`` is
    its count of them all and ``deleted`` lists those it returned. A delete MetaTables
    does not answer is confirmed with one read of what still matches the selection.
    """

    from metatables import TransferOutcomeUnknown

    from msm.services.bulk_deletion import bulk_delete_response, canonical_uid

    def selected(values: Sequence[str] | None) -> list[str]:
        return list(dict.fromkeys(canonical_uid(uid) for uid in values or [] if str(uid).strip()))

    selection = {
        "uids": selected(uids),
        "portfolio_group_uids": selected(portfolio_group_uids),
        "portfolio_uids": selected(portfolio_uids),
    }
    explicit = selection["uids"]
    if not any(selection.values()):
        return _membership_response([], {}, explicit)
    try:
        result = portfolio_repository.delete_portfolio_group_memberships(context, **selection)
    except TransferOutcomeUnknown as error:
        return _confirm_unknown_membership_delete(context, selection, error)
    deleted = [{"uid": canonical_uid(row["uid"])} for row in operation_result_rows(result)]
    found = {row["uid"] for row in deleted}
    total = max(len(deleted), int(result.get("row_count") or 0))
    if total == len(deleted):
        failed = {uid: f"{_label(uid)} was not found." for uid in explicit if uid not in found}
        return bulk_delete_response(
            deleted, failed, explicit, singular=_MEMBERSHIP.lower(), plural=_MEMBERSHIPS
        )
    # The statement deleted every match, and MetaTables returned only part of them: a
    # selected uid it did not return is gone, deleted now or never there.
    failed = {uid: _unreturned_reason(uid) for uid in explicit if uid not in found}
    detail = (
        f"Deleted {total} {_MEMBERSHIPS}; MetaTables returned {len(deleted)} of them, which "
        "`deleted` lists."
    )
    if failed:
        detail += f" The call cannot tell the outcome of {len(failed)} selected."
    return _membership_response(deleted, failed, explicit, detail=detail, deleted_count=total)


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


_MEMBERSHIP = "Portfolio group membership"
_MEMBERSHIPS = "portfolio group memberships"


def _confirm_unknown_membership_delete(
    context: MarketsRepositoryContext,
    selection: Mapping[str, list[str]],
    error: Exception,
) -> dict[str, Any]:
    """After the membership delete got no answer: one read of what still matches.

    `msm.services.bulk_deletion.confirm_unread_delete` reads only the selected uids; a
    filter selection also matches rows no one named, so this reads the selection itself.
    Nothing left does not prove the delete committed, since the selection may have matched
    nothing, so no membership is reported deleted then. A membership left may still go:
    the server's transaction can outlive the request.
    """

    from mainsequence.client.exceptions import ApiError
    from mainsequence.logconf import logger
    from metatables import ApiResolutionError
    from metatables.contracts.transfer import TransferError

    from msm.services.bulk_deletion import (
        gone_after_unanswered_delete_reason,
        unconfirmed_delete_reason,
        unknown_delete_reason,
    )

    explicit = selection["uids"]
    logger.warning("A membership delete got no answer; reading its selection again.", error=str(error))
    try:
        remaining = portfolio_repository.matching_portfolio_group_membership_uids(
            context, **selection
        )
    except (ApiError, ApiResolutionError, TransferError) as read_error:
        logger.warning("Reading the selection of a delete without an answer failed.", error=str(read_error))
        failed = {
            uid: unconfirmed_delete_reason(_label(uid), noun=_MEMBERSHIP, error=read_error)
            for uid in explicit
        }
        detail = (
            "MetaTables did not answer the delete, and reading the selection again failed "
            f"too; the call cannot tell which {_MEMBERSHIPS} it deleted. The call may be "
            "retried."
        )
        return _membership_response([], failed, explicit, detail=detail)
    if not remaining:
        failed = {uid: gone_after_unanswered_delete_reason(_label(uid)) for uid in explicit}
        detail = (
            "MetaTables did not answer the delete, and nothing matching the selection "
            f"remains; the call cannot tell how many {_MEMBERSHIPS} it deleted."
        )
        return _membership_response([], failed, explicit, detail=detail)
    left = set(remaining)
    order = list(dict.fromkeys([*explicit, *remaining]))
    failed = {
        uid: (
            unknown_delete_reason(_label(uid), noun=_MEMBERSHIP)
            if uid in left
            else f"{_label(uid)} was not found."
        )
        for uid in order
    }
    detail = (
        f"MetaTables did not answer the delete, and {_MEMBERSHIPS} matching the selection "
        "still existed when read again; `failed` lists them. The call may be retried."
    )
    return _membership_response([], failed, order, detail=detail)


def _label(uid: str) -> str:
    return f"{_MEMBERSHIP} {uid}"


def _unreturned_reason(uid: str) -> str:
    """Why a selected uid the delete did not return, when MetaTables returned only part of
    the deleted rows, is not reported deleted."""

    return (
        f"{_label(uid)}: it no longer exists. This call cannot tell whether it deleted it or "
        "it never existed."
    )


def _membership_response(
    deleted: Sequence[dict[str, Any]],
    failed: dict[str, str],
    order: Sequence[str],
    *,
    detail: str | None = None,
    deleted_count: int | None = None,
) -> dict[str, Any]:
    from msm.services.bulk_deletion import bulk_delete_response

    response = bulk_delete_response(
        deleted, failed, order, singular=_MEMBERSHIP.lower(), plural=_MEMBERSHIPS
    )
    if detail is not None:
        response["detail"] = detail
    if deleted_count is not None:
        response["deleted_count"] = deleted_count
    return response


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


__all__ = [
    "bulk_delete_portfolio_group_memberships",
    "bulk_delete_portfolio_groups",
    "create_portfolio",
    "create_portfolio_group",
    "delete_portfolio_group",
    "delete_portfolio_group_membership",
    "delete_portfolio_group_membership_by_pair",
    "get_portfolio_by_unique_identifier",
    "get_portfolio_group_by_uid",
    "get_portfolio_group_by_unique_identifier",
    "list_portfolio_groups_for_portfolio",
    "list_portfolio_groups_for_portfolio_response",
    "list_portfolio_groups_for_portfolio_unique_identifier",
    "list_portfolio_group_rows_response",
    "list_portfolios_for_group",
    "list_portfolios_for_group_response",
    "list_portfolios_for_group_unique_identifier",
    "search_portfolio_group_memberships",
    "search_portfolio_groups",
    "search_portfolios",
    "update_portfolio",
    "update_portfolio_group",
    "upsert_portfolio_group",
    "upsert_portfolio_group_membership",
]
