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
class MarketsRepositoryContext:
    """MetaTable execution context for markets repositories."""

    target_meta_table_uid_by_fullname: Mapping[str, str]
    limits: MetaTableOperationLimits | Mapping[str, Any] | None = None
    timeout: int | float | tuple[float, float] | None = None

    def meta_table_uid_for_model(self, model: type[MarketsBase]) -> str:
        fullname = str(model.__table__.fullname)
        meta_table_uid = self.target_meta_table_uid_by_fullname.get(fullname)
        if meta_table_uid in (None, ""):
            raise ValueError(
                "Missing registered markets MetaTable UID for SQLAlchemy table "
                f"{fullname!r}."
            )
        return str(meta_table_uid)

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


def compile_markets_statement(
    statement: Any,
    *,
    context: MarketsRepositoryContext,
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
    context: MarketsRepositoryContext,
) -> dict[str, Any]:
    return MetaTable.execute_operation(operation, timeout=context.timeout)


__all__ = [
    "MarketsRepositoryContext",
    "compile_markets_statement",
    "execute_markets_operation",
]
