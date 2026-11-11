from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metatables import (
    MetaTable,
    MetaTableCompiledSQLDialect,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableOperation,
    MetaTableOperationLimits,
    MetaTableTransactionGuardError,
)
from metatables.compiled_sql.v1 import (
    GuardedStatement,
    compile_sqlalchemy_statement,
    compile_sqlalchemy_statements,
)
from metatables.models import MetaTableWriteOperation
from metatables.runtime_contract import DataSourceResolutionError

from msm.base import MarketsBase


@dataclass(frozen=True)
class MarketsMetaTableHandle:
    """Execution handle for one registered markets MetaTable model."""

    model: type[MarketsBase]
    meta_table: MetaTable | None = None
    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    data_source_uid: str | None = None
    timeout: int | float | tuple[float, float] | None = None
    namespace: str | None = None

    @property
    def meta_table_uid(self) -> str:
        return _bound_meta_table_uid(self.model, meta_table=self.meta_table)


@dataclass(frozen=True, init=False)
class MarketsRepositoryContext:
    """MetaTable execution context for markets repositories.

    `namespace` records the runtime namespace override selected during
    bootstrap. `None` means the library's normal MetaTable namespace was used.
    `data_source_uid` is normally `None`, which lets the compiler take the
    DataSource and dialect from the MetaTables API runtime. An explicit UID must
    match that runtime unless a dialect is also supplied.
    """

    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    data_source_uid: str | None = None
    timeout: int | float | tuple[float, float] | None = None
    namespace: str | None = None

    def __init__(
        self,
        limits: MetaTableOperationLimits | Mapping[str, Any] | None = None,
        data_source_uid: str | None = None,
        timeout: int | float | tuple[float, float] | None = None,
        namespace: str | None = None,
    ) -> None:
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "data_source_uid", data_source_uid)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "namespace", namespace)

    def meta_table_uid_for_model(self, model: type[MarketsBase]) -> str:
        return _bound_meta_table_uid(model)

    def table(self, model: type[MarketsBase] | str) -> MarketsMetaTableHandle:
        from msm.models.registration import resolve_markets_meta_table_model

        resolved_model = resolve_markets_meta_table_model(model)
        return MarketsMetaTableHandle(
            model=resolved_model,
            meta_table=_bound_meta_table(resolved_model),
            limits=self.limits,
            data_source_uid=self.data_source_uid,
            timeout=self.timeout,
            namespace=self.namespace,
        )


def _bound_meta_table(model: type[MarketsBase]) -> MetaTable | None:
    get_meta_table = getattr(model, "get_meta_table", None)
    if callable(get_meta_table):
        meta_table = get_meta_table()
        if isinstance(meta_table, MetaTable):
            return meta_table
    return None


def _bound_meta_table_uid(
    model: type[MarketsBase],
    *,
    meta_table: MetaTable | None = None,
) -> str:
    meta_table_uid = getattr(meta_table, "uid", None)
    if meta_table_uid not in (None, ""):
        return str(meta_table_uid)

    get_meta_table_uid = getattr(model, "get_meta_table_uid", None)
    if callable(get_meta_table_uid):
        meta_table_uid = get_meta_table_uid()
        if meta_table_uid not in (None, ""):
            return str(meta_table_uid)

    raise ValueError(
        "Missing registered markets MetaTable UID for "
        f"{getattr(model, '__name__', model)!r}. Bootstrap or attach the "
        "platform-managed MetaTable before compiling row operations."
    )


MarketsOperationContext = MarketsRepositoryContext | MarketsMetaTableHandle


MarketsCompiledWrite = MetaTableCompiledSQLOperation | MetaTableCompiledSQLTransaction


