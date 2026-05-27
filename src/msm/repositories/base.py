from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mainsequence.client.models_metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableOperation,
    MetaTableOperationLimits,
    MetaTableOperationScopeTable,
)
from mainsequence.tdag.meta_tables import compile_sqlalchemy_statement

from msm.base import MarketsBase


@dataclass(frozen=True)
class MarketsMetaTableHandle:
    """Execution handle for one registered markets MetaTable model."""

    model: type[MarketsBase]
    meta_table_uid: str
    meta_table: MetaTable | None = None
    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    timeout: int | float | tuple[float, float] | None = None
    namespace: str | None = None

    def meta_table_uid_for_model(self, model: type[MarketsBase]) -> str:
        if model is not self.model:
            raise ValueError(
                f"{self.model.__name__} handle cannot compile operations for {model.__name__}."
            )
        return self.meta_table_uid

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
        )


@dataclass(frozen=True)
class MarketsRepositoryContext:
    """MetaTable execution context for markets repositories.

    `namespace` records the runtime namespace override selected during
    bootstrap. `None` means the library's normal MetaTable namespace was used.
    """

    target_meta_table_uid_by_fullname: Mapping[str, str]
    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    timeout: int | float | tuple[float, float] | None = None
    namespace: str | None = None

    def meta_table_uid_for_model(self, model: type[MarketsBase]) -> str:
        fullname = str(model.__table__.fullname)
        meta_table_uid = self.target_meta_table_uid_by_fullname.get(fullname)
        if meta_table_uid in (None, ""):
            raise ValueError(
                f"Missing registered markets MetaTable UID for SQLAlchemy table {fullname!r}."
            )
        return str(meta_table_uid)

    def table(self, model: type[MarketsBase] | str) -> MarketsMetaTableHandle:
        from msm.models.registration import resolve_markets_meta_table_model

        resolved_model = resolve_markets_meta_table_model(model)
        return MarketsMetaTableHandle(
            model=resolved_model,
            meta_table_uid=self.meta_table_uid_for_model(resolved_model),
            limits=self.limits,
            timeout=self.timeout,
            namespace=self.namespace,
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
    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        scope_tables=[context.scope_table(model, access=access) for model in models],
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
