"""Delete accounts with their whole history, and the portfolios only they used (ADR 0050).

`Account.delete`, `Account.bulk_delete` and the Markets API account delete routes all
run these functions, so the same call removes the same rows under the runtime and
the remote backend.

Markets deletes only rows in its own tables. A table in another namespace loses rows
only through a foreign key it carries: a `CASCADE` key deletes its rows with their
parent, and a `RESTRICT` key refuses the whole delete.

A delete sends one read and one MetaTables transaction, and asks MetaTables for no
impact; only the bulk-delete preflight does (issue 91).

With ``delete_portfolios``, the portfolios the account's virtual funds or target rows
name are deleted in the same transaction, with their rows in every dataset, when
nothing references them once the account's history is gone. A portfolio is kept, and
the answer says why, when account history of another account references it (ADR 0049),
when the catalog places its values or weights in a table another application owns
(ADR 0047), or when a foreign key refuses its delete; then the transaction deletes
nothing, and a second one deletes the account alone.

After the transactions of a request commit, MetaTables rebuilds the stored update
statistics of each table whose identity coordinates an account re-created under the
same ``unique_identifier`` publishes again (its orders, trades and order events), and
of each portfolio dataset table that lost rows (`msm.services.update_statistics`,
MetaTables#117). A failed rebuild does not undo the delete; the answer lists it in
``statistics_not_refreshed``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger
from metatables import MetaTableTransactionGuardError

from msm.api.http import TableImpact, TableImpactNode
from msm.repositories import account_deletion as account_deletion_repository
from msm.repositories.account_deletion import (
    ACCOUNT_HISTORY_KEYS,
    ACCOUNT_PORTFOLIOS_GUARD,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage

from .core import get_account_by_uid

logger = _mainsequence_logger.bind(sub_application="markets", component="account_deletion")


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
_REFERENCE_REASONS = {
    "virtual_funds": "{count} virtual fund{plural} of other accounts target{verb} it.",
    "target_positions": "{count} target-position row{plural} of other accounts name{verb} it.",
}
PORTFOLIO_CHANGED_REASON = (
    "It changed while the account was being deleted, so the account was deleted alone. "
    "Check the portfolio and delete it on its own."
)
_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")
_REPUBLISHED_HISTORY: tuple[tuple[str, type[Any], str | None], ...] = (
    ("order_events", OrderEventsStorage, None),
    ("trades", TradesStorage, "account_identifier"),
    ("orders", OrdersStorage, "account_identifier"),
)
"""The account's time-index tables whose stored progress an account re-created under the
same ``unique_identifier`` can run into: their identity is the account identifier or the
broker's order and trade identifiers, which its connector publishes again. Each entry
names the dimension that scopes the rebuild to the deleted account; order events have
none, so their rebuild is scoped by its cutoff alone. Holdings, virtual-fund holdings,
target rows and allocation lines are keyed by uids that are new for every account and
snapshot, so no stale entry can match them."""


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


def preflight_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    delete_portfolios: bool = False,
) -> dict[str, Any] | None:
    """What deleting one account removes from the Markets tables, and what blocks it.

    One read. Returns `None` when the account does not exist. Blockers are Markets rows
    of other accounts; tables in other namespaces are reported by
    `account_delete_impact`. With ``delete_portfolios``, ``portfolios`` lists the
    portfolios the delete removes with their rows per dataset, and ``kept_portfolios``
    the ones its history names that stay, with the reason.
    """

    read = account_deletion_repository.read_account_delete(
        context,
        uid=_canonical_uid(uid),
        with_portfolios=delete_portfolios,
    )
    if read is None:
        return None
    portfolios: list[dict[str, Any]] = []
    kept: list[dict[str, str]] = []
    for portfolio in read["portfolios"]:
        reasons = _kept_reasons(portfolio)
        if reasons:
            kept.append(_kept(portfolio, " ".join(reasons)))
        else:
            portfolios.append(
                {
                    "uid": portfolio["uid"],
                    "unique_identifier": portfolio["unique_identifier"],
                    "row_counts": dict(portfolio["row_counts"]),
                }
            )
    counts = read["counts"]
    return {
        "uid": read["uid"],
        "unique_identifier": read["unique_identifier"],
        "row_counts": {key: counts[key] for key in ACCOUNT_HISTORY_KEYS},
        "blockers": _markets_blockers(counts),
        "portfolios": portfolios,
        "kept_portfolios": kept,
    }


@dataclass
class _DeletedAccount:
    """One account whose transaction committed, before its statistics are refreshed."""

    plan: dict[str, Any]
    portfolios: list[dict[str, Any]]
    kept: list[dict[str, str]]
    statistics_not_refreshed: list[str] = field(default_factory=list)
    portfolio_statistics_not_refreshed: dict[str, list[str]] = field(default_factory=dict)

    def stale(self) -> list[str]:
        """Every table key whose statistics were not refreshed, account tables first."""

        keys = list(self.statistics_not_refreshed)
        for portfolio in self.portfolios:
            keys.extend(self.portfolio_statistics_not_refreshed.get(portfolio["unique_identifier"], []))
        return list(dict.fromkeys(keys))

    def response(self) -> dict[str, Any]:
        label = _label(self.plan)
        detail = f"{label} deleted with its history"
        if self.portfolios:
            detail += f" and {_count(len(self.portfolios), 'portfolio')}"
        detail += "."
        if self.kept:
            detail += (
                f" {_count(len(self.kept), 'portfolio')} it used "
                f"{'was' if len(self.kept) == 1 else 'were'} kept."
            )
        if self.stale():
            detail += f" {_not_refreshed_text(self.stale())}"
        return {
            "detail": detail,
            "uid": self.plan["uid"],
            "unique_identifier": self.plan["unique_identifier"],
            "deleted_count": 1,
            "deleted_rows": dict(self.plan["row_counts"]),
            "statistics_not_refreshed": list(self.statistics_not_refreshed),
            "deleted_portfolios": [
                {
                    "uid": portfolio["uid"],
                    "unique_identifier": portfolio["unique_identifier"],
                    "deleted_rows": dict(portfolio["row_counts"]),
                    "statistics_not_refreshed": list(
                        self.portfolio_statistics_not_refreshed.get(portfolio["unique_identifier"], [])
                    ),
                }
                for portfolio in self.portfolios
            ],
            "kept_portfolios": list(self.kept),
        }


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    delete_portfolios: bool = False,
) -> dict[str, Any] | None:
    """Delete one account and its whole history in one transaction (ADR 0050).

    Returns `None` when the account does not exist. Raises
    `AccountDeleteConflictError` when a foreign key refuses the account's delete; then
    nothing is deleted. ``deleted_rows`` counts the Markets rows per table just before
    the delete ran. With ``delete_portfolios``, ``deleted_portfolios`` lists the
    portfolios deleted with it and their rows per dataset, and ``kept_portfolios`` the
    portfolios its history named that stay, with the reason. After the transaction
    commits, the stored update statistics of the tables that lost rows are rebuilt;
    ``statistics_not_refreshed`` lists those that could not be.
    """

    deleted = _delete_one(context, uid=uid, delete_portfolios=delete_portfolios)
    if deleted is None:
        return None
    _refresh_statistics(context, [deleted])
    return deleted.response()


def bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    delete_portfolios: bool = False,
) -> dict[str, Any]:
    """Delete each account as `delete_account` does, each in its own transaction.

    An account that is missing or refused is reported in `failed` and the others are
    still deleted. Accounts go in the order given, so a portfolio that only selected
    accounts use goes with the last of them. After the transactions, each table that
    lost rows has its stored update statistics rebuilt once, for every account and
    portfolio the request deleted.
    """

    done: list[_DeletedAccount] = []
    failed: list[dict[str, str]] = []
    for uid in _unique_uids(uids):
        try:
            deleted = _delete_one(context, uid=uid, delete_portfolios=delete_portfolios)
        except AccountDeleteConflictError as exc:
            failed.append({"uid": uid, "detail": str(exc)})
            continue
        if deleted is None:
            failed.append({"uid": uid, "detail": f"Account {uid} was not found."})
            continue
        done.append(deleted)
    _refresh_statistics(context, done)
    count = len(done)
    if count == 0:
        detail = "No accounts were deleted."
    else:
        detail = f"Deleted {_count(count, 'account')} with {'its' if count == 1 else 'their'} history"
        portfolio_count = sum(len(item.portfolios) for item in done)
        if portfolio_count:
            detail += f" and {_count(portfolio_count, 'portfolio')}"
        detail += "."
    if failed:
        detail += f" {len(failed)} could not be deleted."
    stale = list(dict.fromkeys(key for item in done for key in item.stale()))
    if stale:
        detail += f" {_not_refreshed_text(stale)}"
    return {
        "detail": detail,
        "deleted_count": count,
        "deleted": [item.response() for item in done],
        "failed": failed,
    }


def preflight_bulk_delete_accounts(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    delete_portfolios: bool = False,
) -> dict[str, Any]:
    """Report what deleting the accounts removes and what blocks it, without deleting.

    One read per account, and MetaTables' delete impact for the account table. Each
    account is read as if it were deleted alone.
    """

    target_uids = _unique_uids(uids)
    accounts: list[dict[str, Any]] = []
    blockers: list[str] = []
    portfolio_warnings: list[str] = []
    for uid in target_uids:
        item = preflight_account_delete(context, uid=uid, delete_portfolios=delete_portfolios)
        if item is None:
            blockers.append(f"Account {uid} was not found.")
            continue
        accounts.append(item)
        label = _label(item)
        blockers.extend(f"{label}: {blocker}" for blocker in item["blockers"])
        portfolio_warnings.extend(
            f"{label}: portfolio {portfolio['unique_identifier']!r} is deleted with it, with "
            "its rows in every dataset."
            for portfolio in item["portfolios"]
        )
        portfolio_warnings.extend(
            f"{label}: portfolio {portfolio['unique_identifier']!r} is kept. {portfolio['reason']}"
            for portfolio in item["kept_portfolios"]
        )
    impact = account_delete_impact()
    blockers.extend(impact.blockers)
    allowed = bool(target_uids) and not blockers
    matched = len(accounts)
    portfolio_count = sum(len(item["portfolios"]) for item in accounts)
    if allowed:
        detail = (
            f"{matched} account{' is' if matched == 1 else 's are'} ready for deletion with "
            f"{'its' if matched == 1 else 'their'} history"
        )
        if portfolio_count:
            detail += f" and {_count(portfolio_count, 'portfolio')}"
        detail += "."
    else:
        detail = "The account selection cannot be deleted as submitted."
    return {
        "allowed": allowed,
        "detail": detail,
        "matched_count": matched,
        "blockers": blockers,
        "warnings": [*impact.warnings, *portfolio_warnings],
        "impact": impact.impact,
        "accounts": accounts,
        "other_namespace_cascades": list(impact.other_namespace_cascades),
        "other_namespace_restricts": list(impact.other_namespace_restricts),
    }


def _delete_one(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    delete_portfolios: bool,
) -> _DeletedAccount | None:
    """Read and delete one account, and its portfolios on request; ``None`` without it."""

    plan = preflight_account_delete(context, uid=uid, delete_portfolios=delete_portfolios)
    if plan is None:
        return None
    label = _label(plan)
    if plan["blockers"]:
        raise AccountDeleteConflictError(f"{label} cannot be deleted: {' '.join(plan['blockers'])}")
    portfolios = plan["portfolios"]
    kept = list(plan["kept_portfolios"])
    try:
        result = _delete(context, plan, portfolios)
    except MetaTableTransactionGuardError as exc:
        if exc.label != ACCOUNT_PORTFOLIOS_GUARD:
            raise
        # A portfolio was referenced or removed in between; nothing was deleted.
        kept.extend(_kept(portfolio, PORTFOLIO_CHANGED_REASON) for portfolio in portfolios)
        portfolios = []
        result = _delete(context, plan, portfolios)
    except AccountDeleteConflictError as exc:
        if not portfolios:
            raise
        # A key the read could not see, such as one from another application's table,
        # refused the transaction, which deleted nothing. Delete the account alone: if a
        # key refuses that too, it is the account's own and nothing is deleted.
        refused = str(exc.__cause__ or exc)
        result = _delete(context, plan, [])
        kept.extend(
            _kept(
                portfolio,
                f"A foreign key refused its delete, so the account was deleted alone: {refused}",
            )
            for portfolio in portfolios
        )
        portfolios = []
    if not result.get("rows"):
        # The account's guard stopped the list: the account vanished or was renamed in
        # between. Nothing was deleted.
        if not get_account_by_uid(context, uid=uuid.UUID(plan["uid"])).get("rows"):
            return None
        raise AccountDeleteConflictError(
            f"{label} changed while it was being deleted; nothing was deleted. Retry the delete."
        )
    if portfolios:
        # The portfolios' statement returns the rows it deleted, with their identifiers now.
        returned = {
            _canonical_uid(row["uid"]): str(row.get("unique_identifier") or "")
            for row in result["rows"]
        }
        portfolios = [
            {**portfolio, "unique_identifier": returned.get(portfolio["uid"]) or portfolio["unique_identifier"]}
            for portfolio in portfolios
        ]
    return _DeletedAccount(plan=plan, portfolios=portfolios, kept=kept)


def _refresh_statistics(
    context: MarketsRepositoryContext,
    deleted: Sequence[_DeletedAccount],
) -> None:
    """Rebuild the stored update statistics of every table the deletes left stale.

    Once per table, after every transaction of the request: the account tables of
    `_REPUBLISHED_HISTORY` that lost rows, scoped to the deleted accounts' identifiers,
    and the portfolio dataset tables that lost rows, scoped to the deleted portfolios'
    identifiers. Failures are logged and recorded on each deleted account.
    """

    from msm.services.update_statistics import (
        refresh_portfolio_dataset_statistics,
        refresh_update_statistics,
    )

    for key, model, dimension in _REPUBLISHED_HISTORY:
        affected = [item for item in deleted if item.plan["row_counts"].get(key, 0) > 0]
        if not affected:
            continue
        identifiers = [item.plan["unique_identifier"] for item in affected]
        try:
            refresh_update_statistics(
                model,
                dimension_filters={dimension: identifiers} if dimension else None,
                timeout=context.timeout,
            )
        except Exception:
            logger.exception(
                "MetaTables could not refresh an account table's update statistics",
                table=key,
                account_identifiers=identifiers,
            )
            for item in affected:
                item.statistics_not_refreshed.append(key)
    not_refreshed = refresh_portfolio_dataset_statistics(
        {
            portfolio["unique_identifier"]: portfolio["row_counts"]
            for item in deleted
            for portfolio in item.portfolios
        },
        timeout=context.timeout,
    )
    for item in deleted:
        item.portfolio_statistics_not_refreshed = {
            portfolio["unique_identifier"]: not_refreshed.get(portfolio["unique_identifier"], [])
            for portfolio in item.portfolios
        }


def _not_refreshed_text(keys: Sequence[str]) -> str:
    from msm.services.update_statistics import statistics_not_refreshed_text

    return statistics_not_refreshed_text(keys)


def _delete(
    context: MarketsRepositoryContext,
    plan: Mapping[str, Any],
    portfolios: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run the delete's transaction; a refusing foreign key raises the conflict error."""

    try:
        return account_deletion_repository.delete_account(
            context,
            uid=plan["uid"],
            unique_identifier=plan["unique_identifier"],
            portfolio_uids=[portfolio["uid"] for portfolio in portfolios],
        )
    except MetaTableTransactionGuardError:
        raise
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        raise AccountDeleteConflictError(
            f"{_label(plan)} cannot be deleted; nothing was deleted. {exc}"
        ) from exc


