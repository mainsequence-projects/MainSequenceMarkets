"""Delete an account with its whole history, and the portfolios only it used (ADR 0050).

The delete is an ordered statement list that MetaTables runs in one transaction on
PostgreSQL and on SQLite (MetaTables ADR 0026). Every statement targets a table in
the Markets namespace. Rows in another application's table are removed only by a
foreign key that table carries; Markets sends it no statement.

With portfolios (issue 91), the list goes on after the account: the portfolios' rows in
each registered dataset (`msm.portfolio_datasets`), then the portfolio rows. Each of
those statements keeps only the portfolios that no account history references once the
account's own history is gone.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, Uuid, bindparam, delete, func, literal, select, union
from sqlalchemy.orm import aliased

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    OrderManagerTable,
    PortfolioDatasetAvailabilityTable,
    PortfolioTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.portfolio_datasets import portfolio_dataset_tables
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import (
    AccountAllocationLinesStorage,
    VirtualFundHoldingsStorage,
)
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage

from .base import (
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

ACCOUNT_DELETE_GUARD = "account"
"""Guard label of the account statement: the account row, with the identifier read before."""

ACCOUNT_PORTFOLIOS_GUARD = "portfolios"
"""Guard label of the last statement when portfolios go too: each portfolio read as
deletable is deleted, or nothing is."""

ACCOUNT_DELETE_READ_MAX_ROWS = 10_000
"""Rows the read may return, one per portfolio the account names (MetaTables' maximum)."""


@dataclass(frozen=True)
class AccountDeleteTable:
    """One Markets table the account delete removes rows from, in delete order."""

    key: str
    model: type[Any]

    @property
    def table_name(self) -> str:
        return str(self.model.__table__.name)


ACCOUNT_DELETE_TABLES: tuple[AccountDeleteTable, ...] = (
    AccountDeleteTable("order_events", OrderEventsStorage),
    AccountDeleteTable("trades", TradesStorage),
    AccountDeleteTable("orders", OrdersStorage),
    AccountDeleteTable("order_managers", OrderManagerTable),
    AccountDeleteTable("allocation_lines", AccountAllocationLinesStorage),
    AccountDeleteTable("virtual_fund_holdings", VirtualFundHoldingsStorage),
    AccountDeleteTable("virtual_fund_holdings_sets", VirtualFundHoldingsSetTable),
    AccountDeleteTable("virtual_funds", VirtualFundTable),
    AccountDeleteTable("target_positions", TargetPositionsStorage),
    AccountDeleteTable("position_sets", PositionSetTable),
    AccountDeleteTable("target_allocations", AccountTargetAllocationTable),
    AccountDeleteTable("holdings", AccountHoldingsStorage),
    AccountDeleteTable("holdings_sets", AccountHoldingsSetTable),
    AccountDeleteTable("accounts", AccountTable),
)
"""Every Markets table the delete touches, in the order its statements run."""

ACCOUNT_HISTORY_KEYS = tuple(table.key for table in ACCOUNT_DELETE_TABLES if table.key != "accounts")
"""The account's history: every table above but the account's own."""

ACCOUNT_DELETE_BLOCKER_KEYS = (
    "other_account_orders",
    "other_account_virtual_fund_holdings_sets",
    "other_account_virtual_fund_holdings",
)
"""Markets rows of other accounts whose ``RESTRICT`` keys refuse the delete."""

ACCOUNT_HISTORY_REFERENCES: tuple[tuple[str, type[Any], str], ...] = (
    ("virtual_funds", VirtualFundTable, "target_portfolio_uid"),
    ("target_positions", TargetPositionsStorage, "portfolio_uid"),
)
"""Account history that references ``Portfolio.uid`` with ``RESTRICT``, by its key in
`ACCOUNT_DELETE_TABLES`. Only the account delete removes it (ADR 0049 decision 1)."""


def account_history_reference(model: type[Any], column: str) -> Any:
    """Whether a row of ``model`` names the portfolio row of the enclosing statement."""

    return (
        select(literal(1))
        .select_from(model)
        .where(getattr(model, column) == PortfolioTable.uid)
        .exists()
    )


@dataclass(frozen=True)
class _AccountScope:
    """The account's keys as bound parameters, and the selects the statements share.

    Without ``unique_identifier`` the identifier is read from the account row in the
    same statement, as the read does.
    """

    uid: uuid.UUID
    unique_identifier: str | None

    def account_uid(self) -> Any:
        return bindparam("account_uid", value=self.uid, type_=Uuid(as_uuid=True))

    def account_identifier(self) -> Any:
        if self.unique_identifier is None:
            return (
                select(AccountTable.unique_identifier)
                .where(AccountTable.uid == self.account_uid())
                .scalar_subquery()
            )
        return bindparam("account_identifier", value=self.unique_identifier, type_=String())

    def order_identifiers(self) -> Any:
        return select(OrdersStorage.order_identifier).where(
            OrdersStorage.account_identifier == self.account_identifier()
        )

    def other_order_identifiers(self) -> Any:
        return select(OrdersStorage.order_identifier).where(
            OrdersStorage.account_identifier != self.account_identifier()
        )

    def order_manager_identifiers(self) -> Any:
        return select(OrderManagerTable.unique_identifier).where(
            OrderManagerTable.target_account_uid == self.account_uid()
        )

    def virtual_fund_uids(self) -> Any:
        return select(VirtualFundTable.uid).where(VirtualFundTable.account_uid == self.account_uid())

    def target_allocation_uids(self) -> Any:
        return select(AccountTargetAllocationTable.uid).where(
            AccountTargetAllocationTable.account_uid == self.account_uid()
        )

    def position_set_uids(self) -> Any:
        return select(PositionSetTable.uid).where(
            PositionSetTable.account_target_allocation_uid.in_(self.target_allocation_uids())
        )

    def holdings_set_uids(self) -> Any:
        return select(AccountHoldingsSetTable.uid).where(
            AccountHoldingsSetTable.account_uid == self.account_uid()
        )


def _scope(uid: uuid.UUID | str, unique_identifier: str) -> _AccountScope:
    identifier = str(unique_identifier or "").strip()
    if not identifier:
        raise ValueError("Deleting an account requires its unique_identifier.")
    return _AccountScope(uid=uuid.UUID(str(uid)), unique_identifier=identifier)


def _row_filters(scope: _AccountScope) -> dict[str, Callable[[], Any]]:
    """The ``WHERE`` clause that selects the account's rows in each table."""

    return {
        # Order events have no foreign key: they name an order only by its identifier.
        # Events whose identifier another account's order also uses stay.
        "order_events": lambda: OrderEventsStorage.order_identifier.in_(scope.order_identifiers())
        & OrderEventsStorage.order_identifier.not_in(scope.other_order_identifiers()),
        "trades": lambda: TradesStorage.account_identifier == scope.account_identifier(),
        "orders": lambda: OrdersStorage.account_identifier == scope.account_identifier(),
        "order_managers": lambda: OrderManagerTable.target_account_uid == scope.account_uid(),
        "allocation_lines": lambda: AccountAllocationLinesStorage.account_uid
        == scope.account_uid(),
        "virtual_fund_holdings": lambda: VirtualFundHoldingsStorage.virtual_fund_uid.in_(
            scope.virtual_fund_uids()
        ),
        "virtual_fund_holdings_sets": lambda: VirtualFundHoldingsSetTable.virtual_fund_uid.in_(
            scope.virtual_fund_uids()
        ),
        "virtual_funds": lambda: VirtualFundTable.account_uid == scope.account_uid(),
        "target_positions": lambda: TargetPositionsStorage.position_set_uid.in_(
            scope.position_set_uids()
        ),
        "position_sets": lambda: PositionSetTable.account_target_allocation_uid.in_(
            scope.target_allocation_uids()
        ),
        "target_allocations": lambda: AccountTargetAllocationTable.account_uid == scope.account_uid(),
        "holdings": lambda: AccountHoldingsStorage.account_uid == scope.account_uid(),
        "holdings_sets": lambda: AccountHoldingsSetTable.account_uid == scope.account_uid(),
        "accounts": lambda: (AccountTable.uid == scope.account_uid())
        & (AccountTable.unique_identifier == scope.account_identifier()),
    }


def _blocker_filters(scope: _AccountScope) -> dict[str, tuple[type[Any], Callable[[], Any]]]:
    """Rows of other accounts that reference this account's rows with ``RESTRICT``."""

    other_virtual_funds = select(VirtualFundTable.uid).where(
        VirtualFundTable.account_uid != scope.account_uid()
    )
    return {
        "other_account_orders": (
            OrdersStorage,
            lambda: OrdersStorage.order_manager_identifier.in_(scope.order_manager_identifiers())
            & (OrdersStorage.account_identifier != scope.account_identifier()),
        ),
        "other_account_virtual_fund_holdings_sets": (
            VirtualFundHoldingsSetTable,
            lambda: VirtualFundHoldingsSetTable.source_account_holdings_set_uid.in_(
                scope.holdings_set_uids()
            )
            & VirtualFundHoldingsSetTable.virtual_fund_uid.in_(other_virtual_funds),
        ),
        "other_account_virtual_fund_holdings": (
            VirtualFundHoldingsStorage,
            lambda: VirtualFundHoldingsStorage.source_account_holdings_set_uid.in_(
                scope.holdings_set_uids()
            )
            & VirtualFundHoldingsStorage.virtual_fund_uid.in_(other_virtual_funds),
        ),
    }


# The delete ------------------------------------------------------------------------------


def _deletable_portfolios(portfolio_uids: Sequence[uuid.UUID]) -> Any:
    """The portfolios among ``portfolio_uids`` that no account history references."""

    condition = PortfolioTable.uid.in_(portfolio_uids)
    for _key, model, column in ACCOUNT_HISTORY_REFERENCES:
        condition = condition & ~account_history_reference(model, column)
    return condition


def _portfolio_statements(portfolio_uids: Sequence[uuid.UUID | str]) -> list[GuardedStatement | Any]:
    uids = sorted({uuid.UUID(str(uid)) for uid in portfolio_uids})
    identifiers = select(PortfolioTable.unique_identifier).where(_deletable_portfolios(uids))
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(table.model.portfolio_identifier.in_(identifiers))
        for table in portfolio_dataset_tables()
    ]
    statements.append(
        GuardedStatement(
            delete(PortfolioTable)
            .where(_deletable_portfolios(uids))
            .returning(PortfolioTable.uid, PortfolioTable.unique_identifier),
            expect_rows=len(uids),
            label=ACCOUNT_PORTFOLIOS_GUARD,
        )
    )
    return statements


