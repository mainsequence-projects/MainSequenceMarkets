"""Delete portfolios with their own datasets (ADR 0049, issue 93).

`DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/` run these
functions, and `POST /api/v1/portfolio/bulk-delete/preflight/` reports what they would
do. No row class method runs them: `Portfolio.delete` is refused under both backends.

A portfolio is deleted with its rows in its seven Markets datasets (weights, values,
rebalance state, analytics, event ledger, state and cash flows) in one MetaTables
transaction, or not at all. A bulk delete deletes every selected portfolio that may go,
together in one transaction, and reports each one it did not delete with the reason; a
refused portfolio never stops the others (issue 127). Account history, the virtual funds and account target rows
that name the portfolio, refuses it before anything is sent: it is kept for as long as the
account exists (ADR 0049 decision 1). Through the Markets API only the portfolio's manager
may delete it (ADR 0060, decision 4).

Markets touches only its own tables (ADR 0060, decision 1). An application's own table
whose `RESTRICT` key references the portfolio is neither discovered nor counted: the
database applies the key when the transaction runs, and its refusal is answered as a
`PortfolioDeleteConflictError` with the database's message. The application deletes its
rows first (``msm_portfolios.recipes.delete_private_series``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger

from msm.api.http import TableImpact
from msm.repositories.account_deletion import ACCOUNT_HISTORY_REFERENCES
from msm.repositories.base import MarketsRepositoryContext
from msm.api.managers import manager_refusal
from msm_portfolios.repositories import portfolio_deletion as portfolio_deletion_repository
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES

logger = _mainsequence_logger.bind(sub_application="markets", component="portfolio_deletion")


class PortfolioDeleteConflictError(ValueError):
    """A reference refuses the portfolio delete. Nothing was deleted."""


ACCOUNT_HISTORY_GUIDANCE = (
    "Account history is kept for as long as the account exists (ADR 0049); retire the "
    "portfolio instead."
)
_HISTORY_BLOCKERS = {
    "virtual_funds": (
        "{count} virtual fund{plural} target it (VirtualFundTable.target_portfolio_uid, "
        "ON DELETE RESTRICT)."
    ),
    "target_positions": (
        "{count} account target-position row{plural} name it "
        "(TargetPositionsStorage.portfolio_uid, ON DELETE RESTRICT)."
    ),
}
_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")


@dataclass(frozen=True)
class PortfolioDeleteImpact:
    """MetaTables' delete impact for the portfolio table, passed through as it answers."""

    impact: TableImpact | None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PlannedDelete:
    """One portfolio as the counting read found it, with what blocks its delete."""

    uid: str
    unique_identifier: str
    row_counts: dict[str, int]
    history_blockers: tuple[str, ...] = ()
    manager_blocker: str | None = None

    @property
    def blockers(self) -> list[str]:
        return [*self.history_blockers, *([self.manager_blocker] if self.manager_blocker else [])]

    @property
    def label(self) -> str:
        return f"Portfolio {self.unique_identifier!r}"

    def preflight(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "unique_identifier": self.unique_identifier,
            "row_counts": dict(self.row_counts),
            "blockers": self.blockers,
        }


