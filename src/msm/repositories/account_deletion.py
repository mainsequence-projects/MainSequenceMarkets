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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, literal, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    OrderManagerTable,
    OrderTable,
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
    with_max_rows,
)

ACCOUNT_DELETE_GUARD = "account"
"""Guard label of the accounts' statement: every account row, with the identifier read before."""


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
    AccountDeleteTable("order_states", OrdersStorage),
    AccountDeleteTable("orders", OrderTable),
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
    """The accounts whose rows the statements select, and the selects they share.

    ``uids`` are the accounts deleted (or read). Without ``unique_identifiers`` their
    identifiers are read from their rows in the same statement, as the read does.
    ``together`` are further accounts deleted in the same transaction: rows of theirs are
    not "another account's" (issue 128).
    """

    uids: tuple[uuid.UUID, ...]
    unique_identifiers: tuple[str, ...] | None
    together: tuple[uuid.UUID, ...] = ()

    def uid_in(self, column: Any) -> Any:
        return column.in_(list(self.uids))

    def identifiers(self) -> Any:
        if self.unique_identifiers is None:
            return select(AccountTable.unique_identifier).where(self.uid_in(AccountTable.uid))
        return list(self.unique_identifiers)

    def identifier_in(self, column: Any) -> Any:
        return column.in_(self.identifiers())

    def _deleted_uids(self) -> list[uuid.UUID]:
        return list(dict.fromkeys((*self.uids, *self.together)))

    def of_another_account_uid(self, column: Any) -> Any:
        """Whether ``column``, an account uid, names an account not deleted here."""

        return ~column.in_(self._deleted_uids())

    def of_another_account_identifier(self, column: Any) -> Any:
        """Whether ``column``, an account identifier, names an account not deleted here."""

        if self.together:
            deleted = select(AccountTable.unique_identifier).where(
                AccountTable.uid.in_(self._deleted_uids())
            )
            return ~column.in_(deleted)
        return ~self.identifier_in(column)

    def order_uids(self) -> Any:
        return select(OrderTable.uid).where(self.identifier_in(OrderTable.account_identifier))

    def order_manager_identifiers(self) -> Any:
        return select(OrderManagerTable.unique_identifier).where(
            self.uid_in(OrderManagerTable.target_account_uid)
        )

    def virtual_fund_uids(self) -> Any:
        return select(VirtualFundTable.uid).where(self.uid_in(VirtualFundTable.account_uid))

    def target_allocation_uids(self) -> Any:
        return select(AccountTargetAllocationTable.uid).where(
            self.uid_in(AccountTargetAllocationTable.account_uid)
        )

    def position_set_uids(self) -> Any:
        return select(PositionSetTable.uid).where(
            PositionSetTable.account_target_allocation_uid.in_(self.target_allocation_uids())
        )

    def holdings_set_uids(self) -> Any:
        return select(AccountHoldingsSetTable.uid).where(
            self.uid_in(AccountHoldingsSetTable.account_uid)
        )


def _scope(accounts: Sequence[tuple[uuid.UUID | str, str]]) -> _AccountScope:
    pairs: dict[uuid.UUID, str] = {}
    for uid, unique_identifier in accounts:
        identifier = str(unique_identifier or "").strip()
        if not identifier:
            raise ValueError("Deleting an account requires its unique_identifier.")
        pairs[uuid.UUID(str(uid))] = identifier
    if not pairs:
        raise ValueError("Deleting accounts requires at least one account.")
    return _AccountScope(uids=tuple(pairs), unique_identifiers=tuple(pairs.values()))


def _uids(uids: uuid.UUID | str | Sequence[uuid.UUID | str]) -> tuple[uuid.UUID, ...]:
    if isinstance(uids, (str, uuid.UUID)):
        uids = [uids]
    return tuple(dict.fromkeys(uuid.UUID(str(uid)) for uid in uids))