def account_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    portfolio_uids: Sequence[uuid.UUID | str] = (),
) -> list[GuardedStatement | Any]:
    """The account delete as ordered statements for one transaction.

    Children go before the rows their ``RESTRICT`` keys reference: orders, trades and
    the events of those orders; order managers; virtual funds with their holdings;
    target allocations with their position sets and target rows; holdings sets with
    their rows; the account. The account statement is guarded: it must delete exactly
    the account read before, with the same ``unique_identifier``, or nothing is deleted.

    With ``portfolio_uids``, the rows of those portfolios in each registered dataset and
    then the portfolio rows follow, each statement limited to the portfolios no account
    history references any more. The last statement is guarded: it must delete every
    one of them, or nothing is deleted.
    """

    scope = _scope(uid, unique_identifier)
    filters = _row_filters(scope)
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(filters[table.key]())
        for table in ACCOUNT_DELETE_TABLES
        if table.key != "accounts"
    ]
    statements.append(
        GuardedStatement(
            delete(AccountTable)
            .where(filters["accounts"]())
            .returning(AccountTable.uid, AccountTable.unique_identifier),
            expect_rows=1,
            label=ACCOUNT_DELETE_GUARD,
        )
    )
    if portfolio_uids:
        statements.extend(_portfolio_statements(portfolio_uids))
    return statements


