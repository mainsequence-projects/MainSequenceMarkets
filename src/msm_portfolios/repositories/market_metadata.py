from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.repositories.base import MarketsRepositoryContext, execute_markets_operation
from msm.repositories.crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
)
from msm_portfolios.models import (
    PortfolioMetadataTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
)


def build_create_portfolio_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    description: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=PortfolioMetadataTable,
        values={
            "unique_identifier": unique_identifier,
            "description": description,
        },
    )


def create_portfolio_metadata(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_portfolio_metadata_operation(context, **kwargs),
        context=context,
    )


def build_get_portfolio_metadata_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        context,
        model=PortfolioMetadataTable,
        unique_identifier=unique_identifier,
    )


def build_search_portfolio_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    return build_search_model_operation(
        context,
        model=PortfolioMetadataTable,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
        limit=limit,
    )


def build_update_portfolio_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    description: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=PortfolioMetadataTable,
        uid=uid,
        values={"description": description},
    )


def build_delete_portfolio_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=PortfolioMetadataTable, uid=uid)


def build_create_signal_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    signal_uid: str,
    signal_description: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=SignalMetadataTable,
        values={
            "signal_uid": signal_uid,
            "signal_description": signal_description,
        },
    )


def build_search_signal_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    signal_uid: str | None = None,
    signal_uid_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if signal_uid not in (None, ""):
        filters["signal_uid"] = signal_uid
    return build_search_model_operation(
        context,
        model=SignalMetadataTable,
        filters=filters,
        contains_filters={"signal_uid": signal_uid_contains or ""},
        limit=limit,
    )


def build_update_signal_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    signal_description: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=SignalMetadataTable,
        uid=uid,
        values={"signal_description": signal_description},
    )


def build_delete_signal_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=SignalMetadataTable, uid=uid)


def build_create_rebalance_strategy_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    rebalance_strategy_uid: str,
    rebalance_strategy_description: str | None = None,
    configuration_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=RebalanceStrategyMetadataTable,
        values={
            "rebalance_strategy_uid": rebalance_strategy_uid,
            "rebalance_strategy_description": rebalance_strategy_description,
            "configuration_json": configuration_json,
        },
    )


def build_search_rebalance_strategy_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    rebalance_strategy_uid: str | None = None,
    rebalance_strategy_uid_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if rebalance_strategy_uid not in (None, ""):
        filters["rebalance_strategy_uid"] = rebalance_strategy_uid
    return build_search_model_operation(
        context,
        model=RebalanceStrategyMetadataTable,
        filters=filters,
        contains_filters={"rebalance_strategy_uid": rebalance_strategy_uid_contains or ""},
        limit=limit,
    )


def build_update_rebalance_strategy_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    rebalance_strategy_description: str | None = None,
    configuration_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=RebalanceStrategyMetadataTable,
        uid=uid,
        values={
            "rebalance_strategy_description": rebalance_strategy_description,
            "configuration_json": configuration_json,
        },
    )


def build_delete_rebalance_strategy_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=RebalanceStrategyMetadataTable, uid=uid)


def execute_market_metadata_operation(
    context: MarketsRepositoryContext,
    operation: MetaTableCompiledSQLOperation,
) -> dict[str, Any]:
    return execute_markets_operation(operation, context=context)


__all__ = [
    "build_create_portfolio_metadata_operation",
    "build_create_rebalance_strategy_metadata_operation",
    "build_create_signal_metadata_operation",
    "build_delete_portfolio_metadata_operation",
    "build_delete_rebalance_strategy_metadata_operation",
    "build_delete_signal_metadata_operation",
    "build_get_portfolio_metadata_by_unique_identifier_operation",
    "build_search_portfolio_metadata_operation",
    "build_search_rebalance_strategy_metadata_operation",
    "build_search_signal_metadata_operation",
    "build_update_portfolio_metadata_operation",
    "build_update_rebalance_strategy_metadata_operation",
    "build_update_signal_metadata_operation",
    "execute_market_metadata_operation",
]