@dataclass(frozen=True)
class PortfolioDeletePlan:
    """The delete's checks for one portfolio selection, run once.

    One counting read for every portfolio in ``uids`` and MetaTables' impact.
    ``portfolios`` holds each existing portfolio by
    uid. `preflight` reports the plan, and `bulk_delete_portfolio_records` can delete by
    it, so `POST /api/v1/portfolio/bulk-delete/` counts its selection once (issue 96).
    Deleting by a plan made earlier is safe: when a portfolio's references change in
    between, the transaction's guarded statement or a ``RESTRICT`` key still refuses it.
    """

    uids: tuple[str, ...]
    impact: PortfolioDeleteImpact
    portfolios: Mapping[str, _PlannedDelete]

    @property
    def deletable(self) -> list[_PlannedDelete]:
        """The selected portfolios that exist and that nothing the read sees refuses."""

        return [
            planned
            for uid in self.uids
            if (planned := self.portfolios.get(uid)) is not None and not planned.blockers
        ]

    def preflight(self) -> dict[str, Any]:
        """What deleting the selection removes and what blocks it."""

        portfolios: list[dict[str, Any]] = []
        blockers: list[str] = []
        history_blocked = False
        for uid in self.uids:
            planned = self.portfolios.get(uid)
            if planned is None:
                blockers.append(f"Portfolio {uid} was not found.")
                continue
            portfolios.append(planned.preflight())
            blockers.extend(f"{planned.label}: {blocker}" for blocker in planned.blockers)
            history_blocked = history_blocked or bool(planned.history_blockers)
        blockers.extend(self.impact.blockers)
        warnings = list(self.impact.warnings)
        if history_blocked:
            warnings.append(ACCOUNT_HISTORY_GUIDANCE)
        deletable = 0 if self.impact.blockers else len(self.deletable)
        allowed = deletable > 0
        matched = len(portfolios)
        if not allowed:
            detail = "None of the selected portfolios can be deleted."
        elif deletable == len(self.uids):
            detail = (
                f"{matched} portfolio{' is' if matched == 1 else 's are'} ready for deletion "
                f"with {'its' if matched == 1 else 'their'} datasets."
            )
        else:
            detail = (
                f"{deletable} of the {len(self.uids)} selected portfolios can be deleted with "
                f"{'its' if deletable == 1 else 'their'} datasets; the others are kept."
            )
        return {
            "allowed": allowed,
            "detail": detail,
            "matched_count": matched,
            "blockers": blockers,
            "warnings": warnings,
            "impact": self.impact.impact,
            "portfolios": portfolios,
        }


def portfolio_delete_impact(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> PortfolioDeleteImpact:
    """MetaTables' delete impact for the portfolio table, as MetaTables answers it.

    Markets reports it and checks nothing in it: the database applies every key when the
    delete runs. An unavailable impact is a warning.
    """

    from msm.models import PortfolioTable
    from msm.services.table_impact import delete_rows_impact

    base = delete_rows_impact(PortfolioTable)
    return PortfolioDeleteImpact(
        impact=base.impact,
        warnings=list(base.warnings),
        blockers=list(base.blockers),
    )


def delete_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    impact: PortfolioDeleteImpact | None = None,
) -> dict[str, Any] | None:
    """Delete one portfolio with its rows in its seven datasets, in one transaction.

    Returns ``None`` when the portfolio does not exist. Raises
    `PortfolioDeleteConflictError` when account history references it or the database
    refuses the delete, and ``PermissionError`` when the caller does not manage it; then
    nothing is deleted. ``deleted_rows`` counts the rows per dataset just before the
    delete ran.
    """

    portfolio_uid = _canonical_uid(uid)
    impact = impact if impact is not None else portfolio_delete_impact(timeout=context.timeout)
    planned = _plan(context, [portfolio_uid], impact=impact).get(portfolio_uid)
    if planned is None or not _delete_planned(context, planned, impact=impact):
        return None
    return _deleted_response(planned)


