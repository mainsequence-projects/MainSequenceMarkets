from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.models import OpenFigiAssetDetailsTable

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_openfigi_details_operation(
    context: MarketsRepositoryContext,
    *,
    asset_uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    payload = dict(values)
    payload["asset_uid"] = asset_uid
    return build_create_model_operation(
        context,
        model=OpenFigiAssetDetailsTable,
        values=payload,
    )


def create_openfigi_details(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_openfigi_details_operation(context, **kwargs),
        context=context,
    )


def build_get_openfigi_details_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=OpenFigiAssetDetailsTable, uid=uid)


def get_openfigi_details_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_openfigi_details_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_search_openfigi_details_operation(
    context: MarketsRepositoryContext,
    *,
    asset_uid: uuid.UUID | str | None = None,
    figi: str | None = None,
    ticker: str | None = None,
    ticker_contains: str | None = None,
    isin: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    contains_filters: dict[str, str] = {}
    if asset_uid is not None:
        filters["asset_uid"] = asset_uid
    if figi not in (None, ""):
        filters["figi"] = figi
    if ticker not in (None, ""):
        filters["ticker"] = ticker
    if ticker_contains not in (None, ""):
        contains_filters["ticker"] = ticker_contains
    if isin not in (None, ""):
        filters["isin"] = isin
    return build_search_model_operation(
        context,
        model=OpenFigiAssetDetailsTable,
        filters=filters,
        contains_filters=contains_filters,
        limit=limit,
    )


def search_openfigi_details(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_openfigi_details_operation(context, **kwargs),
        context=context,
    )


def build_update_openfigi_details_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=OpenFigiAssetDetailsTable,
        uid=uid,
        values=values,
    )


def update_openfigi_details(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_openfigi_details_operation(context, **kwargs),
        context=context,
    )


def build_delete_openfigi_details_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=OpenFigiAssetDetailsTable, uid=uid)


def delete_openfigi_details(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_openfigi_details_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_openfigi_details_operation",
    "build_delete_openfigi_details_operation",
    "build_get_openfigi_details_by_uid_operation",
    "build_search_openfigi_details_operation",
    "build_update_openfigi_details_operation",
    "create_openfigi_details",
    "delete_openfigi_details",
    "get_openfigi_details_by_uid",
    "search_openfigi_details",
    "update_openfigi_details",
]