def resolve_markets_sql_target(
    context: MarketsOperationContext,
    *,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> tuple[str, MetaTableCompiledSQLDialect]:
    """Return the DataSource UID and SQL dialect a write compiles for.

    A write whose SQL differs by dialect resolves both once, then compiles
    offline with them. Supplying `context.data_source_uid` and `dialect`
    needs no runtime. Otherwise the Environment-selected MetaTables API runtime
    answers, and a supplied value that disagrees with it raises
    `metatables.DataSourceResolutionError`, as `compile_markets_statement` does.
    """

    if context.data_source_uid is not None and dialect is not None:
        return str(context.data_source_uid), dialect

    import metatables.runtime_context as runtime_context

    runtime = runtime_context.get_runtime_context()
    runtime_uid = runtime.require_data_source_uid()
    runtime_dialect, _paramstyle = runtime.require_sql_dialect()
    if context.data_source_uid is not None and str(context.data_source_uid) != runtime_uid:
        raise DataSourceResolutionError(
            "The requested DataSource differs from the API runtime; supply its dialect too."
        )
    if dialect is not None and dialect != runtime_dialect:
        raise DataSourceResolutionError(
            "The requested SQL dialect differs from the API runtime DataSource."
        )
    return runtime_uid, runtime_dialect


def compile_markets_statement(
    statement: Any,
    *,
    context: MarketsOperationContext,
    operation: MetaTableOperation,
    dialect: MetaTableCompiledSQLDialect | None = None,
    data_source_uid: str | None = None,
) -> MetaTableCompiledSQLOperation:
    """Compile SQLAlchemy SQL for the context's DataSource.

    When the DataSource UID (`data_source_uid`, else `context.data_source_uid`)
    or `dialect` is `None`, the compiler reads the DataSource and dialect
    together from the Environment-selected MetaTables API runtime and raises
    `metatables.DataSourceResolutionError` if that runtime has no usable
    DataSource or disagrees with the supplied value. Supplying both compiles
    offline without the runtime. `operation="select"` selects read execution;
    the other operation labels select write execution.
    """

    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        data_source_uid=data_source_uid if data_source_uid is not None else context.data_source_uid,
        dialect=dialect,
        limits=context.limits,
    )


def compile_markets_statements(
    statements: Sequence[GuardedStatement | Any],
    *,
    context: MarketsOperationContext,
    operation: MetaTableWriteOperation,
    data_source_uid: str,
    dialect: MetaTableCompiledSQLDialect,
) -> MetaTableCompiledSQLTransaction:
    """Compile write statements that run in order in one transaction (MetaTables ADR 0026).

    Used where the dialect cannot hold a multi-table write in one statement:
    SQLite accepts only `SELECT` inside `WITH`. Resolve the target first with
    `resolve_markets_sql_target`.
    """

    return compile_sqlalchemy_statements(
        statements,
        operation=operation,
        data_source_uid=data_source_uid,
        dialect=dialect,
        limits=context.limits,
    )


def execute_markets_operation(
    operation: MetaTableCompiledSQLOperation,
    *,
    context: MarketsOperationContext,
) -> dict[str, Any]:
    return MetaTable.execute_operation(operation, timeout=context.timeout)


def execute_markets_write(
    write: MarketsCompiledWrite,
    *,
    context: MarketsOperationContext,
    refused_by: Collection[str] = (),
) -> dict[str, Any]:
    """Run a compiled write: one statement, or a statement list in one transaction.

    A statement list that stops at a guard labelled in `refused_by` wrote
    nothing and answers with no rows, as the single PostgreSQL statement does
    when its own gate selects nothing. Any other guard miss raises
    `metatables.MetaTableTransactionGuardError`.
    """

    if not isinstance(write, MetaTableCompiledSQLTransaction):
        return execute_markets_operation(write, context=context)
    try:
        return MetaTable.execute_transaction(write, timeout=context.timeout)
    except MetaTableTransactionGuardError as error:
        if error.label not in refused_by:
            raise
        return {"ok": True, "operation": write.operation, "rows": [], "row_count": 0}


__all__ = [
    "MarketsCompiledWrite",
    "MarketsMetaTableHandle",
    "MarketsOperationContext",
    "MarketsRepositoryContext",
    "compile_markets_statement",
    "compile_markets_statements",
    "execute_markets_operation",
    "execute_markets_write",
    "resolve_markets_sql_target",
]