def build_delete_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    portfolio_uids: Sequence[uuid.UUID | str] = (),
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the account delete for the context's DataSource (ADR 0050)."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        account_delete_statements(
            uid=uid,
            unique_identifier=unique_identifier,
            portfolio_uids=portfolio_uids,
        ),
        context=with_max_rows(with_delete_deadline(context), max(len(portfolio_uids), 1)),
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    portfolio_uids: Sequence[uuid.UUID | str] = (),
) -> dict[str, Any]:
    """Delete the account, every Markets row that references it and the portfolios, or nothing.

    Answers with the deleted portfolio rows when ``portfolio_uids`` is given, else with
    the deleted account row; with no rows when the account no longer exists under
    ``unique_identifier``. When one of the portfolios is referenced again in between,
    the portfolios' guard raises `metatables.MetaTableTransactionGuardError` labelled
    `ACCOUNT_PORTFOLIOS_GUARD`. A foreign key that refuses the delete raises the
    MetaTables error. Either way nothing is deleted.
    """

    return execute_markets_write(
        build_delete_account_operation(
            context,
            uid=uid,
            unique_identifier=unique_identifier,
            portfolio_uids=portfolio_uids,
        ),
        context=context,
        refused_by=(ACCOUNT_DELETE_GUARD,),
    )


