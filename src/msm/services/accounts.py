from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories import accounts as account_repository


def create_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.create_account(context, **kwargs)


def get_account_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.get_account_by_unique_identifier(context, **kwargs)


def search_accounts(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.search_accounts(context, **kwargs)


def update_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.update_account(context, **kwargs)


def delete_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.delete_account(context, **kwargs)


def create_account_target_position_assignment(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.create_account_target_position_assignment(context, **kwargs)


def search_account_target_position_assignments(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.search_account_target_position_assignments(context, **kwargs)


def delete_account_target_position_assignment(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.delete_account_target_position_assignment(context, **kwargs)


__all__ = [
    "create_account",
    "create_account_target_position_assignment",
    "delete_account",
    "delete_account_target_position_assignment",
    "get_account_by_unique_identifier",
    "search_account_target_position_assignments",
    "search_accounts",
    "update_account",
]