def plan_portfolio_deletes(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> PortfolioDeletePlan:
    """Run the delete's checks for the selection once, without deleting.

    One read counts every selected portfolio, whatever their number (issue 96).
    """

    target_uids = _unique_uids(uids)
    impact = portfolio_delete_impact(timeout=context.timeout)
    return PortfolioDeletePlan(
        uids=tuple(target_uids),
        impact=impact,
        portfolios=_plan(context, target_uids, impact=impact),
    )


def bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    plan: PortfolioDeletePlan | None = None,
) -> dict[str, Any]:
    """Delete every selected portfolio that may go, with its datasets, and report the rest.

    One read counts every selected portfolio, unless ``plan`` is the plan
    `plan_portfolio_deletes` made for these ``uids``; then the delete counts nothing
    again. A portfolio that is missing, that account history references, that the caller
    does not manage, or that MetaTables' impact refuses for the whole table is reported in
    ``failed``. The others are deleted together in one transaction (issue 127).

    When the database refuses that transaction, nothing in it was deleted: a reference
    was written since the read, or a key from an application's own table holds rows of
    one of them. The read cannot tell which, so the portfolios are then deleted one per
    transaction, and only the refused ones are reported in ``failed``.
    """

    target_uids = _unique_uids(uids)
    if plan is None:
        plan = plan_portfolio_deletes(context, uids=target_uids)
    elif list(plan.uids) != target_uids:
        raise ValueError("The delete plan was made for another portfolio selection.")
    failed: dict[str, str] = {}
    allowed: list[_PlannedDelete] = []
    for uid in target_uids:
        planned = plan.portfolios.get(uid)
        if planned is None:
            failed[uid] = f"Portfolio {uid} was not found."
        elif plan.impact.blockers:
            failed[uid] = (
                f"{planned.label} cannot be deleted; nothing was deleted. "
                + " ".join(plan.impact.blockers)
            )
        elif planned.manager_blocker:
            failed[uid] = planned.manager_blocker
        elif planned.blockers:
            failed[uid] = _refusal(planned)
        else:
            allowed.append(planned)
    deleted, refused = _delete_together(context, allowed, impact=plan.impact)
    failed.update(refused)
    count = len(deleted)
    if count == 0:
        detail = "No portfolios were deleted."
    else:
        detail = (
            f"Deleted {count} portfolio{'s' if count != 1 else ''} with "
            f"{'its' if count == 1 else 'their'} datasets."
        )
    if failed:
        detail += f" {len(failed)} could not be deleted."
    return {
        "detail": detail,
        "deleted_count": count,
        "deleted": [_deleted_response(item) for item in deleted],
        "failed": [{"uid": uid, "detail": failed[uid]} for uid in target_uids if uid in failed],
    }


def preflight_bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Report what deleting the portfolios removes and what blocks it, without deleting.

    It runs the delete's own checks, so a portfolio it allows is deleted unless its
    references change in between or the database refuses it.
    """

    return plan_portfolio_deletes(context, uids=uids).preflight()


# The delete ------------------------------------------------------------------------------


def _delete_together(
    context: MarketsRepositoryContext,
    allowed: Sequence[_PlannedDelete],
    *,
    impact: PortfolioDeleteImpact,
) -> tuple[list[_PlannedDelete], dict[str, str]]:
    """Delete ``allowed`` in one transaction: the deleted ones, and the refused ones' reasons.

    A refused transaction deleted nothing; each portfolio is then deleted on its own, so
    that only those the database refuses stay.
    """

    if len(allowed) < 2:
        return _delete_each(context, allowed, impact=impact)
    try:
        result = portfolio_deletion_repository.delete_portfolios(
            context,
            portfolios=[(planned.uid, planned.unique_identifier) for planned in allowed],
        )
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        logger.info("Portfolio bulk delete refused; deleting each portfolio on its own.", error=str(exc))
        return _delete_each(context, allowed, impact=impact)
    if not result.get("rows"):
        # The guard stopped the list: a portfolio vanished, was renamed or was named by
        # account history since the read. Nothing was deleted.
        return _delete_each(context, allowed, impact=impact)
    return list(allowed), {}


def _delete_each(
    context: MarketsRepositoryContext,
    allowed: Sequence[_PlannedDelete],
    *,
    impact: PortfolioDeleteImpact,
) -> tuple[list[_PlannedDelete], dict[str, str]]:
    deleted: list[_PlannedDelete] = []
    refused: dict[str, str] = {}
    for planned in allowed:
        try:
            done = _delete_planned(context, planned, impact=impact)
        except (PortfolioDeleteConflictError, PermissionError) as exc:
            refused[planned.uid] = str(exc)
            continue
        if done:
            deleted.append(planned)
        else:
            refused[planned.uid] = f"Portfolio {planned.uid} was not found."
    return deleted, refused


def _delete_planned(
    context: MarketsRepositoryContext,
    planned: _PlannedDelete,
    *,
    impact: PortfolioDeleteImpact,
) -> bool:
    """Run one portfolio's transaction: ``False`` when it vanished in between."""

    if planned.manager_blocker:
        raise PermissionError(planned.manager_blocker)
    if planned.blockers:
        raise PortfolioDeleteConflictError(_refusal(planned))
    try:
        result = portfolio_deletion_repository.delete_portfolio(
            context,
            uid=planned.uid,
            unique_identifier=planned.unique_identifier,
        )
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        # Account history written since, or a RESTRICT key of an application's own table
        # that still holds rows of the portfolio: the database's message says which.
        current = _plan(context, [planned.uid], impact=impact).get(planned.uid)
        if current is not None and current.history_blockers:
            raise PortfolioDeleteConflictError(_refusal(current)) from exc
        raise PortfolioDeleteConflictError(
            f"{planned.label} cannot be deleted; nothing was deleted. The database refused "
            f"it: {exc} An application that keeps rows of the portfolio in its own table "
            "deletes them first."
        ) from exc
    if not result.get("rows"):
        # The guard stopped the list: the portfolio vanished, was renamed, or account
        # history named it in between. Nothing was deleted.
        current = _plan(context, [planned.uid], impact=impact).get(planned.uid)
        if current is None:
            return False
        if current.blockers:
            raise PortfolioDeleteConflictError(_refusal(current))
        raise PortfolioDeleteConflictError(
            f"{planned.label} changed while it was being deleted; nothing was deleted. "
            "Retry the delete."
        )
    return True


