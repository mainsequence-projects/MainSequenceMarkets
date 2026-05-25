from __future__ import annotations

from typing import Any

from msm.repositories import (
    MarketsRepositoryContext,
    create_fund as repository_create_fund,
    get_funds_by_account as repository_get_funds_by_account,
    get_funds_by_portfolio as repository_get_funds_by_portfolio,
)


def create_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_create_fund(context, **kwargs)


def get_funds_by_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_funds_by_portfolio(context, **kwargs)


def get_funds_by_account(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_funds_by_account(context, **kwargs)


__all__ = [
    "create_fund",
    "get_funds_by_account",
    "get_funds_by_portfolio",
]
