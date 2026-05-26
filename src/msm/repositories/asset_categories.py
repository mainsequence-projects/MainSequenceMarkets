from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import AssetCategoryTable, AssetCategoryMembershipTable

from .base import MarketsRepositoryContext, compile_markets_statement, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_asset_category_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    display_name: str,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AssetCategoryTable,
        values={
            "unique_identifier": unique_identifier,
            "display_name": display_name,
            "description": description,
            "metadata_json": metadata_json,
        },
    )


def create_asset_category(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_asset_category_operation(context, **kwargs),
        context=context,
    )


def build_get_asset_category_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=AssetCategoryTable, uid=uid)


def get_asset_category_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_category_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_get_asset_category_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        context,
        model=AssetCategoryTable,
        unique_identifier=unique_identifier,
    )


def get_asset_category_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_category_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_asset_categories_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    display_name_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    return build_search_model_operation(
        context,
        model=AssetCategoryTable,
        contains_filters={
            "unique_identifier": unique_identifier_contains or "",
            "display_name": display_name_contains or "",
        },
        limit=limit,
    )


def search_asset_categories(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_asset_categories_operation(context, **kwargs),
        context=context,
    )


def build_update_asset_category_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    display_name: str | None = None,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=AssetCategoryTable,
        uid=uid,
        values={
            "display_name": display_name,
            "description": description,
            "metadata_json": metadata_json,
        },
    )


def update_asset_category(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_asset_category_operation(context, **kwargs),
        context=context,
    )


def build_delete_asset_category_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=AssetCategoryTable, uid=uid)


def delete_asset_category(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_category_operation(context, uid=uid),
        context=context,
    )


def build_create_asset_category_membership_operation(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AssetCategoryMembershipTable,
        values={
            "category_uid": category_uid,
            "asset_uid": asset_uid,
        },
    )


def create_asset_category_membership(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_asset_category_membership_operation(context, **kwargs),
        context=context,
    )


def build_search_asset_category_memberships_operation(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str | None = None,
    asset_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if category_uid is not None:
        filters["category_uid"] = category_uid
    if asset_uid is not None:
        filters["asset_uid"] = asset_uid
    return build_search_model_operation(
        context,
        model=AssetCategoryMembershipTable,
        filters=filters,
        limit=limit,
    )


def search_asset_category_memberships(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_asset_category_memberships_operation(context, **kwargs),
        context=context,
    )


def build_delete_asset_category_membership_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=AssetCategoryMembershipTable, uid=uid)


def build_delete_asset_category_membership_by_pair_operation(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(AssetCategoryMembershipTable).where(
        AssetCategoryMembershipTable.category_uid == category_uid,
        AssetCategoryMembershipTable.asset_uid == asset_uid,
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[AssetCategoryMembershipTable],
        access="write",
    )


def build_delete_asset_category_memberships_for_category_operation(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(AssetCategoryMembershipTable).where(
        AssetCategoryMembershipTable.category_uid == category_uid
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[AssetCategoryMembershipTable],
        access="write",
    )


def build_replace_asset_category_memberships_operations(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
    asset_uids: Sequence[uuid.UUID | str],
) -> list[MetaTableCompiledSQLOperation]:
    operations = [
        build_delete_asset_category_memberships_for_category_operation(
            context,
            category_uid=category_uid,
        )
    ]
    operations.extend(
        build_create_asset_category_membership_operation(
            context,
            category_uid=category_uid,
            asset_uid=asset_uid,
        )
        for asset_uid in asset_uids
    )
    return operations


def delete_asset_category_membership(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_category_membership_operation(context, uid=uid),
        context=context,
    )


def delete_asset_category_membership_by_pair(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
    asset_uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_category_membership_by_pair_operation(
            context,
            category_uid=category_uid,
            asset_uid=asset_uid,
        ),
        context=context,
    )


def delete_asset_category_memberships_for_category(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_category_memberships_for_category_operation(
            context,
            category_uid=category_uid,
        ),
        context=context,
    )


def replace_asset_category_memberships(
    context: MarketsRepositoryContext,
    *,
    category_uid: uuid.UUID | str,
    asset_uids: Sequence[uuid.UUID | str],
) -> list[dict[str, Any]]:
    return [
        execute_markets_operation(operation, context=context)
        for operation in build_replace_asset_category_memberships_operations(
            context,
            category_uid=category_uid,
            asset_uids=asset_uids,
        )
    ]


__all__ = [
    "build_create_asset_category_membership_operation",
    "build_create_asset_category_operation",
    "build_delete_asset_category_membership_operation",
    "build_delete_asset_category_membership_by_pair_operation",
    "build_delete_asset_category_memberships_for_category_operation",
    "build_delete_asset_category_operation",
    "build_get_asset_category_by_uid_operation",
    "build_get_asset_category_by_unique_identifier_operation",
    "build_search_asset_categories_operation",
    "build_search_asset_category_memberships_operation",
    "build_replace_asset_category_memberships_operations",
    "build_update_asset_category_operation",
    "create_asset_category",
    "create_asset_category_membership",
    "delete_asset_category",
    "delete_asset_category_membership",
    "delete_asset_category_membership_by_pair",
    "delete_asset_category_memberships_for_category",
    "get_asset_category_by_uid",
    "get_asset_category_by_unique_identifier",
    "search_asset_categories",
    "search_asset_category_memberships",
    "replace_asset_category_memberships",
    "update_asset_category",
]
