from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from metatables import (
    DataSourceResolutionError,
    MetaTable,
    MetaTableCompiledSQLDialect,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableOperation,
    MetaTableOperationLimits,
    MetaTableTransactionGuardError,
    MetaTableWriteOperation,
    TransferOutcomeUnknown,
)
from metatables.compiled_sql.v1 import (
    GuardedStatement,
    compile_sqlalchemy_statement,
    compile_sqlalchemy_statements,
)
from metatables.contracts.transfer import TransferError

from msm.base import MarketsBase

from .operation_count import count_operation


@dataclass(frozen=True)
class MarketsMetaTableHandle:
    """Execution handle for one registered markets MetaTable model."""

    model: type[MarketsBase]
    meta_table: MetaTable | None = None
    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    data_source_uid: str | None = None
    timeout: int | float | tuple[float, float] | None = None

    @property
    def meta_table_uid(self) -> str:
        return _bound_meta_table_uid(self.model, meta_table=self.meta_table)


@dataclass(frozen=True, init=False)
class MarketsRepositoryContext:
    """MetaTable execution context for markets repositories.

    `data_source_uid` is normally `None`, which lets the compiler take the
    DataSource and dialect from the MetaTables API runtime. An explicit UID must
    match that runtime unless a dialect is also supplied.
    """

    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    data_source_uid: str | None = None
    timeout: int | float | tuple[float, float] | None = None

    def __init__(
        self,
        limits: MetaTableOperationLimits | Mapping[str, Any] | None = None,
        data_source_uid: str | None = None,
        timeout: int | float | tuple[float, float] | None = None,
    ) -> None:
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "data_source_uid", data_source_uid)
        object.__setattr__(self, "timeout", timeout)

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

DELETE_DEADLINE_MS = 60_000
"""MetaTables' longest deadline, in milliseconds, for a delete's read and transaction.

Its 15 s default covers a whole statement list; deleting a portfolio's datasets can take
longer (issue 91)."""


def with_max_rows[ContextT: (MarketsRepositoryContext, MarketsMetaTableHandle)](
    context: ContextT, max_rows: int
) -> ContextT:
    """``context`` whose operations return at least ``max_rows`` rows."""

    limits = MetaTableOperationLimits.model_validate(context.limits or {})
    if limits.max_rows >= max_rows:
        return context
    return replace(context, limits=limits.model_copy(update={"max_rows": max_rows}))


def with_delete_deadline[ContextT: (MarketsRepositoryContext, MarketsMetaTableHandle)](
    context: ContextT,
) -> ContextT:
    """``context`` whose operations may run for `DELETE_DEADLINE_MS`."""

    limits = MetaTableOperationLimits.model_validate(context.limits or {})
    if limits.statement_timeout_ms >= DELETE_DEADLINE_MS:
        return context
    return replace(
        context,
        limits=limits.model_copy(update={"statement_timeout_ms": DELETE_DEADLINE_MS}),
    )


@dataclass
class _RuntimeLookup:
    target: tuple[str, MetaTableCompiledSQLDialect] | None = None


_lookup: ContextVar[_RuntimeLookup | None] = ContextVar("msm_runtime_lookup", default=None)


@contextmanager
def one_runtime_lookup() -> Iterator[None]:
    """Look the MetaTables API runtime up once for the Markets statements of the block.

    A run of many statements enters it (issue #140): the first statement that needs the
    DataSource and SQL dialect asks the runtime, and every later one compiles offline
    with that answer. Outside a block each statement asks; MetaTables keeps a hosted
    API's runtime for the process and asks a local API every time. The API checks the
    DataSource and dialect of every operation, so a runtime that changes during the block
    refuses its operations instead of running them elsewhere. A block inside another
    shares its lookup.
    """

    if _lookup.get() is not None:
        yield
        return
    token = _lookup.set(_RuntimeLookup())
    try:
        yield
    finally:
        _lookup.reset(token)


def _runtime_target() -> tuple[str, MetaTableCompiledSQLDialect]:
    lookup = _lookup.get()
    if lookup is not None and lookup.target is not None:
        return lookup.target

    import metatables

    runtime = metatables.get_runtime_context()
    target = (runtime.require_data_source_uid(), runtime.require_sql_dialect()[0])
    if lookup is not None:
        lookup.target = target
    return target


