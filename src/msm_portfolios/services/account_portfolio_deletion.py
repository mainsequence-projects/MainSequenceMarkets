"""Delete accounts with the portfolios only they used (ADR 0050 decision 9, issue 91).

`DELETE /api/v1/account/{uid}/?delete_portfolios=true` and the account bulk-delete
action with its `delete_portfolios` option run these functions, and code running with
the portfolio runtime calls them directly::

    import msm_portfolios
    from msm_portfolios.services import delete_account_with_portfolios

    delete_account_with_portfolios(msm_portfolios.get_runtime().context, uid=account_uid)

Each account is deleted as core's `msm.services.delete_account` deletes it, with the
same checks and answers, in the same single transaction as the portfolios that its
virtual funds or target rows name and that nothing references once its history is
gone: their rows in every dataset and group memberships (by `CASCADE`), then the
portfolio. One read and one transaction per account. A portfolio is kept, and the answer
says why, when account history of another account references it (ADR 0049), when the
caller does not manage it (ADR 0060), or when a foreign key refuses its delete (an
application's own table that still holds rows of it); then the transaction deletes
nothing, and a second one deletes the account alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from metatables import MetaTableTransactionGuardError

from msm.repositories.base import MarketsRepositoryContext
from msm.services.accounts import deletion as account_deletion
from msm.services.accounts.deletion import AccountDeleteConflictError
from msm.api.managers import manager_refusal
from msm_portfolios.repositories import account_portfolio_deletion as repository
from msm_portfolios.repositories.account_portfolio_deletion import ACCOUNT_PORTFOLIOS_GUARD

PORTFOLIO_CHANGED_REASON = (
    "It changed while the account was being deleted, so the account was deleted alone. "
    "Check the portfolio and delete it on its own."
)
_REFERENCE_REASONS = {
    "virtual_funds": "{count} virtual fund{plural} of other accounts target{verb} it.",
    "target_positions": "{count} target-position row{plural} of other accounts name{verb} it.",
}


def preflight_account_delete_with_portfolios(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    together: Sequence[uuid.UUID | str] = (),
) -> dict[str, Any] | None:
    """What deleting one account with its portfolios removes, and what blocks it.

    One read. Returns `None` when the account does not exist. Core's plan
    (`row_counts`, `blockers`), with ``portfolios``, the portfolios the delete removes
    with their rows per dataset, and ``kept_portfolios``, the ones its history names that
    stay, with the reason. ``together`` are accounts deleted in the same transaction:
    their rows and history keep nothing (issue 128).
    """

    read = repository.read_account_with_portfolios(
        context,
        uid=account_deletion.canonical_uid(uid),
        together=account_deletion.unique_uids(together),
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
    return {
        **account_deletion.account_delete_plan(read),
        "portfolios": portfolios,
        "kept_portfolios": kept,
    }


def delete_account_with_portfolios(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Delete one account with its whole history and the portfolios only it used.

    Returns `None` when the account does not exist. Raises
    `msm.services.AccountDeleteConflictError` when a foreign key refuses the account's
    own delete; then nothing is deleted. Answers as `msm.services.delete_account` does,
    with ``deleted_portfolios``, each with its ``deleted_rows`` per dataset, and
    ``kept_portfolios``, each with its ``reason``.
    """

    plan = preflight_account_delete_with_portfolios(context, uid=uid)
    if plan is None:
        return None
    account_deletion.check_account_delete_blockers(plan)
    portfolios = plan["portfolios"]
    kept = list(plan["kept_portfolios"])
    try:
        result = account_deletion.run_account_delete(context, plan, _write(context, plan, portfolios))
    except MetaTableTransactionGuardError as exc:
        if exc.label != ACCOUNT_PORTFOLIOS_GUARD:
            raise
        # A portfolio was referenced or removed in between; nothing was deleted.
        kept.extend(_kept(portfolio, PORTFOLIO_CHANGED_REASON) for portfolio in portfolios)
        portfolios = []
        result = account_deletion.run_account_delete(context, plan)
    except AccountDeleteConflictError as exc:
        if not portfolios:
            raise
        # A key the read could not see, such as one from another application's table,
        # refused the transaction, which deleted nothing. Delete the account alone: if a
        # key refuses that too, it is the account's own and nothing is deleted.
        refused = str(exc.__cause__ or exc)
        result = account_deletion.run_account_delete(context, plan)
        kept.extend(
            _kept(
                portfolio,
                f"A foreign key refused its delete, so the account was deleted alone: {refused}",
            )
            for portfolio in portfolios
        )
        portfolios = []
    if not result.get("rows"):
        account_deletion.account_delete_refused(context, plan)
        return None
    if portfolios:
        # The portfolios' statement returns the rows it deleted, with their identifiers now.
        returned = {
            account_deletion.canonical_uid(row["uid"]): str(row.get("unique_identifier") or "")
            for row in result["rows"]
        }
        portfolios = [
            {**portfolio, "unique_identifier": returned.get(portfolio["uid"]) or portfolio["unique_identifier"]}
            for portfolio in portfolios
        ]
    return _deleted_response(plan, portfolios, kept)


