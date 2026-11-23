"""Delete accounts with their whole history (ADR 0050).

`Account.delete`, `Account.bulk_delete` and the Markets API account delete routes all
run these functions, so the same call removes the same rows under the runtime and
the remote backend.

Markets deletes only rows in its own tables. A table in another namespace loses rows
only through a foreign key it carries: a `CASCADE` key deletes its rows with their
parent, and a `RESTRICT` key refuses the whole delete.

A delete sends one read and one MetaTables transaction, and asks MetaTables for no
impact; only the bulk-delete preflight does (issue 91). The plan, the transaction and
the answer are public pieces, so that the portfolio package's delete of an account with
the portfolios only it used runs the same checks and answers the same way.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from metatables import MetaTableTransactionGuardError

from msm.api.http import TableImpact, TableImpactNode
from msm.repositories import account_deletion as account_deletion_repository
from msm.repositories.account_deletion import ACCOUNT_DELETE_GUARD, ACCOUNT_HISTORY_KEYS
from msm.repositories.base import MarketsCompiledWrite, MarketsRepositoryContext, execute_markets_write

from .core import get_account_by_uid


class AccountDeleteConflictError(ValueError):
    """A foreign key refuses the account delete. Nothing was deleted."""


@dataclass(frozen=True)
class AccountDeleteImpact:
    """What deleting accounts reaches beyond the Markets tables, from MetaTables."""

    impact: TableImpact | None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    other_namespace_cascades: list[str] = field(default_factory=list)
    other_namespace_restricts: list[str] = field(default_factory=list)


_BLOCKER_MESSAGES = {
    "other_account_orders": (
        "{count} orders of other accounts name its order managers (ON DELETE RESTRICT)."
    ),
    "other_account_virtual_fund_holdings_sets": (
        "{count} virtual-fund holdings sets of other accounts were allocated from its "
        "holdings sets (ON DELETE RESTRICT)."
    ),
    "other_account_virtual_fund_holdings": (
        "{count} virtual-fund holdings rows of other accounts were allocated from its "
        "holdings sets (ON DELETE RESTRICT)."
    ),
}
_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")


def account_delete_impact() -> AccountDeleteImpact:
    """MetaTables' delete impact for the account table, split by namespace.

    Tables in other namespaces that a `CASCADE` key reaches lose their referencing
    rows with the account. Tables in other namespaces with a `RESTRICT` key refuse the
    delete while they hold referencing rows. Markets cannot count rows there, so both
    are warnings; the database applies the keys when the delete runs. Only the
    preflight asks for it.
    """

    from msm.models import AccountTable
    from msm.services.table_impact import delete_rows_impact, impact_node_label
    from msm.settings import markets_namespace

    base = delete_rows_impact(AccountTable)
    cascades: list[str] = []
    restricts: list[str] = []
    if base.impact is not None:
        namespace = markets_namespace()
        nodes = {node.id: node for node in base.impact.nodes}

        def outside_markets(node: TableImpactNode | None) -> bool:
            # A table can be in several namespaces (MetaTables 0.1.66); it is a Markets table
            # when the Markets namespace is one of them.
            return node is None or node.type != "meta_table" or namespace not in node.namespaces

        for node in base.impact.nodes:
            if outside_markets(node) and "delete" in node.effects:
                cascades.append(impact_node_label(node, sentence_start=True))
        for edge in base.impact.edges:
            source = nodes.get(edge.source)
            if edge.kind == "foreign_key" and edge.effect == "restrict" and outside_markets(source):
                restricts.append(impact_node_label(source, sentence_start=True))
    cascades = list(dict.fromkeys(cascades))
    restricts = list(dict.fromkeys(restricts))
    warnings = [
        *base.warnings,
        *(
            f"{table}: its rows that reference a deleted account or its rows are deleted "
            "with them by that table's own CASCADE key. Markets sends that table no statement."
            for table in cascades
        ),
        *(
            f"{table}: its rows that reference an account or its rows refuse the delete while "
            "they exist (ON DELETE RESTRICT). The application that owns that table deletes them first."
            for table in restricts
        ),
    ]
    return AccountDeleteImpact(
        impact=base.impact,
        warnings=warnings,
        blockers=list(base.blockers),
        other_namespace_cascades=cascades,
        other_namespace_restricts=restricts,
    )


# The pieces ------------------------------------------------------------------------------


def account_delete_plan(read: Mapping[str, Any]) -> dict[str, Any]:
    """The delete of an account as one read found it: its rows per table and its blockers.

    ``read`` is `msm.repositories.account_deletion.account_delete_read_row`'s answer.
    Blockers are Markets rows of other accounts; tables in other namespaces are reported
    by `account_delete_impact`.
    """

    counts = read["counts"]
    return {
        "uid": read["uid"],
        "unique_identifier": read["unique_identifier"],
        "row_counts": {key: counts[key] for key in ACCOUNT_HISTORY_KEYS},
        "blockers": [
            message.format(count=counts[key])
            for key, message in _BLOCKER_MESSAGES.items()
            if counts.get(key, 0) > 0
        ],
    }


def check_account_delete_blockers(plan: Mapping[str, Any]) -> None:
    """Raise `AccountDeleteConflictError` when Markets rows of other accounts block it."""

    if plan["blockers"]:
        raise AccountDeleteConflictError(
            f"{_label(plan)} cannot be deleted: {' '.join(plan['blockers'])}"
        )


def run_account_delete(
    context: MarketsRepositoryContext,
    plan: Mapping[str, Any],
    write: MarketsCompiledWrite | None = None,
) -> dict[str, Any]:
    """Run the account delete's transaction for ``plan``, or ``write`` built around it.

    ``write`` is a statement list that holds
    `msm.repositories.account_deletion.account_delete_statements` and ends with a
    statement that returns rows. Answers with the transaction's result, whose rows are
    empty when the account's guard stopped the list; `account_delete_refused` then says
    why. Raises `AccountDeleteConflictError` when a foreign key refused the transaction,
    and `metatables.MetaTableTransactionGuardError` when another guard missed. Nothing
    is deleted unless rows come back.
    """

    try:
        return execute_markets_write(
            write
            or account_deletion_repository.build_delete_account_operation(
                context,
                uid=plan["uid"],
                unique_identifier=plan["unique_identifier"],
                row_counts=plan["row_counts"],
            ),
            context=context,
            refused_by=(ACCOUNT_DELETE_GUARD,),
        )
    except MetaTableTransactionGuardError:
        raise
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        raise AccountDeleteConflictError(
            f"{_label(plan)} cannot be deleted; nothing was deleted. {exc}"
        ) from exc


def account_delete_refused(context: MarketsRepositoryContext, plan: Mapping[str, Any]) -> None:
    """After the account's guard stopped the transaction, which deleted nothing.

    Returns when the account is gone; raises `AccountDeleteConflictError` when it was
    renamed in between.
    """

    if get_account_by_uid(context, uid=uuid.UUID(plan["uid"])).get("rows"):
        raise AccountDeleteConflictError(
            f"{_label(plan)} changed while it was being deleted; nothing was deleted. "
            "Retry the delete."
        )


def account_deleted_response(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The answer for an account whose delete committed."""

    return {
        "detail": f"{_label(plan)} deleted with its history.",
        "uid": plan["uid"],
        "unique_identifier": plan["unique_identifier"],
        "deleted_count": 1,
        "deleted_rows": dict(plan["row_counts"]),
    }


