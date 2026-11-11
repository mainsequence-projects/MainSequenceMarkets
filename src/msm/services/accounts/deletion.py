"""Delete accounts with their whole history (ADR 0050).

`Account.delete`, `Account.bulk_delete` and the Markets API account delete routes all
run these functions, so the same call removes the same rows under the runtime and
the remote backend.

Markets deletes only rows in its own tables. A table in another namespace loses rows
only through a foreign key it carries: a `CASCADE` key deletes its rows with their
parent and is reported, and a `RESTRICT` key refuses the whole delete.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from msm.api.http import TableImpact, TableImpactNode
from msm.repositories import account_deletion as account_deletion_repository
from msm.repositories.base import MarketsRepositoryContext

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


_DELETED_TABLE_KEYS = tuple(
    table.key for table in account_deletion_repository.ACCOUNT_DELETE_TABLES if table.key != "accounts"
)
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
    are warnings; the database applies the keys when the delete runs.
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
            return node is None or node.type != "meta_table" or (node.namespace or "") != namespace

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


def preflight_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Count what deleting one account removes from the Markets tables, and what blocks it.

    Returns `None` when the account does not exist. Blockers here are Markets rows of
    other accounts; tables in other namespaces are reported by `account_delete_impact`.
    """

    account = _account_row(context, uid=uid)
    if account is None:
        return None
    counts = account_deletion_repository.count_account_delete_rows(
        context,
        uid=account["uid"],
        unique_identifier=account["unique_identifier"],
    )
    return {
        "uid": account["uid"],
        "unique_identifier": account["unique_identifier"],
        "row_counts": {key: counts[key] for key in _DELETED_TABLE_KEYS},
        "blockers": _markets_blockers(counts),
    }


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    impact: AccountDeleteImpact | None = None,
) -> dict[str, Any] | None:
    """Delete one account and its whole history in one transaction (ADR 0050).

    Returns `None` when the account does not exist. Raises
    `AccountDeleteConflictError` when a foreign key refuses the delete; then nothing
    is deleted. `deleted_rows` counts the Markets rows per table just before the
    delete ran.
    """

    preflight = preflight_account_delete(context, uid=uid)
    if preflight is None:
        return None
    label = f"Account {preflight['unique_identifier']!r}"
    if preflight["blockers"]:
        raise AccountDeleteConflictError(f"{label} cannot be deleted: {' '.join(preflight['blockers'])}")
    impact = impact if impact is not None else account_delete_impact()
    try:
        result = account_deletion_repository.delete_account(
            context,
            uid=preflight["uid"],
            unique_identifier=preflight["unique_identifier"],
        )
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        raise AccountDeleteConflictError(
            f"{label} cannot be deleted; nothing was deleted. {exc}{_restrict_hint(impact)}"
        ) from exc
    if not result.get("rows"):
        if _account_row(context, uid=preflight["uid"]) is None:
            return None
        raise AccountDeleteConflictError(
            f"{label} changed while it was being deleted; nothing was deleted. Retry the delete."
        )
    return {
        "detail": f"{label} deleted with its history.",
        "uid": preflight["uid"],
        "unique_identifier": preflight["unique_identifier"],
        "deleted_count": 1,
        "deleted_rows": preflight["row_counts"],
        "other_namespace_cascades": list(impact.other_namespace_cascades),
    }


def bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Delete each account with its history, each in its own transaction.

    An account that is missing or refused is reported in `failed` and the others are
    still deleted.
    """

    impact = account_delete_impact()
    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for uid in _unique_uids(uids):
        try:
            result = delete_account(context, uid=uid, impact=impact)
        except AccountDeleteConflictError as exc:
            failed.append({"uid": uid, "detail": str(exc)})
            continue
        if result is None:
            failed.append({"uid": uid, "detail": f"Account {uid} was not found."})
            continue
        deleted.append(result)
    count = len(deleted)
    if count == 0:
        detail = "No accounts were deleted."
    else:
        detail = f"Deleted {count} account{'s' if count != 1 else ''} with their history."
    if failed:
        detail += f" {len(failed)} could not be deleted."
    return {
        "detail": detail,
        "deleted_count": count,
        "deleted": deleted,
        "failed": failed,
        "other_namespace_cascades": list(impact.other_namespace_cascades),
    }


def preflight_bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Report what deleting the accounts removes and what blocks it, without deleting."""

    target_uids = _unique_uids(uids)
    accounts: list[dict[str, Any]] = []
    blockers: list[str] = []
    for uid in target_uids:
        item = preflight_account_delete(context, uid=uid)
        if item is None:
            blockers.append(f"Account {uid} was not found.")
            continue
        accounts.append(item)
        blockers.extend(f"Account {item['unique_identifier']!r}: {blocker}" for blocker in item["blockers"])
    impact = account_delete_impact()
    blockers.extend(impact.blockers)
    allowed = bool(target_uids) and not blockers
    matched = len(accounts)
    detail = (
        f"{matched} account{' is' if matched == 1 else 's are'} ready for deletion with "
        f"{'its' if matched == 1 else 'their'} history."
        if allowed
        else "The account selection cannot be deleted as submitted."
    )
    return {
        "allowed": allowed,
        "detail": detail,
        "matched_count": matched,
        "blockers": blockers,
        "warnings": list(impact.warnings),
        "impact": impact.impact,
        "accounts": accounts,
        "other_namespace_cascades": list(impact.other_namespace_cascades),
        "other_namespace_restricts": list(impact.other_namespace_restricts),
    }


def _account_row(context: MarketsRepositoryContext, *, uid: uuid.UUID | str) -> dict[str, Any] | None:
    account_uid = uuid.UUID(str(uid))
    rows = get_account_by_uid(context, uid=account_uid).get("rows") or []
    if not rows:
        return None
    row = rows[0]
    return {
        "uid": str(uuid.UUID(str(row["uid"]))),
        "unique_identifier": str(row.get("unique_identifier") or ""),
    }


def _markets_blockers(counts: Mapping[str, int]) -> list[str]:
    return [
        message.format(count=counts[key])
        for key, message in _BLOCKER_MESSAGES.items()
        if counts.get(key, 0) > 0
    ]


def _restrict_hint(impact: AccountDeleteImpact) -> str:
    if not impact.other_namespace_restricts:
        return ""
    tables = ", ".join(impact.other_namespace_restricts)
    return (
        f" Tables in other namespaces whose RESTRICT keys can refuse it: {tables}. "
        "The application that owns each table deletes its rows first."
    )


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


def _unique_uids(uids: Sequence[uuid.UUID | str]) -> list[str]:
    return list(dict.fromkeys(str(uuid.UUID(str(uid))) for uid in uids))


__all__ = [
    "AccountDeleteConflictError",
    "AccountDeleteImpact",
    "account_delete_impact",
    "bulk_delete_accounts",
    "delete_account",
    "preflight_account_delete",
    "preflight_bulk_delete_accounts",
]
