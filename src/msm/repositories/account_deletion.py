"""Delete an account with its whole history (ADR 0050).

The delete is an ordered statement list that MetaTables runs in one transaction on
PostgreSQL and on SQLite (MetaTables ADR 0026). Every statement targets a table in
the Markets namespace. Rows in another application's table are removed only by a
foreign key that table carries; Markets sends it no statement.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, Uuid, bindparam, delete, func, select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    OrderManagerTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage

from .base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
)

ACCOUNT_DELETE_GUARD = "account"
"""Guard label of the last statement: the account row, with the identifier read before."""


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

ACCOUNT_DELETE_BLOCKER_KEYS = (
    "other_account_orders",
    "other_account_virtual_fund_holdings_sets",
    "other_account_virtual_fund_holdings",
)
"""Markets rows of other accounts whose ``RESTRICT`` keys refuse the delete."""


@dataclass(frozen=True)
class _AccountScope:
    """The account's keys as bound parameters, and the selects the statements share."""

    uid: uuid.UUID
    unique_identifier: str

    def account_uid(self) -> Any:
        return bindparam("account_uid", value=self.uid, type_=Uuid(as_uuid=True))

    def account_identifier(self) -> Any:
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


def account_delete_statements(
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> list[GuardedStatement | Any]:
    """The account delete as ordered statements for one transaction.

    Children go before the rows their ``RESTRICT`` keys reference: orders, trades and
    the events of those orders; order managers; virtual funds with their holdings;
    target allocations with their position sets and target rows; holdings sets with
    their rows; the account. The last statement is guarded: it must delete exactly the
    account read before, with the same ``unique_identifier``, or nothing is deleted.
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
    return statements


def build_delete_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the account delete for the context's DataSource (ADR 0050)."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        account_delete_statements(uid=uid, unique_identifier=unique_identifier),
        context=context,
        operation="delete",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> dict[str, Any]:
    """Delete the account and every Markets row that references it, or nothing.

    Answers with the deleted account row, or with no rows when the account no longer
    exists under ``unique_identifier``. A foreign key that refuses the delete raises
    the MetaTables error, and nothing is deleted.
    """

    return execute_markets_write(
        build_delete_account_operation(context, uid=uid, unique_identifier=unique_identifier),
        context=context,
        refused_by=(ACCOUNT_DELETE_GUARD,),
    )


def build_count_account_delete_rows_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """One read that counts the rows the delete would remove, and the rows that block it."""

    scope = _scope(uid, unique_identifier)
    filters = _row_filters(scope)
    counts = [
        select(func.count())
        .select_from(table.model)
        .where(filters[table.key]())
        .scalar_subquery()
        .label(table.key)
        for table in ACCOUNT_DELETE_TABLES
    ]
    counts.extend(
        select(func.count()).select_from(model).where(where()).scalar_subquery().label(key)
        for key, (model, where) in _blocker_filters(scope).items()
    )
    return compile_markets_statement(
        select(*counts),
        context=context,
        operation="select",
        dialect=dialect,
    )


def count_account_delete_rows(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    unique_identifier: str,
) -> dict[str, int]:
    """Rows per table the delete would remove, and per blocker key the rows that block it."""

    result = execute_markets_operation(
        build_count_account_delete_rows_operation(
            context,
            uid=uid,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )
    rows = result.get("rows") or []
    row = rows[0] if rows else {}
    keys = [table.key for table in ACCOUNT_DELETE_TABLES] + list(ACCOUNT_DELETE_BLOCKER_KEYS)
    return {key: int(row.get(key) or 0) for key in keys}


__all__ = [
    "ACCOUNT_DELETE_BLOCKER_KEYS",
    "ACCOUNT_DELETE_GUARD",
    "ACCOUNT_DELETE_TABLES",
    "AccountDeleteTable",
    "account_delete_statements",
    "build_count_account_delete_rows_operation",
    "build_delete_account_operation",
    "count_account_delete_rows",
    "delete_account",
]
