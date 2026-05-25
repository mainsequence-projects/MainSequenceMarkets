from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.provider_details import (
    create_openfigi_details as repository_create_openfigi_details,
    delete_openfigi_details as repository_delete_openfigi_details,
    get_openfigi_details_by_uid as repository_get_openfigi_details_by_uid,
    search_openfigi_details as repository_search_openfigi_details,
    update_openfigi_details as repository_update_openfigi_details,
)


def create_openfigi_details(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_create_openfigi_details(context, **kwargs)


def get_openfigi_details_by_uid(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_get_openfigi_details_by_uid(context, **kwargs)


def search_openfigi_details(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_search_openfigi_details(context, **kwargs)


def update_openfigi_details(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_update_openfigi_details(context, **kwargs)


def delete_openfigi_details(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_delete_openfigi_details(context, **kwargs)


__all__ = [
    "create_openfigi_details",
    "delete_openfigi_details",
    "get_openfigi_details_by_uid",
    "search_openfigi_details",
    "update_openfigi_details",
]
