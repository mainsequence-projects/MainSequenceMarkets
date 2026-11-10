"""Portfolio retirement (ADR 0049).

A retired portfolio keeps every row that names it: account target snapshots,
virtual funds and their holdings, and its own weights and values. From
``retired_at`` on it cannot be named by a new target snapshot, no virtual-fund
holdings are written for it, discovery leaves it out and the portfolio updaters
write nothing. Retiring is refused while an account's current target names it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext


class PortfolioRetiredError(ValueError):
    """A write named a portfolio that is retired."""

    def __init__(self, retired: Mapping[str, dt.datetime], *, action: str) -> None:
        self.retired = dict(retired)
        listed = ", ".join(
            f"{uid} (retired at {retired_at.isoformat()})"
            for uid, retired_at in sorted(self.retired.items())
        )
        super().__init__(f"{action} names a retired portfolio: {listed}.")


class PortfolioRetirementConflictError(ValueError):
    """Retiring was refused because accounts' current targets name the portfolio."""

    def __init__(self, *, portfolio_uid: str, account_count: int) -> None:
        self.portfolio_uid = portfolio_uid
        self.account_count = account_count
        accounts = "account's" if account_count == 1 else "accounts'"
        super().__init__(
            f"Portfolio {portfolio_uid} cannot be retired: {account_count} {accounts} current "
            "target names it. GET /api/v1/portfolio/{uid}/account-targets/ lists them; "
            "write their targets without it first."
        )


def retired_portfolios(
    context: MarketsRepositoryContext,
    portfolio_uids: Iterable[Any],
    *,
    as_of: dt.datetime | None = None,
) -> dict[str, dt.datetime]:
    """Return ``{portfolio uid: retired_at}`` for the listed portfolios that are retired.

    With ``as_of``, only portfolios retired at or before that time are returned.
    """

    from msm.models import PortfolioTable
    from msm.repositories.crud import search_model

    uids = sorted({str(uuid.UUID(str(value))) for value in portfolio_uids if value not in (None, "")})
    if not uids:
        return {}
    rows = operation_result_rows(
        search_model(
            context,
            model=PortfolioTable,
            in_filters={"uid": uids},
            limit=len(uids),
        )
    )
    retired: dict[str, dt.datetime] = {}
    for row in rows:
        if row.get("retired_at") in (None, ""):
            continue
        retired_at = _utc(row["retired_at"])
        if as_of is None or retired_at <= _utc(as_of):
            retired[str(row["uid"])] = retired_at
    return retired


def retired_portfolios_from_rows(
    portfolio_uids: Iterable[Any],
    *,
    as_of: dt.datetime | None = None,
) -> dict[str, dt.datetime]:
    """``retired_portfolios`` through the ``Portfolio`` row API of the active runtime.

    For SDK writers that run without a repository context; one read per portfolio.
    """

    from msm.api.portfolios import Portfolio

    retired: dict[str, dt.datetime] = {}
    for value in sorted({str(value) for value in portfolio_uids if value not in (None, "")}):
        portfolio = Portfolio.get_by_uid(value)
        retired_at = getattr(portfolio, "retired_at", None)
        if retired_at is None:
            continue
        retired_at = _utc(retired_at)
        if as_of is None or retired_at <= _utc(as_of):
            retired[value] = retired_at
    return retired


def count_current_portfolio_targets(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str,
) -> int:
    """Count the accounts whose current target names the portfolio."""

    from msm.repositories.accounts import count_portfolio_account_targets

    rows = operation_result_rows(
        count_portfolio_account_targets(context, portfolio_uid=portfolio_uid)
    )
    return int(rows[0]["count"]) if rows else 0


def retire_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Retire a portfolio at the current UTC time and return its row.

    Returns ``None`` for an unknown portfolio and the row unchanged for a retired
    one. Raises ``PortfolioRetirementConflictError`` while an account's current
    target names the portfolio. The update checks this in the same statement;
    a second read afterwards undoes the retirement if a target write that named
    the portfolio committed while the update ran.
    """

    from msm.repositories.portfolios import clear_portfolio_retirement, retire_portfolio

    existing = _portfolio_row(context, uid=uid)
    if existing is None:
        return None
    portfolio_uid = str(existing["uid"])
    if existing.get("retired_at") is not None:
        return existing

    retired_at = dt.datetime.now(dt.UTC)
    retired = _first(retire_portfolio(context, uid=portfolio_uid, retired_at=retired_at))
    if retired is None:
        current = _portfolio_row(context, uid=portfolio_uid)
        if current is None:
            return None
        if current.get("retired_at") is not None:
            return current
        raise PortfolioRetirementConflictError(
            portfolio_uid=portfolio_uid,
            account_count=count_current_portfolio_targets(context, portfolio_uid=portfolio_uid),
        )

    account_count = count_current_portfolio_targets(context, portfolio_uid=portfolio_uid)
    if account_count:
        clear_portfolio_retirement(context, uid=portfolio_uid, retired_at=retired_at)
        raise PortfolioRetirementConflictError(
            portfolio_uid=portfolio_uid,
            account_count=account_count,
        )
    return retired


def reinstate_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Clear ``retired_at`` and return the row; ``None`` for an unknown portfolio."""

    from msm.repositories.portfolios import clear_portfolio_retirement

    return _first(clear_portfolio_retirement(context, uid=uid))


def _portfolio_row(context: MarketsRepositoryContext, *, uid: uuid.UUID | str) -> dict[str, Any] | None:
    from msm.models import PortfolioTable
    from msm.repositories.crud import get_model_by_uid

    return _first(get_model_by_uid(context, model=PortfolioTable, uid=uid))


def _first(result: Any) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return dict(rows[0]) if rows else None


def _utc(value: Any) -> dt.datetime:
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value)
    if not isinstance(value, dt.datetime):
        raise TypeError(f"Expected a datetime, got {value!r}.")
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


__all__ = [
    "PortfolioRetiredError",
    "PortfolioRetirementConflictError",
    "count_current_portfolio_targets",
    "reinstate_portfolio_record",
    "retire_portfolio_record",
    "retired_portfolios",
    "retired_portfolios_from_rows",
]
