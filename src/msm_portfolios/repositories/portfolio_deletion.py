"""Delete portfolios with their own datasets (ADR 0049, issues 93 and 127).

The delete is an ordered statement list that MetaTables runs in one transaction on
PostgreSQL and on SQLite (MetaTables ADR 0026), as the account delete is (ADR 0050).
Every statement targets a table in the Markets namespace: the portfolios' rows in their
seven datasets, then the portfolio rows. One list deletes one portfolio or a whole
selection. Rows in another application's table are never deleted here; their `RESTRICT`
keys refuse the delete instead (ADR 0060).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import PortfolioTable
from msm.repositories.account_deletion import ACCOUNT_HISTORY_REFERENCES, account_history_reference
from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    with_delete_deadline,
    with_max_rows,
)
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES

PORTFOLIO_DELETE_GUARD = "portfolio"
"""Guard label of the last statement: every portfolio row, with the identifier read before."""


@dataclass(frozen=True)
class _PortfolioScope:
    uids: tuple[uuid.UUID, ...]
    unique_identifiers: tuple[str, ...]


def _scope(portfolios: Sequence[tuple[uuid.UUID | str, str]]) -> _PortfolioScope:
    pairs: dict[uuid.UUID, str] = {}
    for uid, unique_identifier in portfolios:
        identifier = str(unique_identifier or "").strip()
        if not identifier:
            raise ValueError("Deleting a portfolio requires its unique_identifier.")
        pairs[uuid.UUID(str(uid))] = identifier
    if not pairs:
        raise ValueError("Deleting portfolios requires at least one portfolio.")
    return _PortfolioScope(uids=tuple(pairs), unique_identifiers=tuple(pairs.values()))


def portfolios_delete_statements(
    portfolios: Sequence[tuple[uuid.UUID | str, str]],
) -> list[GuardedStatement | Any]:
    """The delete of ``portfolios``, ``(uid, unique_identifier)`` pairs, for one transaction.

    The seven datasets go first, each in one statement for every portfolio, then the
    portfolio rows. The last statement is guarded: it must delete exactly the portfolios
    read before, each with its ``unique_identifier``, while no virtual fund or account
    target row names any of them, or nothing is deleted.
    """

    scope = _scope(portfolios)
    identifiers = list(scope.unique_identifiers)
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(table.model.portfolio_identifier.in_(identifiers))
        for table in PORTFOLIO_DATASET_TABLES
    ]
    portfolio_rows = (
        delete(PortfolioTable)
        .where(PortfolioTable.uid.in_(list(scope.uids)))
        .where(PortfolioTable.unique_identifier.in_(identifiers))
    )
    for _key, model, column in ACCOUNT_HISTORY_REFERENCES:
        portfolio_rows = portfolio_rows.where(~account_history_reference(model, column))
    statements.append(
        GuardedStatement(
            portfolio_rows.returning(PortfolioTable.uid, PortfolioTable.unique_identifier),
            expect_rows=len(scope.uids),
            label=PORTFOLIO_DELETE_GUARD,
        )
    )
    return statements


def portfolio_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> list[GuardedStatement | Any]:
    """One portfolio's delete as ordered statements for one transaction."""

    return portfolios_delete_statements([(uid, unique_identifier)])


def build_delete_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    portfolios: Sequence[tuple[uuid.UUID | str, str]],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the delete of ``portfolios`` for the context's DataSource.

    The transaction may run for MetaTables' longest deadline (`with_delete_deadline`):
    the 15 s default covers the whole list, and portfolios with long series can take
    longer to delete (ADR 0049).
    """

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        portfolios_delete_statements(portfolios),
        context=with_max_rows(with_delete_deadline(context), max(len(portfolios), 1)),
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def build_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile one portfolio's delete for the context's DataSource."""

    return build_delete_portfolios_operation(
        context, portfolios=[(uid, unique_identifier)], dialect=dialect
    )


