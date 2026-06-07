from __future__ import annotations

from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import AccountAllocationModelTable

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_search_model_operation,
)


def build_create_account_allocation_model_operation(
    context: MarketsRepositoryContext,
    *,
    allocation_model_name: str,
    allocation_model_description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountAllocationModelTable,
        values={
            "allocation_model_name": allocation_model_name,
            "allocation_model_description": allocation_model_description,
            "metadata_json": metadata_json,
        },
    )


def create_account_allocation_model(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_allocation_model_operation(context, **kwargs),
        context=context,
    )


def build_search_account_allocation_models_operation(
    context: MarketsRepositoryContext,
    *,
    allocation_model_name_contains: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    return build_search_model_operation(
        context,
        model=AccountAllocationModelTable,
        contains_filters={
            "allocation_model_name": allocation_model_name_contains or "",
        },
        limit=limit,
    )


def search_account_allocation_models(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_allocation_models_operation(context, **kwargs),
        context=context,
    )


__all__ = [
    "build_create_account_allocation_model_operation",
    "build_search_account_allocation_models_operation",
    "create_account_allocation_model",
    "search_account_allocation_models",
]
