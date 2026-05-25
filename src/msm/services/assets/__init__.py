from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from msm.repositories import MarketsRepositoryContext


def create_asset(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import create_asset as repository_create_asset

    return repository_create_asset(context, **kwargs)


def upsert_asset(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import upsert_asset as repository_upsert_asset

    return repository_upsert_asset(context, **kwargs)


def get_asset_by_uid(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import get_asset_by_uid as repository_get_asset_by_uid

    return repository_get_asset_by_uid(context, **kwargs)


def get_asset_by_unique_identifier(
    context: "MarketsRepositoryContext",
    **kwargs: Any,
) -> dict[str, Any]:
    from msm.repositories.assets import (
        get_asset_by_unique_identifier as repository_get_asset_by_unique_identifier,
    )

    return repository_get_asset_by_unique_identifier(context, **kwargs)


def search_assets(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import search_assets as repository_search_assets

    return repository_search_assets(context, **kwargs)


def update_asset(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import update_asset as repository_update_asset

    return repository_update_asset(context, **kwargs)


def delete_asset(context: "MarketsRepositoryContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import delete_asset as repository_delete_asset

    return repository_delete_asset(context, **kwargs)


__all__ = [
    "create_asset",
    "delete_asset",
    "get_asset_by_uid",
    "get_asset_by_unique_identifier",
    "search_assets",
    "update_asset",
    "upsert_asset",
]
