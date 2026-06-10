from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.metatables import MetaTableCompiledSQLOperation
from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.models import PortfolioTable


def build_create_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    calendar_uid: uuid.UUID | str,
    published_index_uid: uuid.UUID | str | None = None,
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None,
    signal_weights_data_node_uid: uuid.UUID | str | None = None,
    signal_uid: str | None = None,
    portfolio_data_node_uid: uuid.UUID | str | None = None,
    backtest_table_price_column_name: str = "close",
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(PortfolioTable)
        .values(
            unique_identifier=unique_identifier,
            calendar_uid=calendar_uid,
            published_index_uid=published_index_uid,
            portfolio_weights_data_node_uid=portfolio_weights_data_node_uid,
            signal_weights_data_node_uid=signal_weights_data_node_uid,
            signal_uid=signal_uid,
            portfolio_data_node_uid=portfolio_data_node_uid,
            backtest_table_price_column_name=backtest_table_price_column_name,
        )
        .returning(PortfolioTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[PortfolioTable],
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
    statement = (
        select(PortfolioTable).where(PortfolioTable.unique_identifier == unique_identifier).limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[PortfolioTable],
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
    calendar_uid: uuid.UUID | str | None = None,
    published_index_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = select(PortfolioTable).limit(limit)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            PortfolioTable.unique_identifier.contains(str(unique_identifier_contains))
        )
    if calendar_uid not in (None, ""):
        statement = statement.where(PortfolioTable.calendar_uid == calendar_uid)
    if published_index_uid not in (None, ""):
        statement = statement.where(PortfolioTable.published_index_uid == published_index_uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[PortfolioTable],
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
        update(PortfolioTable)
        .where(PortfolioTable.uid == uid)
        .values(**{key: value for key, value in values.items() if value is not None})
        .returning(PortfolioTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[PortfolioTable],
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
    statement = delete(PortfolioTable).where(PortfolioTable.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[PortfolioTable],
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


__all__ = [
    "build_create_portfolio_operation",
    "build_delete_portfolio_operation",
    "build_get_portfolio_by_unique_identifier_operation",
    "build_search_portfolios_operation",
    "build_update_portfolio_operation",
    "create_portfolio",
    "delete_portfolio",
    "get_portfolio_by_unique_identifier",
    "search_portfolios",
    "update_portfolio",
]
