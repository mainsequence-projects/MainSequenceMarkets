from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation
from msm.models import Portfolio, PortfolioAssetDetail

from .base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    calendar_name: str | None = None,
    portfolio_index_asset_uid: uuid.UUID | str | None = None,
    portfolio_index_asset_unique_identifier: str | None = None,
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None,
    signal_weights_data_node_uid: uuid.UUID | str | None = None,
    portfolio_data_node_uid: uuid.UUID | str | None = None,
    backtest_table_price_column_name: str = "close",
    builds_from_target_weights: bool = True,
    builds_from_predictions: bool = False,
    builds_from_target_positions: bool = False,
    tracking_funds_expected_exposure_from_latest_holdings: bool = False,
    stats_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(Portfolio)
        .values(
            unique_identifier=unique_identifier,
            calendar_name=calendar_name,
            portfolio_index_asset_uid=portfolio_index_asset_uid,
            portfolio_index_asset_unique_identifier=portfolio_index_asset_unique_identifier,
            portfolio_weights_data_node_uid=portfolio_weights_data_node_uid,
            signal_weights_data_node_uid=signal_weights_data_node_uid,
            portfolio_data_node_uid=portfolio_data_node_uid,
            backtest_table_price_column_name=backtest_table_price_column_name,
            builds_from_target_weights=builds_from_target_weights,
            builds_from_predictions=builds_from_predictions,
            builds_from_target_positions=builds_from_target_positions,
            tracking_funds_expected_exposure_from_latest_holdings=(
                tracking_funds_expected_exposure_from_latest_holdings
            ),
            stats_json=stats_json,
            metadata_json=metadata_json,
        )
        .returning(Portfolio)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[Portfolio],
        access="write",
    )


def create_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_get_portfolio_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = select(Portfolio).where(Portfolio.unique_identifier == unique_identifier).limit(1)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[Portfolio],
        access="read",
    )


def get_portfolio_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_portfolio_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    calendar_name: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = select(Portfolio).limit(limit)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            Portfolio.unique_identifier.contains(str(unique_identifier_contains))
        )
    if calendar_name not in (None, ""):
        statement = statement.where(Portfolio.calendar_name == str(calendar_name))
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[Portfolio],
        access="read",
    )


def search_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolios_operation(context, **kwargs),
        context=context,
    )


def build_update_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(Portfolio)
        .where(Portfolio.uid == uid)
        .values(**{key: value for key, value in values.items() if value is not None})
        .returning(Portfolio)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[Portfolio],
        access="write",
    )


def update_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(Portfolio).where(Portfolio.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[Portfolio],
        access="write",
    )


def delete_portfolio(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_operation(context, uid=uid),
        context=context,
    )


def build_create_portfolio_asset_detail_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str | None = None,
    asset_unique_identifier: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=PortfolioAssetDetail,
        values={
            "portfolio_uid": portfolio_uid,
            "asset_uid": asset_uid,
            "asset_unique_identifier": asset_unique_identifier,
            "metadata_json": metadata_json,
        },
    )


def create_portfolio_asset_detail(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_portfolio_asset_detail_operation(context, **kwargs),
        context=context,
    )


def build_search_portfolio_asset_details_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str | None = None,
    asset_uid: uuid.UUID | str | None = None,
    asset_unique_identifier: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "portfolio_uid": portfolio_uid,
        "asset_uid": asset_uid,
        "asset_unique_identifier": asset_unique_identifier,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(
        context,
        model=PortfolioAssetDetail,
        filters=filters,
        limit=limit,
    )


def search_portfolio_asset_details(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolio_asset_details_operation(context, **kwargs),
        context=context,
    )


def build_update_portfolio_asset_detail_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str | None = None,
    asset_unique_identifier: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=PortfolioAssetDetail,
        uid=uid,
        values={
            "asset_uid": asset_uid,
            "asset_unique_identifier": asset_unique_identifier,
            "metadata_json": metadata_json,
        },
    )


def update_portfolio_asset_detail(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_portfolio_asset_detail_operation(context, **kwargs),
        context=context,
    )


def build_delete_portfolio_asset_detail_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=PortfolioAssetDetail, uid=uid)


def delete_portfolio_asset_detail(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_asset_detail_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_portfolio_asset_detail_operation",
    "build_create_portfolio_operation",
    "build_delete_portfolio_asset_detail_operation",
    "build_delete_portfolio_operation",
    "build_get_portfolio_by_unique_identifier_operation",
    "build_search_portfolio_asset_details_operation",
    "build_search_portfolios_operation",
    "build_update_portfolio_asset_detail_operation",
    "build_update_portfolio_operation",
    "create_portfolio_asset_detail",
    "create_portfolio",
    "delete_portfolio_asset_detail",
    "delete_portfolio",
    "get_portfolio_by_unique_identifier",
    "search_portfolio_asset_details",
    "search_portfolios",
    "update_portfolio_asset_detail",
    "update_portfolio",
]