def _sql_target(
    data_source_uid: str | None, dialect: MetaTableCompiledSQLDialect | None
) -> tuple[str, MetaTableCompiledSQLDialect]:
    runtime_uid, runtime_dialect = _runtime_target()
    if data_source_uid is not None and str(data_source_uid) != runtime_uid:
        raise DataSourceResolutionError(
            "The requested DataSource differs from the API runtime; supply its dialect too."
        )
    if dialect is not None and dialect != runtime_dialect:
        raise DataSourceResolutionError(
            "The requested SQL dialect differs from the API runtime DataSource."
        )
    return runtime_uid, runtime_dialect


def resolve_markets_sql_target(
    context: MarketsOperationContext,
    *,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> tuple[str, MetaTableCompiledSQLDialect]:
    """Return the DataSource UID and SQL dialect a write compiles for.

    A write whose SQL differs by dialect resolves both once, then compiles
    offline with them. Supplying `context.data_source_uid` and `dialect`
    needs no runtime. Otherwise the Environment-selected MetaTables API runtime
    answers (once per `one_runtime_lookup` block), and a supplied value that
    disagrees with it raises `metatables.DataSourceResolutionError`, as
    `compile_markets_statement` does.
    """

    if context.data_source_uid is not None and dialect is not None:
        return str(context.data_source_uid), dialect
    return _sql_target(context.data_source_uid, dialect)


def values_parameter(value: Any, type_: Any, *, dialect: MetaTableCompiledSQLDialect) -> Any:
    """A bound value for a row of a SQL ``VALUES`` list.

    PostgreSQL types a ``VALUES`` list from its first row, so the value is cast to
    ``type_`` there. SQLite casts ``DATETIME`` and ``JSON`` to numbers, so the value binds
    bare and the type only converts it.
    """

    from sqlalchemy import cast, literal

    parameter = literal(value, type_)
    return cast(parameter, type_) if dialect == "postgresql" else parameter


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
    offline without the runtime, and so does every statement after the first in a
    `one_runtime_lookup` block. `operation="select"` selects read execution;
    the other operation labels select write execution.
    """

    if data_source_uid is None:
        data_source_uid = context.data_source_uid
    if _lookup.get() is not None and (data_source_uid is None or dialect is None):
        data_source_uid, dialect = _sql_target(data_source_uid, dialect)
    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        data_source_uid=data_source_uid,
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


class UnansweredReadError(TransferError):
    """A select got no answer from MetaTables: a failed read, which may be sent again.

    MetaTables raises `metatables.TransferOutcomeUnknown` for every ``execute-operation``
    call without an answer (a 5xx or a lost connection), since that route runs writes
    too and only ``/read`` is retried. A select writes nothing, so there is no outcome
    to confirm (MainSequenceMarkets#151).
    """


def execute_markets_operation(
    operation: MetaTableCompiledSQLOperation,
    *,
    context: MarketsOperationContext,
) -> dict[str, Any]:
    """Run one compiled statement.

    A select without an answer raises `UnansweredReadError`; a write without one raises
    MetaTables' `metatables.TransferOutcomeUnknown`, since it may be stored.
    """

    count_operation()
    try:
        return MetaTable.execute_operation(operation, timeout=context.timeout)
    except TransferOutcomeUnknown as error:
        if operation.operation != "select":
            raise
        raise UnansweredReadError(f"The read got no answer: {error}") from error


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
    count_operation()
    try:
        return MetaTable.execute_transaction(write, timeout=context.timeout)
    except MetaTableTransactionGuardError as error:
        if error.label not in refused_by:
            raise
        return {"ok": True, "operation": write.operation, "rows": [], "row_count": 0}


__all__ = [
    "DELETE_DEADLINE_MS",
    "MarketsCompiledWrite",
    "MarketsMetaTableHandle",
    "MarketsOperationContext",
    "MarketsRepositoryContext",
    "UnansweredReadError",
    "compile_markets_statement",
    "compile_markets_statements",
    "execute_markets_operation",
    "execute_markets_write",
    "one_runtime_lookup",
    "resolve_markets_sql_target",
    "values_parameter",
    "with_delete_deadline",
    "with_max_rows",
]
