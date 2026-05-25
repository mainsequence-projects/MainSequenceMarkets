from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.market_metadata import (
    build_create_portfolio_metadata_operation,
    build_create_rebalance_strategy_metadata_operation,
    build_create_signal_metadata_operation,
    build_delete_portfolio_metadata_operation,
    build_delete_rebalance_strategy_metadata_operation,
    build_delete_signal_metadata_operation,
    build_get_portfolio_metadata_by_unique_identifier_operation,
    build_search_portfolio_metadata_operation,
    build_search_rebalance_strategy_metadata_operation,
    build_search_signal_metadata_operation,
    build_update_portfolio_metadata_operation,
    build_update_rebalance_strategy_metadata_operation,
    build_update_signal_metadata_operation,
    execute_market_metadata_operation,
)


def create_portfolio_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_create_portfolio_metadata_operation(context, **kwargs),
    )


def get_portfolio_metadata_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_get_portfolio_metadata_by_unique_identifier_operation(context, **kwargs),
    )


def search_portfolio_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_search_portfolio_metadata_operation(context, **kwargs),
    )


def update_portfolio_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_update_portfolio_metadata_operation(context, **kwargs),
    )


def delete_portfolio_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_delete_portfolio_metadata_operation(context, **kwargs),
    )


def create_signal_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_create_signal_metadata_operation(context, **kwargs),
    )


def search_signal_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_search_signal_metadata_operation(context, **kwargs),
    )


def update_signal_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_update_signal_metadata_operation(context, **kwargs),
    )


def delete_signal_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_delete_signal_metadata_operation(context, **kwargs),
    )


def create_rebalance_strategy_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_create_rebalance_strategy_metadata_operation(context, **kwargs),
    )


def search_rebalance_strategy_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_search_rebalance_strategy_metadata_operation(context, **kwargs),
    )


def update_rebalance_strategy_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_update_rebalance_strategy_metadata_operation(context, **kwargs),
    )


def delete_rebalance_strategy_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_market_metadata_operation(
        context,
        build_delete_rebalance_strategy_metadata_operation(context, **kwargs),
    )


__all__ = [
    "create_portfolio_metadata",
    "create_rebalance_strategy_metadata",
    "create_signal_metadata",
    "delete_portfolio_metadata",
    "delete_rebalance_strategy_metadata",
    "delete_signal_metadata",
    "get_portfolio_metadata_by_unique_identifier",
    "search_portfolio_metadata",
    "search_rebalance_strategy_metadata",
    "search_signal_metadata",
    "update_portfolio_metadata",
    "update_rebalance_strategy_metadata",
    "update_signal_metadata",
]