def summarize_account_delete_preflight(
    target_uids: Sequence[str],
    accounts: Sequence[Mapping[str, Any]],
    impact: AccountDeleteImpact,
) -> dict[str, Any]:
    """The bulk preflight's answer from each found account's plan and the impact.

    ``target_uids`` are the selected uids; a uid without a plan in ``accounts`` was not
    found. Each blocker keeps its own account, never the selection: the answer is allowed
    when at least one account can be deleted (issue 128).
    """

    by_uid = {item["uid"]: item for item in accounts}
    blockers: list[str] = []
    for uid in target_uids:
        item = by_uid.get(uid)
        if item is None:
            blockers.append(f"Account {uid} was not found.")
            continue
        blockers.extend(f"{_label(item)}: {blocker}" for blocker in item["blockers"])
    blockers.extend(impact.blockers)
    matched = len(accounts)
    deletable = 0 if impact.blockers else sum(1 for item in accounts if not item["blockers"])
    # Allowed when at least one account can go; the others are reported (issue 128).
    allowed = deletable > 0
    if not allowed:
        detail = "None of the selected accounts can be deleted."
    elif deletable == len(target_uids):
        detail = (
            f"{matched} account{' is' if matched == 1 else 's are'} ready for deletion with "
            f"{'its' if matched == 1 else 'their'} history."
        )
    else:
        detail = (
            f"{deletable} of the {len(target_uids)} selected accounts can be deleted with "
            f"{'its' if deletable == 1 else 'their'} history; the others are kept."
        )
    return {
        "allowed": allowed,
        "detail": detail,
        "matched_count": matched,
        "blockers": blockers,
        "warnings": list(impact.warnings),
        "impact": impact.impact,
        "accounts": list(accounts),
        "other_namespace_cascades": list(impact.other_namespace_cascades),
        "other_namespace_restricts": list(impact.other_namespace_restricts),
    }


