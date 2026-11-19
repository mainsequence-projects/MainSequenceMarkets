"""Delete an account with the portfolios only it used, in one read and one transaction.

The portfolio package owns this delete (ADR 0050 decision 9, issue 91): the portfolio
datasets are defined here, and core ``msm`` does not import this package (ADR 0019). It
composes core's account delete, `msm.repositories.account_deletion`, with the
portfolios' own statements:

- one read: core's read of the account, with one row per portfolio the account's
  virtual funds or target rows name;
- one statement list: core's account statements, then the portfolios' rows in each of
  their datasets and the portfolio rows. Each portfolio statement keeps only the
  portfolios that no account history references once the account's own history is gone.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, union

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import PortfolioDatasetAvailabilityTable, PortfolioTable
from msm.repositories.account_deletion import (
    ACCOUNT_HISTORY_REFERENCES,
    account_delete_read_row,
    account_delete_read_statement,
    account_delete_statements,
    account_history_filters,
    account_history_reference,
)
from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    resolve_markets_sql_target,
    with_delete_deadline,
    with_max_rows,
)
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES

ACCOUNT_PORTFOLIOS_GUARD = "portfolios"
"""Guard label of the last statement: each portfolio read as deletable is deleted, or
nothing is."""

ACCOUNT_DELETE_READ_MAX_ROWS = 10_000
"""Rows the read may return, one per portfolio the account names (MetaTables' maximum)."""


def unreferenced_portfolios(portfolio_uids: Sequence[uuid.UUID]) -> Any:
    """The portfolios among ``portfolio_uids`` that no account history references."""

    condition = PortfolioTable.uid.in_(portfolio_uids)
    for _key, model, column in ACCOUNT_HISTORY_REFERENCES:
        condition = condition & ~account_history_reference(model, column)
    return condition


def account_portfolio_delete_statements(
    portfolio_uids: Sequence[uuid.UUID | str],
) -> list[GuardedStatement | Any]:
    """The portfolios' rows in each dataset, then the portfolio rows.

    Each statement keeps only the portfolios no account history references. The last is
    guarded: it must delete every one of them, or nothing is deleted.
    """

    uids = sorted({uuid.UUID(str(uid)) for uid in portfolio_uids})
    identifiers = select(PortfolioTable.unique_identifier).where(unreferenced_portfolios(uids))
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(table.model.portfolio_identifier.in_(identifiers))
        for table in PORTFOLIO_DATASET_TABLES
    ]
    statements.append(
        GuardedStatement(
            delete(PortfolioTable)
            .where(unreferenced_portfolios(uids))
            .returning(PortfolioTable.uid, PortfolioTable.unique_identifier),
            expect_rows=len(uids),
            label=ACCOUNT_PORTFOLIOS_GUARD,
        )
    )
    return statements


def account_with_portfolios_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    portfolio_uids: Sequence[uuid.UUID | str],
) -> list[GuardedStatement | Any]:
    """Core's account statements, then the portfolios': one transaction, at most 22."""

    return [
        *account_delete_statements(uid=uid, unique_identifier=unique_identifier),
        *account_portfolio_delete_statements(portfolio_uids),
    ]


def build_delete_account_with_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    portfolio_uids: Sequence[uuid.UUID | str],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the account and portfolio delete, run with the delete's deadline."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        account_with_portfolios_delete_statements(
            uid=uid,
            unique_identifier=unique_identifier,
            portfolio_uids=portfolio_uids,
        ),
        context=with_max_rows(with_delete_deadline(context), max(len(portfolio_uids), 1)),
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def _label(name: str) -> str:
    # Keys such as ``values`` and ``state`` are SQL keywords; the labels never are.
    return f"portfolio_{name}"


