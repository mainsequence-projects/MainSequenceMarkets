from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import AccountGroup, AccountModelPortfolio

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_account_model_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    model_portfolio_name: str,
    model_portfolio_description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountModelPortfolio,
        values={
            "model_portfolio_name": model_portfolio_name,
            "model_portfolio_description": model_portfolio_description,
            "metadata_json": metadata_json,
        },
    )


def create_account_model_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_model_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_search_account_model_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    model_portfolio_name_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    return build_search_model_operation(
        context,
        model=AccountModelPortfolio,
        contains_filters={
            "model_portfolio_name": model_portfolio_name_contains or "",
        },
        limit=limit,
    )


def search_account_model_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_model_portfolios_operation(context, **kwargs),
        context=context,
    )


def build_create_account_group_operation(
    context: MarketsRepositoryContext,
    *,
    group_name: str | None = None,
    group_description: str | None = None,
    account_model_portfolio_uid: uuid.UUID | str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountGroup,
        values={
            "group_name": group_name,
            "group_description": group_description,
            "account_model_portfolio_uid": account_model_portfolio_uid,
            "metadata_json": metadata_json,
        },
    )


def create_account_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_group_operation(context, **kwargs),
        context=context,
    )


def build_get_account_group_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=AccountGroup, uid=uid)


def build_search_account_groups_operation(
    context: MarketsRepositoryContext,
    *,
    group_name_contains: str | None = None,
    account_model_portfolio_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if account_model_portfolio_uid is not None:
        filters["account_model_portfolio_uid"] = account_model_portfolio_uid
    return build_search_model_operation(
        context,
        model=AccountGroup,
        filters=filters,
        contains_filters={"group_name": group_name_contains or ""},
        limit=limit,
    )


def search_account_groups(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_groups_operation(context, **kwargs),
        context=context,
    )


def build_update_account_group_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    group_name: str | None = None,
    group_description: str | None = None,
    account_model_portfolio_uid: uuid.UUID | str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=AccountGroup,
        uid=uid,
        values={
            "group_name": group_name,
            "group_description": group_description,
            "account_model_portfolio_uid": account_model_portfolio_uid,
            "metadata_json": metadata_json,
        },
    )


def update_account_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_account_group_operation(context, **kwargs),
        context=context,
    )


def build_delete_account_group_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=AccountGroup, uid=uid)


def delete_account_group(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_account_group_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_account_group_operation",
    "build_create_account_model_portfolio_operation",
    "build_delete_account_group_operation",
    "build_get_account_group_by_uid_operation",
    "build_search_account_groups_operation",
    "build_search_account_model_portfolios_operation",
    "build_update_account_group_operation",
    "create_account_group",
    "create_account_model_portfolio",
    "delete_account_group",
    "search_account_groups",
    "search_account_model_portfolios",
    "update_account_group",
]