# The delete ------------------------------------------------------------------------------


def preflight_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    together: Sequence[uuid.UUID | str] = (),
) -> dict[str, Any] | None:
    """What deleting one account removes from the Markets tables, and what blocks it.

    One read. Returns `None` when the account does not exist. ``together`` are accounts
    deleted in the same transaction, whose rows block nothing.
    """

    read = account_deletion_repository.read_account_delete(
        context, uid=canonical_uid(uid), together=unique_uids(together)
    )
    return None if read is None else account_delete_plan(read)


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Delete one account and its whole history in one transaction (ADR 0050).

    Returns `None` when the account does not exist. Raises
    `AccountDeleteConflictError` when a foreign key refuses the delete; then nothing
    is deleted. ``deleted_rows`` counts the Markets rows per table just before the
    delete ran.
    """

    plan = preflight_account_delete(context, uid=uid)
    if plan is None:
        return None
    check_account_delete_blockers(plan)
    if not run_account_delete(context, plan).get("rows"):
        account_delete_refused(context, plan)
        return None
    return account_deleted_response(plan)


def bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    table_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    """Delete every selected account that may go, together, and report the rest.

    One read per account, each counting the other selected accounts as deleted with it;
    then one transaction for every account that may go (issue 128). An account that is
    missing or that rows of an account not selected block is reported in ``failed``.
    ``table_blockers``, MetaTables' reasons the whole table refuses the delete, report
    every account. When the database refuses the transaction, which then deletes
    nothing, each account is deleted on its own, so only the refused ones stay.
    """

    target = unique_uids(uids)
    plans = {
        uid: plan
        for uid in target
        if (plan := preflight_account_delete(context, uid=uid, together=target)) is not None
    }
    allowed, failed = partition_account_deletes(target, plans, table_blockers)
    deleted: list[dict[str, Any]] = []
    if allowed and run_accounts_delete(context, allowed) is not None:
        deleted = [account_deleted_response(plan) for plan in allowed]
    else:
        for plan in allowed:
            try:
                result = delete_account(context, uid=plan["uid"])
            except AccountDeleteConflictError as exc:
                failed[plan["uid"]] = str(exc)
                continue
            if result is None:
                failed[plan["uid"]] = f"Account {plan['uid']} was not found."
                continue
            deleted.append(result)
    count = len(deleted)
    detail = (
        "No accounts were deleted."
        if count == 0
        else f"Deleted {count} account{'s' if count != 1 else ''} with "
        f"{'its' if count == 1 else 'their'} history."
    )
    return bulk_accounts_response(detail, deleted, failed, target)


def partition_account_deletes(
    target: Sequence[str],
    plans: Mapping[str, Mapping[str, Any]],
    table_blockers: Sequence[str] = (),
) -> tuple[list[Mapping[str, Any]], dict[str, str]]:
    """The plans of the selected accounts that may go, and the reason for each other one."""

    allowed: list[Mapping[str, Any]] = []
    failed: dict[str, str] = {}
    for uid in target:
        plan = plans.get(uid)
        if plan is None:
            failed[uid] = f"Account {uid} was not found."
        elif table_blockers:
            failed[uid] = (
                f"{_label(plan)} cannot be deleted; nothing was deleted. {' '.join(table_blockers)}"
            )
        elif plan["blockers"]:
            failed[uid] = f"{_label(plan)} cannot be deleted: {' '.join(plan['blockers'])}"
        else:
            allowed.append(plan)
    return allowed, failed


def run_accounts_delete(
    context: MarketsRepositoryContext,
    plans: Sequence[Mapping[str, Any]],
    write: MarketsCompiledWrite | None = None,
) -> dict[str, Any] | None:
    """Delete ``plans``' accounts in one transaction, or ``write`` built around them.

    ``write`` holds `msm.repositories.account_deletion.accounts_delete_statements` for
    the same accounts. Answers with the transaction's result, or ``None`` when it was
    refused and deleted nothing: a guard missed, or a foreign key refused it.
    """

    try:
        result = execute_markets_write(
            write
            or account_deletion_repository.build_delete_accounts_operation(
                context,
                accounts=[(plan["uid"], plan["unique_identifier"]) for plan in plans],
                row_counts=summed_row_counts(plans),
            ),
            context=context,
            refused_by=(ACCOUNT_DELETE_GUARD,),
        )
    except MetaTableTransactionGuardError:
        return None
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        return None
    return result if result.get("rows") else None


def summed_row_counts(plans: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """The plans' ``row_counts`` added up, for one transaction that deletes them all."""

    return {key: sum(plan["row_counts"][key] for plan in plans) for key in ACCOUNT_HISTORY_KEYS}


