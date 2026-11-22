"""Delete an account with its whole history (ADR 0050).

The delete is an ordered statement list that MetaTables runs in one transaction on
PostgreSQL and on SQLite (MetaTables ADR 0026). Every statement targets a table in
the Markets namespace. Rows in another application's table are removed only by a
foreign key that table carries; Markets sends it no statement.

The statements and the read are public so that the delete of an account with the
portfolios only it used, which the portfolio package owns, can extend them into the
same single read and single transaction (issue 91).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, Uuid, bindparam, delete, func, literal, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    OrderManagerTable,
    PortfolioTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
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
)

ACCOUNT_DELETE_GUARD = "account"
"""Guard label of the account statement: the account row, with the identifier read before."""


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

    def ordered_by_another_account(self, order_identifier: Any) -> Any:
        """Whether an order of another account has ``order_identifier``: one index probe."""

        other = aliased(OrdersStorage, name="other_account_order")
        return (
            select(literal(1))
            .select_from(other)
            .where(other.order_identifier == order_identifier)
            .where(other.account_identifier != self.account_identifier())
            .exists()
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
        & ~scope.ordered_by_another_account(OrderEventsStorage.order_identifier),
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


def account_history_filters(uid: uuid.UUID | str) -> dict[str, Callable[[], Any]]:
    """The ``WHERE`` clause that selects the account's rows in each table, by table key.

    The account's identifier is read from its row in the same statement, so the filters
    serve a read that knows only the uid.
    """

    return _row_filters(_AccountScope(uid=uuid.UUID(str(uid)), unique_identifier=None))


# The delete ------------------------------------------------------------------------------


def account_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
) -> list[GuardedStatement | Any]:
    """The account delete as ordered statements for one transaction.

    Children go before the rows their ``RESTRICT`` keys reference: orders, trades and
    the events of those orders; order managers; virtual funds with their holdings;
    target allocations with their position sets and target rows; holdings sets with
    their rows; the account. The account statement is guarded: it must delete exactly
    the account read before, with the same ``unique_identifier``, or nothing is deleted.
    MetaTables checks a guard after each statement, so statements may follow it.

    ``row_counts`` are the read's counts by table key (`ACCOUNT_HISTORY_KEYS`). A table
    the read found empty gets no statement, so the transaction neither reads nor locks
    it. A row written there after the read is still handled by its foreign key: a
    ``CASCADE`` key deletes it with its parent, and a ``RESTRICT`` key refuses the
    transaction, which then deletes nothing. Order events have no key, so their
    statement runs whenever the account has orders.
    """

    scope = _scope(uid, unique_identifier)
    filters = _row_filters(scope)
    statements: list[GuardedStatement | Any] = [
        delete(table.model).where(filters[table.key]())
        for table in ACCOUNT_DELETE_TABLES
        if table.key != "accounts" and _has_rows(table.key, row_counts)
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
    return statements


def _has_rows(key: str, row_counts: Mapping[str, int]) -> bool:
    if key == "order_events":
        return row_counts["order_events"] > 0 or row_counts["orders"] > 0
    return row_counts[key] > 0


def build_delete_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the account delete for the context's DataSource (ADR 0050)."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        account_delete_statements(
            uid=uid, unique_identifier=unique_identifier, row_counts=row_counts
        ),
        context=with_delete_deadline(context),
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Delete the account and every Markets row that references it, or nothing.

    ``row_counts`` are `read_account_delete`'s counts. Answers with the deleted account
    row, or with no rows when the account no longer exists under ``unique_identifier``.
    A foreign key that refuses the delete raises the MetaTables error, and nothing is
    deleted.
    """

    return execute_markets_write(
        build_delete_account_operation(
            context, uid=uid, unique_identifier=unique_identifier, row_counts=row_counts
        ),
        context=context,
        refused_by=(ACCOUNT_DELETE_GUARD,),
    )


# The read --------------------------------------------------------------------------------


def account_delete_read_statement(uid: uuid.UUID | str) -> Select:
    """The account delete's read: the account, the rows its delete removes, and the rows
    of other accounts that block it, labelled by the keys of `ACCOUNT_HISTORY_KEYS` and
    `ACCOUNT_DELETE_BLOCKER_KEYS`.

    Each count is a subquery on the bound account uid alone (the identifier is read in
    the same statement), so the database runs each once, whatever columns and joins a
    caller adds. No row means no account.
    """

    account = aliased(AccountTable, name="deleted_account")
    filters = account_history_filters(uid)
    scope = _AccountScope(uid=uuid.UUID(str(uid)), unique_identifier=None)
    return (
        select(
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
        )
        .select_from(account)
        .where(account.uid == scope.account_uid())
    )


def account_delete_read_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The account's ``uid``, ``unique_identifier`` and ``counts`` from a read row."""

    return {
        "uid": str(uuid.UUID(str(row["uid"]))),
        "unique_identifier": str(row.get("unique_identifier") or ""),
        "counts": {
            key: int(row.get(key) or 0) for key in (*ACCOUNT_HISTORY_KEYS, *ACCOUNT_DELETE_BLOCKER_KEYS)
        },
    }


def build_read_account_delete_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """Compile the account delete's read, run with the delete's deadline."""

    return compile_markets_statement(
        account_delete_read_statement(uid),
        context=with_delete_deadline(context),
        operation="select",
        dialect=dialect,
    )


def read_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any] | None:
    """What deleting the account removes and what blocks it, in one read.

    Answers ``None`` when the account does not exist, else `account_delete_read_row`.
    """

    result = execute_markets_operation(
        build_read_account_delete_operation(context, uid=uid),
        context=context,
    )
    rows = result.get("rows") or []
    return account_delete_read_row(rows[0]) if rows else None


__all__ = [
    "ACCOUNT_DELETE_BLOCKER_KEYS",
    "ACCOUNT_DELETE_GUARD",
    "ACCOUNT_DELETE_TABLES",
    "ACCOUNT_HISTORY_KEYS",
    "ACCOUNT_HISTORY_REFERENCES",
    "AccountDeleteTable",
    "account_delete_read_row",
    "account_delete_read_statement",
    "account_delete_statements",
    "account_history_filters",
    "account_history_reference",
    "build_delete_account_operation",
    "build_read_account_delete_operation",
    "delete_account",
    "read_account_delete",
]
