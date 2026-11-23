"""Order managers, orders and execution rows (ADR 0064)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.base import new_markets_uid
from msm.models import OrderManagerTable, OrderTable

from .base import (
    MarketsRepositoryContext,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    with_max_rows,
)
from .crud import (
    MAX_STATEMENT_PARAMETERS,
    MAX_STATEMENT_ROWS,
    build_create_model_operation,
    build_delete_model_operation,
    build_search_model_operation,
    build_update_model_operation,
)

ORDER_MANAGER_GUARD = "order_manager"
"""Guard label of the batch's statement: the order manager row, upserted."""


def build_create_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    target_account_uid: uuid.UUID | str,
    target_time: dt.datetime,
    order_received_time: dt.datetime | None = None,
    execution_end: dt.datetime | None = None,
    status: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=OrderManagerTable,
        values={
            "unique_identifier": unique_identifier,
            "target_account_uid": target_account_uid,
            "target_time": target_time,
            "order_received_time": order_received_time,
            "execution_end": execution_end,
            "status": status,
            "metadata_json": metadata_json,
        },
    )


def build_search_order_managers_operation(
    context: MarketsRepositoryContext,
    *,
    target_account_uid: uuid.UUID | str | None = None,
    status: str | None = None,
    unique_identifier_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if target_account_uid is not None:
        filters["target_account_uid"] = target_account_uid
    if status not in (None, ""):
        filters["status"] = status
    return build_search_model_operation(
        context,
        model=OrderManagerTable,
        filters=filters,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
        limit=limit,
    )


def build_update_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(context, model=OrderManagerTable, uid=uid, values=values)


def build_delete_order_manager_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=OrderManagerTable, uid=uid)


def execute_execution_operation(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_markets_operation(operation, context=context)


# Execution rows ---------------------------------------------------------------------------


def execution_rows_per_statement(table: type[Any]) -> int:
    """Rows of ``table`` one upsert statement holds within MetaTables' limits."""

    columns = len(table.__table__.columns)
    return max(1, min(MAX_STATEMENT_ROWS, MAX_STATEMENT_PARAMETERS // columns))


def upsert_rows_statements(
    table: type[Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    dialect: MetaTableCompiledSQLDialect,
    conflict_columns: Sequence[str] | None = None,
) -> list[Any]:
    """Upserts of ``rows`` on ``conflict_columns`` (the table's index names by default),
    each statement within MetaTables' limits. Every row carries every column."""

    keys = list(conflict_columns or table.__index_names__)
    columns = [column.name for column in table.__table__.columns]
    insert = sqlite_insert if dialect == "sqlite" else postgresql_insert
    per_statement = execution_rows_per_statement(table)
    statements: list[Any] = []
    for start in range(0, len(rows), per_statement):
        statement = insert(table).values(
            [{name: row.get(name) for name in columns} for row in rows[start : start + per_statement]]
        )
        statements.append(
            statement.on_conflict_do_update(
                index_elements=[table.__table__.c[name] for name in keys],
                set_={
                    name: statement.excluded[name] for name in columns if name not in keys
                },
            )
        )
    return statements


def write_execution_rows(
    context: MarketsRepositoryContext,
    tables: Sequence[tuple[type[Any], Sequence[Mapping[str, Any]]]],
) -> dict[str, Any]:
    """Upsert each table's rows, in the order given, in one transaction (MetaTables ADR 0026)."""

    data_source_uid, dialect = resolve_markets_sql_target(context)
    statements = [
        statement
        for table, rows in tables
        if rows
        for statement in upsert_rows_statements(table, rows, dialect=dialect)
    ]
    return execute_markets_write(
        compile_markets_statements(
            statements,
            context=context,
            operation="upsert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        ),
        context=context,
    )


# A batch with its orders ---------------------------------------------------------------


def write_order_batch(
    context: MarketsRepositoryContext,
    *,
    order_manager: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Upsert the order manager and insert its orders, in one transaction.

    The order manager is upserted on ``unique_identifier`` and returned. An order is
    written once (ADR 0064): one that exists already is left as it is, so a batch sent
    again writes nothing twice. Answers the order manager row.
    """

    data_source_uid, dialect = resolve_markets_sql_target(context)
    insert = sqlite_insert if dialect == "sqlite" else postgresql_insert
    # A new batch's uid; an existing batch keeps its own, which the upsert never updates.
    order_manager = {"uid": new_markets_uid(), **order_manager}
    manager_columns = [
        name
        for name in (
            "uid",
            "unique_identifier",
            "target_account_uid",
            "target_time",
            "order_received_time",
            "execution_end",
            "status",
            "metadata_json",
        )
        if name in order_manager
    ]
    manager_insert = insert(OrderManagerTable).values(
        {name: order_manager[name] for name in manager_columns}
    )
    manager_upsert = manager_insert.on_conflict_do_update(
        index_elements=[OrderManagerTable.__table__.c.unique_identifier],
        set_={
            name: manager_insert.excluded[name]
            for name in manager_columns
            if name not in ("uid", "unique_identifier")
        },
    ).returning(*OrderManagerTable.__table__.columns)
    order_columns = [column.name for column in OrderTable.__table__.columns]
    per_statement = execution_rows_per_statement(OrderTable)
    order_inserts = []
    for start in range(0, len(orders), per_statement):
        statement = insert(OrderTable).values(
            [
                {name: order.get(name) for name in order_columns}
                for order in orders[start : start + per_statement]
            ]
        )
        order_inserts.append(
            statement.on_conflict_do_nothing(index_elements=[OrderTable.__table__.c.uid])
        )
    # The batch's row comes last: a transaction answers its last statement's rows.
    statements: list[Any] = [
        *order_inserts,
        GuardedStatement(manager_upsert, expect_rows=1, label=ORDER_MANAGER_GUARD),
    ]
    if order_inserts:
        # Orders name their batch, so the batch is written first, then again to answer it.
        statements.insert(0, _manager_upsert_without_rows(insert, order_manager, manager_columns))
    return execute_markets_write(
        compile_markets_statements(
            statements,
            context=with_max_rows(context, 1),
            operation="upsert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        ),
        context=context,
    )


def _manager_upsert_without_rows(
    insert: Any, order_manager: Mapping[str, Any], manager_columns: Sequence[str]
) -> Any:
    statement = insert(OrderManagerTable).values(
        {name: order_manager[name] for name in manager_columns}
    )
    return statement.on_conflict_do_update(
        index_elements=[OrderManagerTable.__table__.c.unique_identifier],
        set_={
            name: statement.excluded[name]
            for name in manager_columns
            if name not in ("uid", "unique_identifier")
        },
    )


__all__ = [
    "ORDER_MANAGER_GUARD",
    "build_create_order_manager_operation",
    "build_delete_order_manager_operation",
    "build_search_order_managers_operation",
    "build_update_order_manager_operation",
    "execute_execution_operation",
    "execution_rows_per_statement",
    "upsert_rows_statements",
    "write_execution_rows",
    "write_order_batch",
]
