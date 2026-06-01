from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm_portfolios.repositories import portfolios as portfolio_repository


def create_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.create_portfolio(context, **kwargs)


def get_portfolio_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return portfolio_repository.get_portfolio_by_unique_identifier(context, **kwargs)


def search_portfolios(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.search_portfolios(context, **kwargs)


def update_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.update_portfolio(context, **kwargs)


def delete_portfolio(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return portfolio_repository.delete_portfolio(context, **kwargs)


__all__ = [
    "create_portfolio",
    "delete_portfolio",
    "get_portfolio_by_unique_identifier",
    "search_portfolios",
    "update_portfolio",
]
