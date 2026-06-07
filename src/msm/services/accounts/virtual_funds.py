from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.virtual_funds import (
    create_virtual_fund as repository_create_virtual_fund,
)
from msm.repositories.virtual_funds import (
    delete_virtual_fund as repository_delete_virtual_fund,
)
from msm.repositories.virtual_funds import (
    get_virtual_fund_by_unique_identifier as repository_get_virtual_fund_by_unique_identifier,
)
from msm.repositories.virtual_funds import (
    get_virtual_funds_by_account as repository_get_virtual_funds_by_account,
)
from msm.repositories.virtual_funds import (
    get_virtual_funds_by_portfolio as repository_get_virtual_funds_by_portfolio,
)
from msm.repositories.virtual_funds import (
    update_virtual_fund as repository_update_virtual_fund,
)


def create_virtual_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_create_virtual_fund(context, **kwargs)


def get_virtual_funds_by_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_virtual_funds_by_portfolio(context, **kwargs)


def get_virtual_fund_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_virtual_fund_by_unique_identifier(context, **kwargs)


def get_virtual_funds_by_account(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_virtual_funds_by_account(context, **kwargs)


def update_virtual_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_update_virtual_fund(context, **kwargs)


def delete_virtual_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_delete_virtual_fund(context, **kwargs)


__all__ = [
    "create_virtual_fund",
    "delete_virtual_fund",
    "get_virtual_fund_by_unique_identifier",
    "get_virtual_funds_by_account",
    "get_virtual_funds_by_portfolio",
    "update_virtual_fund",
]
