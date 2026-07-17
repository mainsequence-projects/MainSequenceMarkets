from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from msm.repositories import MarketsOperationContext


def create_asset(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import create_asset as repository_create_asset

    return repository_create_asset(asset, **kwargs)


def upsert_asset(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import upsert_asset as repository_upsert_asset

    return repository_upsert_asset(asset, **kwargs)


def get_asset_by_uid(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import get_asset_by_uid as repository_get_asset_by_uid

    return repository_get_asset_by_uid(asset, **kwargs)


def get_asset_by_unique_identifier(
    asset: "MarketsOperationContext",
    **kwargs: Any,
) -> dict[str, Any]:
    from msm.repositories.assets import (
        get_asset_by_unique_identifier as repository_get_asset_by_unique_identifier,
    )

    return repository_get_asset_by_unique_identifier(asset, **kwargs)


def search_assets(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import search_assets as repository_search_assets

    return repository_search_assets(asset, **kwargs)


def update_asset(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import update_asset as repository_update_asset

    return repository_update_asset(asset, **kwargs)


def delete_asset(asset: "MarketsOperationContext", **kwargs: Any) -> dict[str, Any]:
    from msm.repositories.assets import delete_asset as repository_delete_asset

    return repository_delete_asset(asset, **kwargs)


def asset_reference_details(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from msm.services.assets.reference_details import asset_reference_details as read_details

    return read_details(*args, **kwargs)


def asset_reference_details_by_uids(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from msm.services.assets.reference_details import (
        asset_reference_details_by_uids as read_details,
    )

    return read_details(*args, **kwargs)


__all__ = [
    "asset_reference_details",
    "asset_reference_details_by_uids",
    "create_asset",
    "delete_asset",
    "get_asset_by_uid",
    "get_asset_by_unique_identifier",
    "search_assets",
    "update_asset",
    "upsert_asset",
]