def _row_filters(scope: _AccountScope) -> dict[str, Callable[[], Any]]:
    """The ``WHERE`` clause that selects the accounts' rows in each table."""

    return {
        # An order's state rows and events name it by its uid, unique across accounts
        # (ADR 0064); its trades carry its account.
        "order_events": lambda: OrderEventsStorage.order_uid.in_(scope.order_uids()),
        "trades": lambda: scope.identifier_in(TradesStorage.account_identifier),
        "order_states": lambda: OrdersStorage.order_uid.in_(scope.order_uids()),
        "orders": lambda: scope.identifier_in(OrderTable.account_identifier),
        "order_managers": lambda: scope.uid_in(OrderManagerTable.target_account_uid),
        "allocation_lines": lambda: scope.uid_in(AccountAllocationLinesStorage.account_uid),
        "virtual_fund_holdings": lambda: VirtualFundHoldingsStorage.virtual_fund_uid.in_(
            scope.virtual_fund_uids()
        ),
        "virtual_fund_holdings_sets": lambda: VirtualFundHoldingsSetTable.virtual_fund_uid.in_(
            scope.virtual_fund_uids()
        ),
        "virtual_funds": lambda: scope.uid_in(VirtualFundTable.account_uid),
        "target_positions": lambda: TargetPositionsStorage.position_set_uid.in_(
            scope.position_set_uids()
        ),
        "position_sets": lambda: PositionSetTable.account_target_allocation_uid.in_(
            scope.target_allocation_uids()
        ),
        "target_allocations": lambda: scope.uid_in(AccountTargetAllocationTable.account_uid),
        "holdings": lambda: scope.uid_in(AccountHoldingsStorage.account_uid),
        "holdings_sets": lambda: scope.uid_in(AccountHoldingsSetTable.account_uid),
        "accounts": lambda: scope.uid_in(AccountTable.uid)
        & scope.identifier_in(AccountTable.unique_identifier),
    }


def _blocker_filters(scope: _AccountScope) -> dict[str, tuple[type[Any], Callable[[], Any]]]:
    """Rows of accounts not deleted here that reference the accounts' rows with ``RESTRICT``."""

    other_virtual_funds = select(VirtualFundTable.uid).where(
        scope.of_another_account_uid(VirtualFundTable.account_uid)
    )
    return {
        "other_account_orders": (
            OrderTable,
            lambda: OrderTable.order_manager_identifier.in_(scope.order_manager_identifiers())
            & scope.of_another_account_identifier(OrderTable.account_identifier),
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


def account_history_filters(
    uids: uuid.UUID | str | Sequence[uuid.UUID | str],
) -> dict[str, Callable[[], Any]]:
    """The ``WHERE`` clause that selects the accounts' rows in each table, by table key.

    The accounts' identifiers are read from their rows in the same statement, so the
    filters serve a read that knows only the uids.
    """

    return _row_filters(_AccountScope(uids=_uids(uids), unique_identifiers=None))


# The delete ------------------------------------------------------------------------------


def accounts_delete_statements(
    *,
    accounts: Sequence[tuple[uuid.UUID | str, str]],
    row_counts: Mapping[str, int],
) -> list[GuardedStatement | Any]:
    """The delete of ``accounts``, ``(uid, unique_identifier)`` pairs, for one transaction.

    Children go before the rows their ``RESTRICT`` keys reference: the events, trades and
    state rows of the accounts' orders, then the orders; order managers; virtual funds with their holdings;
    target allocations with their position sets and target rows; holdings sets with
    their rows; the accounts. Each statement covers every account. The accounts'
    statement is guarded: it must delete exactly the accounts read before, each with its
    ``unique_identifier``, or nothing is deleted. MetaTables checks a guard after each
    statement, so statements may follow it.

    ``row_counts`` are the reads' counts by table key (`ACCOUNT_HISTORY_KEYS`), summed
    over the accounts. A table the reads found empty gets no statement, so the
    transaction neither reads nor locks it. A row written there after the read is still
    handled by its foreign key: a ``CASCADE`` key deletes it with its parent, and a
    ``RESTRICT`` key refuses the transaction, which then deletes nothing.
    """

    scope = _scope(accounts)
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
            expect_rows=len(scope.uids),
            label=ACCOUNT_DELETE_GUARD,
        )
    )
    return statements


