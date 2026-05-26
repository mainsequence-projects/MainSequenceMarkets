from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import AssetMasterListTable

from .base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_asset_master_list_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    name: str,
    reference_meta_table_uid: uuid.UUID | str,
    description: str = "",
    is_default: bool = False,
    validation_version: str = "v1",
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AssetMasterListTable,
        values={
            "unique_identifier": unique_identifier,
            "name": name,
            "description": description,
            "reference_meta_table_uid": reference_meta_table_uid,
            "is_default": is_default,
            "validation_version": validation_version,
            "metadata_json": metadata_json,
        },
    )


def create_asset_master_list(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_asset_master_list_operation(context, **kwargs),
        context=context,
    )


def build_get_asset_master_list_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=AssetMasterListTable, uid=uid)


def get_asset_master_list_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_master_list_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_get_asset_master_list_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        context,
        model=AssetMasterListTable,
        unique_identifier=unique_identifier,
    )


def get_asset_master_list_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_master_list_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_get_default_asset_master_list_operation(
    context: MarketsRepositoryContext,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(AssetMasterListTable).where(AssetMasterListTable.is_default.is_(True)).limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[AssetMasterListTable],
        access="read",
    )


def get_default_asset_master_list(context: MarketsRepositoryContext) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_default_asset_master_list_operation(context),
        context=context,
    )


def build_search_asset_master_lists_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    name_contains: str | None = None,
    is_default: bool | None = None,
    reference_meta_table_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if is_default is not None:
        filters["is_default"] = is_default
    if reference_meta_table_uid is not None:
        filters["reference_meta_table_uid"] = reference_meta_table_uid
    return build_search_model_operation(
        context,
        model=AssetMasterListTable,
        filters=filters,
        contains_filters={
            "unique_identifier": unique_identifier_contains or "",
            "name": name_contains or "",
        },
        limit=limit,
    )


def search_asset_master_lists(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_asset_master_lists_operation(context, **kwargs),
        context=context,
    )


def build_update_asset_master_list_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    name: str | None = None,
    description: str | None = None,
    reference_meta_table_uid: uuid.UUID | str | None = None,
    is_default: bool | None = None,
    validation_version: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=AssetMasterListTable,
        uid=uid,
        values={
            "name": name,
            "description": description,
            "reference_meta_table_uid": reference_meta_table_uid,
            "is_default": is_default,
            "validation_version": validation_version,
            "metadata_json": metadata_json,
        },
    )


def update_asset_master_list(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_asset_master_list_operation(context, **kwargs),
        context=context,
    )


def build_delete_asset_master_list_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=AssetMasterListTable, uid=uid)


def delete_asset_master_list(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_master_list_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_asset_master_list_operation",
    "build_delete_asset_master_list_operation",
    "build_get_asset_master_list_by_uid_operation",
    "build_get_asset_master_list_by_unique_identifier_operation",
    "build_get_default_asset_master_list_operation",
    "build_search_asset_master_lists_operation",
    "build_update_asset_master_list_operation",
    "create_asset_master_list",
    "delete_asset_master_list",
    "get_asset_master_list_by_uid",
    "get_asset_master_list_by_unique_identifier",
    "get_default_asset_master_list",
    "search_asset_master_lists",
    "update_asset_master_list",
]