def _deleted_response(planned: _PlannedDelete) -> dict[str, Any]:
    return {
        "detail": f"{planned.label} deleted with its datasets.",
        "uid": planned.uid,
        "unique_identifier": planned.unique_identifier,
        "deleted_count": 1,
        "deleted_rows": dict(planned.row_counts),
    }


def _refusal(planned: _PlannedDelete) -> str:
    text = f"{planned.label} cannot be deleted; nothing was deleted. {' '.join(planned.blockers)}"
    if planned.history_blockers:
        text += f" {ACCOUNT_HISTORY_GUIDANCE}"
    return text


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


# The checks ------------------------------------------------------------------------------


def _plan(
    context: MarketsRepositoryContext,
    uids: Sequence[str],
    *,
    impact: PortfolioDeleteImpact,
) -> dict[str, _PlannedDelete]:
    """Count the portfolios' rows in their seven datasets and account history in one read."""

    counted = portfolio_deletion_repository.count_portfolio_delete_rows(context, uids=uids)
    plan: dict[str, _PlannedDelete] = {}
    for uid, row in counted.items():
        identifier = row["unique_identifier"]
        plan[uid] = _PlannedDelete(
            uid=uid,
            unique_identifier=identifier,
            row_counts={table.key: row[table.key] for table in PORTFOLIO_DATASET_TABLES},
            history_blockers=tuple(_history_blockers(row)),
            manager_blocker=manager_refusal(f"Portfolio {identifier!r}", row.get("managed_by")),
        )
    return plan


def _history_blockers(row: Mapping[str, Any]) -> list[str]:
    blockers = []
    for key, _model, _column in ACCOUNT_HISTORY_REFERENCES:
        count = int(row.get(key) or 0)
        if count > 0:
            blockers.append(
                _HISTORY_BLOCKERS[key].format(count=count, plural="s" if count != 1 else "")
            )
    return blockers


def _canonical_uid(uid: uuid.UUID | str) -> str:
    return str(uuid.UUID(str(uid)))


def _unique_uids(uids: Sequence[uuid.UUID | str]) -> list[str]:
    return list(dict.fromkeys(_canonical_uid(uid) for uid in uids))


__all__ = [
    "ACCOUNT_HISTORY_GUIDANCE",
    "PortfolioDeleteConflictError",
    "PortfolioDeleteImpact",
    "PortfolioDeletePlan",
    "bulk_delete_portfolio_records",
    "delete_portfolio_record",
    "plan_portfolio_deletes",
    "portfolio_delete_impact",
    "preflight_bulk_delete_portfolio_records",
]
