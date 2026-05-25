from __future__ import annotations

from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.repositories import MarketsRepositoryContext
from msm.repositories.execution import (
    build_create_execution_error_operation,
    build_create_order_manager_operation,
    build_create_order_operation,
    build_create_order_status_event_operation,
    build_create_order_target_quantity_operation,
    build_create_trade_operation,
    build_search_execution_errors_operation,
    build_search_order_managers_operation,
    build_search_order_status_events_operation,
    build_search_order_target_quantities_operation,
    build_search_orders_operation,
    build_search_trades_operation,
    build_update_order_manager_operation,
    build_update_order_operation,
    execute_execution_operation,
)


def create_order_manager(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_create_order_manager_operation(context, **kwargs))


def search_order_managers(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_search_order_managers_operation(context, **kwargs))


def update_order_manager(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_update_order_manager_operation(context, **kwargs))


def create_order_target_quantity(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_create_order_target_quantity_operation(context, **kwargs))


def search_order_target_quantities(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_search_order_target_quantities_operation(context, **kwargs))


def create_order(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_create_order_operation(context, **kwargs))


def search_orders(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_search_orders_operation(context, **kwargs))


def update_order(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_update_order_operation(context, **kwargs))


def create_order_status_event(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_create_order_status_event_operation(context, **kwargs))


def search_order_status_events(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_search_order_status_events_operation(context, **kwargs))


def create_trade(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_create_trade_operation(context, **kwargs))


def search_trades(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return _execute(context, build_search_trades_operation(context, **kwargs))


def create_execution_error(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_create_execution_error_operation(context, **kwargs))


def search_execution_errors(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return _execute(context, build_search_execution_errors_operation(context, **kwargs))


def _execute(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_execution_operation(context, operation)


__all__ = [
    "create_execution_error",
    "create_order",
    "create_order_manager",
    "create_order_status_event",
    "create_order_target_quantity",
    "create_trade",
    "search_execution_errors",
    "search_order_managers",
    "search_order_status_events",
    "search_order_target_quantities",
    "search_orders",
    "search_trades",
    "update_order",
    "update_order_manager",
]
