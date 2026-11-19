"""Delete a portfolio with its own datasets (ADR 0049, issue 93).

The delete is an ordered statement list that MetaTables runs in one transaction on
PostgreSQL and on SQLite (MetaTables ADR 0026), as the account delete is (ADR 0050).
Every statement targets a table in the Markets namespace: the portfolio's rows in its
seven datasets, then the portfolio row. Rows in another application's table are never
deleted here; their `RESTRICT` keys refuse the delete instead.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, Uuid, bindparam, delete, func, literal, select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import PortfolioDatasetAvailabilityTable, PortfolioTable, VirtualFundTable
from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    with_max_rows,
)
from msm.time_index.accounts.storage import TargetPositionsStorage
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioAnalyticsStorage,
    PortfolioCashFlowsStorage,
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
    PortfoliosStorage,
    PortfolioStateStorage,
    PortfolioWeightsStorage,
)

PORTFOLIO_DELETE_GUARD = "portfolio"
"""Guard label of the last statement: the portfolio row, with the identifier read before."""


@dataclass(frozen=True)
class PortfolioDatasetTable:
    """One of the portfolio's own Markets datasets, keyed by ``portfolio_identifier``."""

    key: str
    model: type[Any]

    @property
    def table_name(self) -> str:
        return str(self.model.__table__.name)


PORTFOLIO_DATASET_TABLES: tuple[PortfolioDatasetTable, ...] = (
    PortfolioDatasetTable("weights", PortfolioWeightsStorage),
    PortfolioDatasetTable("values", PortfoliosStorage),
    PortfolioDatasetTable("rebalance_state", PortfolioRebalanceStateStorage),
    PortfolioDatasetTable("analytics", PortfolioAnalyticsStorage),
    PortfolioDatasetTable("event_ledger", PortfolioEventLedgerStorage),
    PortfolioDatasetTable("state", PortfolioStateStorage),
    PortfolioDatasetTable("cash_flows", PortfolioCashFlowsStorage),
)
"""The seven Markets tables whose ``RESTRICT`` key on ``Portfolio.unique_identifier`` the
delete clears, in the order its statements run."""

ACCOUNT_HISTORY_REFERENCES: tuple[tuple[str, type[Any], str], ...] = (
    ("virtual_funds", VirtualFundTable, "target_portfolio_uid"),
    ("target_positions", TargetPositionsStorage, "portfolio_uid"),
)
"""Account history that references ``Portfolio.uid`` with ``RESTRICT``: the delete never
removes it, so any such row refuses the delete (ADR 0049 decision 1)."""

CATALOG_TABLE_KEYS = ("values_meta_table_uid", "weights_meta_table_uid")
"""The catalog columns that can place the portfolio's values or weights in an instance."""


@dataclass(frozen=True)
class _PortfolioScope:
    uid: uuid.UUID
    unique_identifier: str

    def portfolio_uid(self) -> Any:
        return bindparam("portfolio_uid", value=self.uid, type_=Uuid(as_uuid=True))

    def portfolio_identifier(self) -> Any:
        return bindparam("portfolio_identifier", value=self.unique_identifier, type_=String())


def _scope(uid: uuid.UUID | str, unique_identifier: str) -> _PortfolioScope:
    identifier = str(unique_identifier or "").strip()
    if not identifier:
        raise ValueError("Deleting a portfolio requires its unique_identifier.")
    return _PortfolioScope(uid=uuid.UUID(str(uid)), unique_identifier=identifier)


def _history_reference(model: type[Any], column: str) -> Any:
    """Whether a row of ``model`` names the portfolio row the statement deletes."""

    return (
        select(literal(1))
        .select_from(model)
        .where(getattr(model, column) == PortfolioTable.uid)
        .exists()
    )


def portfolio_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> list[GuardedStatement | Any]:
    """The portfolio delete as ordered statements for one transaction.

    The seven datasets go first, then the portfolio row. The last statement is guarded:
    it must delete exactly the portfolio read before, with the same
    ``unique_identifier``, while no virtual fund or account target row names it, or
    nothing is deleted.
    """

    scope = _scope(uid, unique_identifier)
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(table.model.portfolio_identifier == scope.portfolio_identifier())
        for table in PORTFOLIO_DATASET_TABLES
    ]
    portfolio_row = (
        delete(PortfolioTable)
        .where(PortfolioTable.uid == scope.portfolio_uid())
        .where(PortfolioTable.unique_identifier == scope.portfolio_identifier())
    )
    for _key, model, column in ACCOUNT_HISTORY_REFERENCES:
        portfolio_row = portfolio_row.where(~_history_reference(model, column))
    statements.append(
        GuardedStatement(
            portfolio_row.returning(PortfolioTable.uid, PortfolioTable.unique_identifier),
            expect_rows=1,
            label=PORTFOLIO_DELETE_GUARD,
        )
    )
    return statements


def build_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the portfolio delete for the context's DataSource."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        portfolio_delete_statements(uid=uid, unique_identifier=unique_identifier),
        context=context,
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def delete_portfolio(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> dict[str, Any]:
    """Delete the portfolio and its rows in its seven datasets, or nothing.

    Answers with the deleted portfolio row, or with no rows when the guard stopped the
    list: the portfolio no longer exists under ``unique_identifier``, or account
    history names it. A foreign key that refuses the delete raises the MetaTables
    error, and nothing is deleted.
    """

    return execute_markets_write(
        build_delete_portfolio_operation(context, uid=uid, unique_identifier=unique_identifier),
        context=context,
        refused_by=(PORTFOLIO_DELETE_GUARD,),
    )


def build_count_portfolio_delete_rows_operation(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """One read: each portfolio, its catalogued instances and the rows its delete reaches.

    Per portfolio it returns ``uid``, ``unique_identifier``, the catalog's
    ``values_meta_table_uid`` and ``weights_meta_table_uid``, the rows in each of the
    seven datasets, and the account-history rows that block the delete.
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
            *(
                getattr(PortfolioDatasetAvailabilityTable, key).label(key)
                for key in CATALOG_TABLE_KEYS
            ),
            *counts,
        )
        .select_from(PortfolioTable)
        .outerjoin(
            PortfolioDatasetAvailabilityTable,
            PortfolioDatasetAvailabilityTable.portfolio_uid == PortfolioTable.uid,
        )
        .where(PortfolioTable.uid.in_(portfolio_uids))
    )
    return compile_markets_statement(
        statement,
        context=with_max_rows(context, max(len(portfolio_uids), 1)),
        operation="select",
        dialect=dialect,
    )


def count_portfolio_delete_rows(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, dict[str, Any]]:
    """Per existing portfolio uid: its identifier, catalogued instances and row counts.

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
            **{key: _string_or_none(row.get(key)) for key in CATALOG_TABLE_KEYS},
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
    "ACCOUNT_HISTORY_REFERENCES",
    "CATALOG_TABLE_KEYS",
    "PORTFOLIO_DATASET_TABLES",
    "PORTFOLIO_DELETE_GUARD",
    "PortfolioDatasetTable",
    "build_count_portfolio_delete_rows_operation",
    "build_delete_portfolio_operation",
    "count_portfolio_delete_rows",
    "delete_portfolio",
    "portfolio_delete_statements",
]