def bulk_delete_accounts_with_portfolios(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    table_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    """Delete every selected account that may go, with the portfolios only the selection
    used, together, and report the rest (issue 128).

    One read per account, each counting the other selected accounts as deleted with it,
    so a portfolio only selected accounts use goes with them; then one transaction for
    every account that may go and those portfolios. An account that is missing or
    blocked is reported in ``failed``; ``table_blockers`` report every account. When the
    database refuses the transaction, which then deletes nothing, each account is
    deleted on its own with its portfolios, so only the refused ones stay.
    """

    target = account_deletion.unique_uids(uids)
    plans = {
        uid: plan
        for uid in target
        if (plan := preflight_account_delete_with_portfolios(context, uid=uid, together=target))
        is not None
    }
    allowed, failed = account_deletion.partition_account_deletes(target, plans, table_blockers)
    # A portfolio several selected accounts name is reported with the first of them.
    owned: dict[str, list[Mapping[str, Any]]] = {}
    seen: set[str] = set()
    for plan in allowed:
        owned[plan["uid"]] = [item for item in plan["portfolios"] if item["uid"] not in seen]
        seen.update(item["uid"] for item in plan["portfolios"])
    portfolio_uids = [item["uid"] for plan in allowed for item in owned[plan["uid"]]]
    write = (
        repository.build_delete_accounts_with_portfolios_operation(
            context,
            accounts=[(plan["uid"], plan["unique_identifier"]) for plan in allowed],
            row_counts=account_deletion.summed_row_counts(allowed),
            portfolio_uids=portfolio_uids,
        )
        if allowed and portfolio_uids
        else None
    )
    deleted: list[dict[str, Any]] = []
    if allowed and account_deletion.run_accounts_delete(context, allowed, write) is not None:
        deleted = [
            _deleted_response(plan, owned[plan["uid"]], plan["kept_portfolios"]) for plan in allowed
        ]
    else:
        for plan in allowed:
            try:
                result = delete_account_with_portfolios(context, uid=plan["uid"])
            except AccountDeleteConflictError as exc:
                failed[plan["uid"]] = str(exc)
                continue
            if result is None:
                failed[plan["uid"]] = f"Account {plan['uid']} was not found."
                continue
            deleted.append(result)
    count = len(deleted)
    if count == 0:
        detail = "No accounts were deleted."
    else:
        detail = f"Deleted {_count(count, 'account')} with {'its' if count == 1 else 'their'} history"
        portfolio_count = sum(len(item["deleted_portfolios"]) for item in deleted)
        if portfolio_count:
            detail += f" and {_count(portfolio_count, 'portfolio')}"
        detail += "."
    return account_deletion.bulk_accounts_response(detail, deleted, failed, target)


def preflight_bulk_delete_accounts_with_portfolios(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Report what deleting the accounts with their portfolios removes, without deleting.

    One read per account, and MetaTables' delete impact for the account table. Each
    account is read counting the other selected accounts as deleted with it; a warning
    names each portfolio deleted or kept.
    """

    target_uids = account_deletion.unique_uids(uids)
    accounts = [
        plan
        for plan in (
            preflight_account_delete_with_portfolios(context, uid=uid, together=target_uids)
            for uid in target_uids
        )
        if plan is not None
    ]
    # As the delete reports it: a portfolio several accounts that may go name is listed
    # with the first of them.
    seen: set[str] = set()
    for item in accounts:
        if item["blockers"]:
            continue
        mine = [portfolio for portfolio in item["portfolios"] if portfolio["uid"] not in seen]
        seen.update(portfolio["uid"] for portfolio in item["portfolios"])
        item["portfolios"] = mine
    summary = account_deletion.summarize_account_delete_preflight(
        target_uids,
        accounts,
        account_deletion.account_delete_impact(),
    )
    for item in accounts:
        label = _account_label(item)
        summary["warnings"].extend(
            f"{label}: portfolio {portfolio['unique_identifier']!r} is deleted with it, with "
            "its rows in every dataset."
            for portfolio in item["portfolios"]
        )
        summary["warnings"].extend(
            f"{label}: portfolio {portfolio['unique_identifier']!r} is kept. {portfolio['reason']}"
            for portfolio in item["kept_portfolios"]
        )
    portfolio_count = sum(len(item["portfolios"]) for item in accounts)
    if summary["allowed"] and portfolio_count:
        summary["detail"] = (
            f"{summary['detail'].removesuffix('.')} and {_count(portfolio_count, 'portfolio')}."
        )
    return summary


def _write(
    context: MarketsRepositoryContext,
    plan: Mapping[str, Any],
    portfolios: Sequence[Mapping[str, Any]],
) -> Any:
    if not portfolios:
        return None
    return repository.build_delete_account_with_portfolios_operation(
        context,
        uid=plan["uid"],
        unique_identifier=plan["unique_identifier"],
        row_counts=plan["row_counts"],
        portfolio_uids=[portfolio["uid"] for portfolio in portfolios],
    )


def _deleted_response(
    plan: Mapping[str, Any],
    portfolios: Sequence[Mapping[str, Any]],
    kept: Sequence[dict[str, str]],
) -> dict[str, Any]:
    detail = f"{_account_label(plan)} deleted with its history"
    if portfolios:
        detail += f" and {_count(len(portfolios), 'portfolio')}"
    detail += "."
    if kept:
        detail += f" {_count(len(kept), 'portfolio')} it used {'was' if len(kept) == 1 else 'were'} kept."
    return {
        **account_deletion.account_deleted_response(plan),
        "detail": detail,
        "deleted_portfolios": [
            {
                "uid": portfolio["uid"],
                "unique_identifier": portfolio["unique_identifier"],
                "deleted_rows": dict(portfolio["row_counts"]),
            }
            for portfolio in portfolios
        ],
        "kept_portfolios": list(kept),
    }


def _kept_reasons(portfolio: Mapping[str, Any]) -> list[str]:
    """Why a portfolio the account's history names stays when the account goes."""

    reasons = [
        _REFERENCE_REASONS[key].format(
            count=count,
            plural="s" if count != 1 else "",
            verb="" if count != 1 else "s",
        )
        for key, count in portfolio["references"].items()
        if count > 0
    ]
    refusal = manager_refusal(
        f"Portfolio {portfolio['unique_identifier']!r}", portfolio.get("managed_by")
    )
    if refusal is not None:
        reasons.append(refusal)
    return reasons


def _kept(portfolio: Mapping[str, Any], reason: str) -> dict[str, str]:
    return {
        "uid": portfolio["uid"],
        "unique_identifier": portfolio["unique_identifier"],
        "reason": reason,
    }


def _account_label(plan: Mapping[str, Any]) -> str:
    return f"Account {plan['unique_identifier']!r}"


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


__all__ = [
    "PORTFOLIO_CHANGED_REASON",
    "bulk_delete_accounts_with_portfolios",
    "delete_account_with_portfolios",
    "preflight_account_delete_with_portfolios",
    "preflight_bulk_delete_accounts_with_portfolios",
]