def build_read_account_with_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """One read: core's account read, with one row per portfolio its history names.

    Per portfolio: the account history of other accounts that references it, its
    catalog row's values and weights instances, and its rows in each dataset.
    """

    filters = account_history_filters(uid)
    named = union(
        *(
            select(getattr(model, column).label("portfolio_uid")).where(filters[key]())
            for key, model, column in ACCOUNT_HISTORY_REFERENCES
        )
    )
    statement = (
        account_delete_read_statement(uid)
        .add_columns(
            PortfolioTable.uid.label(_label("uid")),
            PortfolioTable.unique_identifier.label(_label("identifier")),
            # Account history of other accounts: it stays when this account goes.
            *(
                select(func.count())
                .select_from(model)
                .where((getattr(model, column) == PortfolioTable.uid) & ~filters[key]())
                .scalar_subquery()
                .label(_label(key))
                for key, model, column in ACCOUNT_HISTORY_REFERENCES
            ),
            *(
                getattr(PortfolioDatasetAvailabilityTable, table.catalog_column).label(
                    table.catalog_column
                )
                for table in PORTFOLIO_DATASET_TABLES
                if table.catalog_column
            ),
            *(
                select(func.count())
                .select_from(table.model)
                .where(table.model.portfolio_identifier == PortfolioTable.unique_identifier)
                .scalar_subquery()
                .label(_label(f"{table.key}_rows"))
                for table in PORTFOLIO_DATASET_TABLES
            ),
        )
        .outerjoin(PortfolioTable, PortfolioTable.uid.in_(named))
        .outerjoin(
            PortfolioDatasetAvailabilityTable,
            PortfolioDatasetAvailabilityTable.portfolio_uid == PortfolioTable.uid,
        )
    )
    return compile_markets_statement(
        statement,
        context=with_max_rows(with_delete_deadline(context), ACCOUNT_DELETE_READ_MAX_ROWS),
        operation="select",
        dialect=dialect,
    )


def read_account_with_portfolios(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """What deleting the account with its portfolios removes, in one read.

    Answers ``None`` when the account does not exist. Otherwise core's
    `account_delete_read_row` with ``portfolios``: per portfolio its ``uid`` and
    ``unique_identifier``, the account history of other accounts that references it
    (``references``, by key of `ACCOUNT_HISTORY_REFERENCES`), its ``catalog`` instance
    uids and its ``row_counts`` per dataset.
    """

    result = execute_markets_operation(
        build_read_account_with_portfolios_operation(context, uid=uid),
        context=context,
    )
    rows = result.get("rows") or []
    if not rows:
        return None
    if result.get("truncated"):
        raise ValueError(
            f"Account {uid} names more portfolios than one read returns "
            f"({ACCOUNT_DELETE_READ_MAX_ROWS}). Delete it without its portfolios."
        )
    read = account_delete_read_row(rows[0])
    read["portfolios"] = sorted(
        (
            {
                "uid": str(uuid.UUID(str(row[_label("uid")]))),
                "unique_identifier": str(row.get(_label("identifier")) or ""),
                "references": {
                    key: int(row.get(_label(key)) or 0)
                    for key, _model, _column in ACCOUNT_HISTORY_REFERENCES
                },
                "catalog": {
                    table.catalog_column: _string_or_none(row.get(table.catalog_column))
                    for table in PORTFOLIO_DATASET_TABLES
                    if table.catalog_column
                },
                "row_counts": {
                    table.key: int(row.get(_label(f"{table.key}_rows")) or 0)
                    for table in PORTFOLIO_DATASET_TABLES
                },
            }
            for row in rows
            if row.get(_label("uid")) is not None
        ),
        key=lambda portfolio: (portfolio["unique_identifier"], portfolio["uid"]),
    )
    return read


def _string_or_none(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


__all__ = [
    "ACCOUNT_DELETE_READ_MAX_ROWS",
    "ACCOUNT_PORTFOLIOS_GUARD",
    "account_portfolio_delete_statements",
    "account_with_portfolios_delete_statements",
    "build_delete_account_with_portfolios_operation",
    "build_read_account_with_portfolios_operation",
    "read_account_with_portfolios",
    "unreferenced_portfolios",
]
