from __future__ import annotations

from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.repositories import MarketsRepositoryContext
from msm.repositories.execution import (
    build_create_order_manager_operation,
    build_search_order_managers_operation,
    build_update_order_manager_operation,
    execute_execution_operation,
)


def create_order_manager(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_create_order_manager_operation(context, **kwargs))


def search_order_managers(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_search_order_managers_operation(context, **kwargs))


def update_order_manager(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_update_order_manager_operation(context, **kwargs))


def _execute(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_execution_operation(context, operation)


__all__ = [
    "create_order_manager",
    "search_order_managers",
    "update_order_manager",
]