# The read --------------------------------------------------------------------------------


def _portfolio_label(name: str) -> str:
    # Keys such as ``values`` and ``state`` are SQL keywords; the labels never are.
    return f"portfolio_{name}"


def build_read_account_delete_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    with_portfolios: bool = False,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """One read: the account, the rows its delete removes, and the rows that block it.

    The counts of the account's rows are subqueries on the bound account uid alone, so
    the database runs each once whatever the number of result rows. With
    ``with_portfolios`` there is one row per portfolio the account's virtual funds or
    target rows name, with the account history of other accounts that references it,
    its catalog row's instance uids and its rows in each registered dataset. No row
    means no account.
    """

    scope = _AccountScope(uid=uuid.UUID(str(uid)), unique_identifier=None)
    account = aliased(AccountTable, name="deleted_account")
    filters = _row_filters(scope)
    context = with_delete_deadline(context)
    statement = select(
        account.uid.label("uid"),
        account.unique_identifier.label("unique_identifier"),
        *(
            select(func.count())
            .select_from(table.model)
            .where(filters[table.key]())
            .scalar_subquery()
            .label(table.key)
            for table in ACCOUNT_DELETE_TABLES
            if table.key != "accounts"
        ),
        *(
            select(func.count()).select_from(model).where(where()).scalar_subquery().label(key)
            for key, (model, where) in _blocker_filters(scope).items()
        ),
    ).select_from(account)
    if with_portfolios:
        datasets = portfolio_dataset_tables()
        named = union(
            *(
                select(getattr(model, column).label("portfolio_uid")).where(filters[key]())
                for key, model, column in ACCOUNT_HISTORY_REFERENCES
            )
        )
        statement = (
            statement.add_columns(
                PortfolioTable.uid.label(_portfolio_label("uid")),
                PortfolioTable.unique_identifier.label(_portfolio_label("identifier")),
                # Account history of other accounts: it stays when this account goes.
                *(
                    select(func.count())
                    .select_from(model)
                    .where((getattr(model, column) == PortfolioTable.uid) & ~filters[key]())
                    .scalar_subquery()
                    .label(_portfolio_label(key))
                    for key, model, column in ACCOUNT_HISTORY_REFERENCES
                ),
                *(
                    getattr(PortfolioDatasetAvailabilityTable, table.catalog_column).label(
                        table.catalog_column
                    )
                    for table in datasets
                    if table.catalog_column
                ),
                *(
                    select(func.count())
                    .select_from(table.model)
                    .where(table.model.portfolio_identifier == PortfolioTable.unique_identifier)
                    .scalar_subquery()
                    .label(_portfolio_label(f"{table.key}_rows"))
                    for table in datasets
                ),
            )
            .outerjoin(PortfolioTable, PortfolioTable.uid.in_(named))
            .outerjoin(
                PortfolioDatasetAvailabilityTable,
                PortfolioDatasetAvailabilityTable.portfolio_uid == PortfolioTable.uid,
            )
        )
        context = with_max_rows(context, ACCOUNT_DELETE_READ_MAX_ROWS)
    return compile_markets_statement(
        statement.where(account.uid == scope.account_uid()),
        context=context,
        operation="select",
        dialect=dialect,
    )