def account_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
) -> list[GuardedStatement | Any]:
    """One account's delete as ordered statements for one transaction."""

    return accounts_delete_statements(accounts=[(uid, unique_identifier)], row_counts=row_counts)


def _has_rows(key: str, row_counts: Mapping[str, int]) -> bool:
    return row_counts[key] > 0


def build_delete_accounts_operation(
    context: MarketsRepositoryContext,
    *,
    accounts: Sequence[tuple[uuid.UUID | str, str]],
    row_counts: Mapping[str, int],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the delete of ``accounts`` for the context's DataSource (ADR 0050)."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        accounts_delete_statements(accounts=accounts, row_counts=row_counts),
        context=with_max_rows(with_delete_deadline(context), max(len(accounts), 1)),
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def build_delete_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile one account's delete for the context's DataSource (ADR 0050)."""

    return build_delete_accounts_operation(
        context, accounts=[(uid, unique_identifier)], row_counts=row_counts, dialect=dialect
    )


def delete_accounts(
    context: MarketsRepositoryContext,
    *,
    accounts: Sequence[tuple[uuid.UUID | str, str]],
    row_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Delete ``accounts`` and every Markets row that references them, all or nothing.

    ``row_counts`` are the reads' counts, summed. Answers with the deleted account rows,
    or with no rows when an account no longer exists under its ``unique_identifier``. A
    foreign key that refuses the delete raises the MetaTables error. Either way nothing
    is deleted.
    """

    return execute_markets_write(
        build_delete_accounts_operation(context, accounts=accounts, row_counts=row_counts),
        context=context,
        refused_by=(ACCOUNT_DELETE_GUARD,),
    )


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    row_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Delete one account and every Markets row that references it, or nothing."""

    return delete_accounts(context, accounts=[(uid, unique_identifier)], row_counts=row_counts)


# The read --------------------------------------------------------------------------------


def account_delete_read_statement(
    uid: uuid.UUID | str,
    *,
    together: Sequence[uuid.UUID | str] = (),
) -> Select:
    """The account delete's read: the account, the rows its delete removes, and the rows
    of other accounts that block it, labelled by the keys of `ACCOUNT_HISTORY_KEYS` and
    `ACCOUNT_DELETE_BLOCKER_KEYS`.

    Each count is a subquery on the bound account uid alone (the identifier is read in
    the same statement), so the database runs each once, whatever columns and joins a
    caller adds. No row means no account. ``together`` are accounts deleted in the same
    transaction: their rows block nothing (issue 128).
    """

    account = aliased(AccountTable, name="deleted_account")
    filters = account_history_filters(uid)
    scope = _AccountScope(uids=_uids(uid), unique_identifiers=None, together=_uids(together))
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
        .where(scope.uid_in(account.uid))
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
    together: Sequence[uuid.UUID | str] = (),
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """Compile the account delete's read, run with the delete's deadline."""

    return compile_markets_statement(
        account_delete_read_statement(uid, together=together),
        context=with_delete_deadline(context),
        operation="select",
        dialect=dialect,
    )


def read_account_delete(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    together: Sequence[uuid.UUID | str] = (),
) -> dict[str, Any] | None:
    """What deleting the account removes and what blocks it, in one read.

    ``together`` are accounts deleted in the same transaction. Answers ``None`` when the
    account does not exist, else `account_delete_read_row`.
    """

    result = execute_markets_operation(
        build_read_account_delete_operation(context, uid=uid, together=together),
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
    "accounts_delete_statements",
    "account_history_reference",
    "build_delete_account_operation",
    "build_delete_accounts_operation",
    "build_read_account_delete_operation",
    "delete_account",
    "delete_accounts",
    "read_account_delete",
]
