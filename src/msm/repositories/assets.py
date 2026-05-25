from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import Asset

from .base import MarketsRepositoryContext, compile_markets_statement, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_asset_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    asset_type: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=Asset,
        values={
            "unique_identifier": unique_identifier,
            "asset_type": asset_type,
        },
    )


def create_asset(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_asset_operation(context, **kwargs),
        context=context,
    )


def build_upsert_asset_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    asset_type: str | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = (
        postgresql_insert(Asset)
        .values(
            unique_identifier=unique_identifier,
            asset_type=asset_type,
        )
        .on_conflict_do_update(
            index_elements=[Asset.unique_identifier],
            set_={
                "asset_type": asset_type,
            },
        )
        .returning(Asset)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        models=[Asset],
        access="write",
    )


def upsert_asset(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_upsert_asset_operation(context, **kwargs),
        context=context,
    )


def build_get_asset_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=Asset, uid=uid)


def get_asset_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_get_asset_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        context,
        model=Asset,
        unique_identifier=unique_identifier,
    )


def get_asset_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_assets_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    asset_type: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if asset_type not in (None, ""):
        filters["asset_type"] = asset_type
    return build_search_model_operation(
        context,
        model=Asset,
        filters=filters,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
        limit=limit,
    )


def search_assets(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_assets_operation(context, **kwargs),
        context=context,
    )


def build_update_asset_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    asset_type: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=Asset,
        uid=uid,
        values={
            "asset_type": asset_type,
        },
    )


def update_asset(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_asset_operation(context, **kwargs),
        context=context,
    )


def build_delete_asset_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=Asset, uid=uid)


def delete_asset(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_asset_operation",
    "build_delete_asset_operation",
    "build_get_asset_by_uid_operation",
    "build_get_asset_by_unique_identifier_operation",
    "build_search_assets_operation",
    "build_update_asset_operation",
    "build_upsert_asset_operation",
    "create_asset",
    "delete_asset",
    "get_asset_by_uid",
    "get_asset_by_unique_identifier",
    "search_assets",
    "update_asset",
    "upsert_asset",
]