def delete_portfolios(
    context: MarketsRepositoryContext,
    *,
    portfolios: Sequence[tuple[uuid.UUID | str, str]],
) -> dict[str, Any]:
    """Delete ``portfolios`` and their rows in their seven datasets, all or nothing.

    Answers with the deleted portfolio rows, or with no rows when the guard stopped the
    list: a portfolio no longer exists under its ``unique_identifier``, or account
    history names it. A foreign key that refuses the delete raises the MetaTables
    error. Either way nothing is deleted.
    """

    return execute_markets_write(
        build_delete_portfolios_operation(context, portfolios=portfolios),
        context=context,
        refused_by=(PORTFOLIO_DELETE_GUARD,),
    )


def delete_portfolio(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> dict[str, Any]:
    """Delete one portfolio and its rows in its seven datasets, or nothing."""

    return delete_portfolios(context, portfolios=[(uid, unique_identifier)])


def build_count_portfolio_delete_rows_operation(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """One read: each portfolio, its manager and the rows its delete reaches.

    Per portfolio it returns ``uid``, ``unique_identifier``, ``managed_by``, the rows in
    each of the seven datasets, and the account-history rows that block the delete. Each count runs
    per portfolio row and reads only that portfolio's rows, through the dataset's
    ``(portfolio_identifier, time_index)`` index (revisions 0026 and 0031, issue 96).
    """

    portfolio_uids = [uuid.UUID(str(uid)) for uid in uids]
    counts = [
        select(func.count())
        .select_from(table.model)
        .where(table.model.portfolio_identifier == PortfolioTable.unique_identifier)
        .scalar_subquery()
        .label(_count_label(table.key))
        for table in PORTFOLIO_DATASET_TABLES
    ]
    counts.extend(
        select(func.count())
        .select_from(model)
        .where(getattr(model, column) == PortfolioTable.uid)
        .scalar_subquery()
        .label(_count_label(key))
        for key, model, column in ACCOUNT_HISTORY_REFERENCES
    )
    statement = (
        select(
            PortfolioTable.uid.label("uid"),
            PortfolioTable.unique_identifier.label("unique_identifier"),
            PortfolioTable.managed_by.label("managed_by"),
            *counts,
        )
        .select_from(PortfolioTable)
        .where(PortfolioTable.uid.in_(portfolio_uids))
    )
    return compile_markets_statement(
        statement,
        context=with_max_rows(with_delete_deadline(context), max(len(portfolio_uids), 1)),
        operation="select",
        dialect=dialect,
    )


def count_portfolio_delete_rows(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, dict[str, Any]]:
    """Per existing portfolio uid: its identifier, manager and row counts.

    A uid that names no portfolio is absent from the answer.
    """

    if not uids:
        return {}
    result = execute_markets_operation(
        build_count_portfolio_delete_rows_operation(context, uids=uids),
        context=context,
    )
    counted: dict[str, dict[str, Any]] = {}
    for row in result.get("rows") or []:
        uid = str(uuid.UUID(str(row["uid"])))
        counted[uid] = {
            "uid": uid,
            "unique_identifier": str(row.get("unique_identifier") or ""),
            "managed_by": _string_or_none(row.get("managed_by")),
            **{
                key: int(row.get(_count_label(key)) or 0)
                for key in (
                    *(table.key for table in PORTFOLIO_DATASET_TABLES),
                    *(key for key, _model, _column in ACCOUNT_HISTORY_REFERENCES),
                )
            },
        }
    return counted


def _count_label(key: str) -> str:
    # Keys such as ``values`` and ``state`` are SQL keywords; the labels never are.
    return f"{key}_rows"


def _string_or_none(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


__all__ = [
    "PORTFOLIO_DELETE_GUARD",
    "build_count_portfolio_delete_rows_operation",
    "build_delete_portfolio_operation",
    "build_delete_portfolios_operation",
    "count_portfolio_delete_rows",
    "delete_portfolio",
    "delete_portfolios",
    "portfolio_delete_statements",
    "portfolios_delete_statements",
]
