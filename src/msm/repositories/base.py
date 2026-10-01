from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from metatables import (
    MetaTable,
    MetaTableCompiledSQLDialect,
    MetaTableCompiledSQLOperation,
    MetaTableOperation,
    MetaTableOperationLimits,
)
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement

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


def compile_markets_statement(
    statement: Any,
    *,
    context: MarketsOperationContext,
    operation: MetaTableOperation,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MetaTableCompiledSQLOperation:
    """Compile SQLAlchemy SQL for the context's DataSource.

    When `context.data_source_uid` or `dialect` is `None`, the compiler reads
    the DataSource and dialect together from the Environment-selected
    MetaTables API runtime and raises `metatables.DataSourceResolutionError`
    if that runtime has no usable DataSource or disagrees with the supplied
    value. Supplying both compiles offline without the runtime.
    `operation="select"` selects read execution; the other operation labels
    select write execution.
    """

    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        data_source_uid=context.data_source_uid,
        dialect=dialect,
        limits=context.limits,
    )


def execute_markets_operation(
    operation: MetaTableCompiledSQLOperation,
    *,
    context: MarketsOperationContext,
) -> dict[str, Any]:
    return MetaTable.execute_operation(operation, timeout=context.timeout)


__all__ = [
    "MarketsMetaTableHandle",
    "MarketsOperationContext",
    "MarketsRepositoryContext",
    "compile_markets_statement",
    "execute_markets_operation",
]
