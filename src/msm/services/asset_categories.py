from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.asset_categories import (
    create_asset_category as repository_create_asset_category,
    create_asset_category_membership as repository_create_asset_category_membership,
    delete_asset_category as repository_delete_asset_category,
    delete_asset_category_membership as repository_delete_asset_category_membership,
    delete_asset_category_membership_by_pair as repository_delete_asset_category_membership_by_pair,
    get_asset_category_by_unique_identifier as repository_get_asset_category_by_unique_identifier,
    get_asset_category_by_uid as repository_get_asset_category_by_uid,
    replace_asset_category_memberships as repository_replace_asset_category_memberships,
    search_asset_categories as repository_search_asset_categories,
    search_asset_category_memberships as repository_search_asset_category_memberships,
    update_asset_category as repository_update_asset_category,
)


def create_asset_category(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_create_asset_category(context, **kwargs)


def get_asset_category_by_uid(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_asset_category_by_uid(context, **kwargs)


def get_asset_category_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_asset_category_by_unique_identifier(context, **kwargs)


def search_asset_categories(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_search_asset_categories(context, **kwargs)


def update_asset_category(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_update_asset_category(context, **kwargs)


def delete_asset_category(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_delete_asset_category(context, **kwargs)


def append_asset_category_membership(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_create_asset_category_membership(context, **kwargs)


def list_asset_category_memberships(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_search_asset_category_memberships(context, **kwargs)


def remove_asset_category_membership(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_delete_asset_category_membership(context, **kwargs)


def remove_asset_category_membership_by_pair(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_delete_asset_category_membership_by_pair(context, **kwargs)


def replace_asset_category_memberships(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return repository_replace_asset_category_memberships(context, **kwargs)


__all__ = [
    "append_asset_category_membership",
    "create_asset_category",
    "delete_asset_category",
    "get_asset_category_by_uid",
    "get_asset_category_by_unique_identifier",
    "list_asset_category_memberships",
    "remove_asset_category_membership",
    "remove_asset_category_membership_by_pair",
    "replace_asset_category_memberships",
    "search_asset_categories",
    "update_asset_category",
]