def read_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    with_portfolios: bool = False,
) -> dict[str, Any] | None:
    """What deleting the account removes and what blocks it, in one read.

    Answers ``None`` when the account does not exist. Otherwise: its ``uid`` and
    ``unique_identifier``; ``counts``, per key of `ACCOUNT_HISTORY_KEYS` and
    `ACCOUNT_DELETE_BLOCKER_KEYS`; and ``portfolios``, empty unless
    ``with_portfolios``: per portfolio the account history of other accounts that
    references it (``references``, by key of `ACCOUNT_HISTORY_REFERENCES`), its
    ``catalog`` instance uids and its ``row_counts`` per registered dataset.
    """

    result = execute_markets_operation(
        build_read_account_delete_operation(context, uid=uid, with_portfolios=with_portfolios),
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
    first = rows[0]
    read: dict[str, Any] = {
        "uid": str(uuid.UUID(str(first["uid"]))),
        "unique_identifier": str(first.get("unique_identifier") or ""),
        "counts": {
            key: int(first.get(key) or 0)
            for key in (*ACCOUNT_HISTORY_KEYS, *ACCOUNT_DELETE_BLOCKER_KEYS)
        },
        "portfolios": [],
    }
    if not with_portfolios:
        return read
    datasets = portfolio_dataset_tables()
    for row in rows:
        if row.get(_portfolio_label("uid")) is None:
            continue
        read["portfolios"].append(
            {
                "uid": str(uuid.UUID(str(row[_portfolio_label("uid")]))),
                "unique_identifier": str(row.get(_portfolio_label("identifier")) or ""),
                "references": {
                    key: int(row.get(_portfolio_label(key)) or 0)
                    for key, _model, _column in ACCOUNT_HISTORY_REFERENCES
                },
                "catalog": {
                    table.catalog_column: _string_or_none(row.get(table.catalog_column))
                    for table in datasets
                    if table.catalog_column
                },
                "row_counts": {
                    table.key: int(row.get(_portfolio_label(f"{table.key}_rows")) or 0)
                    for table in datasets
                },
            }
        )
    read["portfolios"].sort(key=lambda portfolio: (portfolio["unique_identifier"], portfolio["uid"]))
    return read


def _string_or_none(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


__all__ = [
    "ACCOUNT_DELETE_BLOCKER_KEYS",
    "ACCOUNT_DELETE_GUARD",
    "ACCOUNT_DELETE_READ_MAX_ROWS",
    "ACCOUNT_DELETE_TABLES",
    "ACCOUNT_HISTORY_KEYS",
    "ACCOUNT_HISTORY_REFERENCES",
    "ACCOUNT_PORTFOLIOS_GUARD",
    "AccountDeleteTable",
    "account_delete_statements",
    "account_history_reference",
    "build_delete_account_operation",
    "build_read_account_delete_operation",
    "delete_account",
    "read_account_delete",
]