def _kept_reasons(portfolio: Mapping[str, Any]) -> list[str]:
    """Why a portfolio the account's history names stays when the account goes."""

    from msm.portfolio_datasets import portfolio_dataset_tables
    from msm.storage_instances import PROVIDER_TABLE_DELETE_GUIDANCE, provider_owned_table_uid

    reasons = [
        _REFERENCE_REASONS[key].format(
            count=count,
            plural="s" if count != 1 else "",
            verb="" if count != 1 else "s",
        )
        for key, count in portfolio["references"].items()
        if count > 0
    ]
    provider_tables = [
        f"The catalog places its {table.key} in table {owned}, which another application owns."
        for table in portfolio_dataset_tables()
        if table.catalog_column is not None
        and (
            owned := provider_owned_table_uid(
                portfolio["catalog"].get(table.catalog_column),
                core_storage=table.model,
            )
        )
        is not None
    ]
    if provider_tables:
        reasons.extend([*provider_tables, PROVIDER_TABLE_DELETE_GUIDANCE])
    return reasons


def _kept(portfolio: Mapping[str, Any], reason: str) -> dict[str, str]:
    return {
        "uid": portfolio["uid"],
        "unique_identifier": portfolio["unique_identifier"],
        "reason": reason,
    }


def _markets_blockers(counts: Mapping[str, int]) -> list[str]:
    return [
        message.format(count=counts[key])
        for key, message in _BLOCKER_MESSAGES.items()
        if counts.get(key, 0) > 0
    ]


def _label(plan: Mapping[str, Any]) -> str:
    return f"Account {plan['unique_identifier']!r}"


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


def _canonical_uid(uid: uuid.UUID | str) -> str:
    return str(uuid.UUID(str(uid)))


def _unique_uids(uids: Sequence[uuid.UUID | str]) -> list[str]:
    return list(dict.fromkeys(_canonical_uid(uid) for uid in uids))


__all__ = [
    "AccountDeleteConflictError",
    "AccountDeleteImpact",
    "PORTFOLIO_CHANGED_REASON",
    "account_delete_impact",
    "bulk_delete_accounts",
    "delete_account",
    "preflight_account_delete",
    "preflight_bulk_delete_accounts",
]