def bulk_accounts_response(
    detail: str,
    deleted: Sequence[Mapping[str, Any]],
    failed: Mapping[str, str],
    target: Sequence[str],
) -> dict[str, Any]:
    """The bulk-delete envelope; ``failed`` keeps the order of the selection."""

    if failed:
        detail += f" {len(failed)} could not be deleted."
    return {
        "detail": detail,
        "deleted_count": len(deleted),
        "deleted": list(deleted),
        "failed": [{"uid": uid, "detail": failed[uid]} for uid in target if uid in failed],
    }


def preflight_bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Report what deleting the accounts removes and what blocks it, without deleting.

    One read per account, each counting the other selected accounts as deleted with it,
    and MetaTables' delete impact for the account table.
    """

    target_uids = unique_uids(uids)
    accounts = [
        plan
        for plan in (
            preflight_account_delete(context, uid=uid, together=target_uids)
            for uid in target_uids
        )
        if plan is not None
    ]
    return summarize_account_delete_preflight(target_uids, accounts, account_delete_impact())


def canonical_uid(uid: uuid.UUID | str) -> str:
    """``uid`` as a canonical UUID string; a malformed one raises `ValueError`."""

    return str(uuid.UUID(str(uid)))


def unique_uids(uids: Sequence[uuid.UUID | str]) -> list[str]:
    """``uids`` as canonical UUID strings, each once, in their order."""

    return list(dict.fromkeys(canonical_uid(uid) for uid in uids))


def _label(plan: Mapping[str, Any]) -> str:
    return f"Account {plan['unique_identifier']!r}"


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


__all__ = [
    "AccountDeleteConflictError",
    "AccountDeleteImpact",
    "account_delete_impact",
    "account_delete_plan",
    "account_delete_refused",
    "account_deleted_response",
    "bulk_accounts_response",
    "bulk_delete_accounts",
    "canonical_uid",
    "check_account_delete_blockers",
    "delete_account",
    "partition_account_deletes",
    "preflight_account_delete",
    "preflight_bulk_delete_accounts",
    "run_account_delete",
    "run_accounts_delete",
    "summarize_account_delete_preflight",
    "summed_row_counts",
    "unique_uids",
]
