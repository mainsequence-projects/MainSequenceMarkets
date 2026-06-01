from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm_portfolios.repositories import (
    create_fund as repository_create_fund,
)
from msm_portfolios.repositories import (
    delete_fund as repository_delete_fund,
)
from msm_portfolios.repositories import (
    get_fund_by_unique_identifier as repository_get_fund_by_unique_identifier,
)
from msm_portfolios.repositories import (
    get_funds_by_account as repository_get_funds_by_account,
)
from msm_portfolios.repositories import (
    get_funds_by_portfolio as repository_get_funds_by_portfolio,
)
from msm_portfolios.repositories import (
    update_fund as repository_update_fund,
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


def get_fund_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_fund_by_unique_identifier(context, **kwargs)


def get_funds_by_account(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_funds_by_account(context, **kwargs)


def update_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_update_fund(context, **kwargs)


def delete_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_delete_fund(context, **kwargs)


__all__ = [
    "create_fund",
    "delete_fund",
    "get_fund_by_unique_identifier",
    "get_funds_by_account",
    "get_funds_by_portfolio",
    "update_fund",
]
