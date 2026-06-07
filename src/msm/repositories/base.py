from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mainsequence.client.metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableOperation,
    MetaTableOperationLimits,
    MetaTableOperationScopeTable,
)
from mainsequence.meta_tables.compiled_sql.v1 import compile_sqlalchemy_statement

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
    reserved_policy: Literal["reject", "reconcile"] | None = None

    @property
    def meta_table_uid(self) -> str:
        return _bound_meta_table_uid(self.model, meta_table=self.meta_table)

    def meta_table_uid_for_model(self, model: type[MarketsBase]) -> str:
        if model is not self.model:
            raise ValueError(
                f"{self.model.__name__} handle cannot compile operations for {model.__name__}."
            )
        return _bound_meta_table_uid(model, meta_table=self.meta_table)

    def scope_table(
        self,
        model: type[MarketsBase],
        *,
        access: str = "read",
        alias: str | None = None,
    ) -> MetaTableOperationScopeTable:
        return MetaTableOperationScopeTable(
            meta_table_uid=self.meta_table_uid_for_model(model),
            alias=alias,
            access=access,
            reserved_policy=self.reserved_policy,
        )


@dataclass(frozen=True, init=False)
class MarketsRepositoryContext:
    """MetaTable execution context for markets repositories.

    `namespace` records the runtime namespace override selected during
    bootstrap. `None` means the library's normal MetaTable namespace was used.
    """

    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    data_source_uid: str | None = None
    timeout: int | float | tuple[float, float] | None = None
    namespace: str | None = None
    reserved_policy: Literal["reject", "reconcile"] | None = None

    def __init__(
        self,
        limits: MetaTableOperationLimits | Mapping[str, Any] | None = None,
        data_source_uid: str | None = None,
        timeout: int | float | tuple[float, float] | None = None,
        namespace: str | None = None,
        reserved_policy: Literal["reject", "reconcile"] | None = None,
    ) -> None:
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "data_source_uid", data_source_uid)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "reserved_policy", reserved_policy)

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
            reserved_policy=self.reserved_policy,
        )

    def scope_table(
        self,
        model: type[MarketsBase],
        *,
        access: str = "read",
        alias: str | None = None,
    ) -> MetaTableOperationScopeTable:
        return MetaTableOperationScopeTable(
            meta_table_uid=self.meta_table_uid_for_model(model),
            alias=alias,
            access=access,
            reserved_policy=self.reserved_policy,
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
    models: Sequence[type[MarketsBase]],
    access: str,
) -> MetaTableCompiledSQLOperation:
    kwargs: dict[str, Any] = {
        "operation": operation,
        "scope_tables": [context.scope_table(model, access=access) for model in models],
        "limits": context.limits,
    }
    if "data_source_uid" in inspect.signature(compile_sqlalchemy_statement).parameters:
        kwargs["data_source_uid"] = getattr(context, "data_source_uid", None)
    return compile_sqlalchemy_statement(statement, **kwargs)


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
