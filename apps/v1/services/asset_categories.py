from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.v1.schemas.asset_categories import (
    AssetCategory,
    AssetCategoryDetailResponse,
    BulkDeleteAssetCategoriesResponse,
)


def list_asset_categories(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[AssetCategory]:
    runtime = _get_runtime()
    rows = _list_asset_category_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [AssetCategory.model_validate(row) for row in rows]


def get_asset_category_detail(*, uid: str) -> AssetCategoryDetailResponse | None:
    runtime = _get_runtime()
    detail = _get_asset_category_frontend_detail(runtime.context, uid=uid)
    if detail is None:
        return None
    return AssetCategoryDetailResponse.model_validate(detail)


def create_asset_category(*, payload: Mapping[str, Any]) -> AssetCategory:
    runtime = _get_runtime()
    record = _create_asset_category_record(runtime.context, **dict(payload))
    return AssetCategory.model_validate(record)


def update_asset_category(*, uid: str, payload: Mapping[str, Any]) -> AssetCategory | None:
    runtime = _get_runtime()
    record = _update_asset_category_record(runtime.context, uid=uid, **dict(payload))
    if record is None:
        return None
    return AssetCategory.model_validate(record)


def delete_asset_category(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_asset_category_record(runtime.context, uid=uid))


def bulk_delete_asset_categories(*, payload: Mapping[str, Any]) -> BulkDeleteAssetCategoriesResponse:
    runtime = _get_runtime()
    result = _bulk_delete_asset_category_records(runtime.context, **dict(payload))
    return BulkDeleteAssetCategoriesResponse.model_validate(result)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Asset",
            "AssetCategory",
            "AssetCategoryMembership",
        ],
        row_model_name="AssetCategory apps/v1",
    )


def _list_asset_category_rows(context, **kwargs):
    from msm.services import list_asset_category_rows

    return list_asset_category_rows(context, **kwargs)


def _get_asset_category_frontend_detail(context, **kwargs):
    from msm.services import get_asset_category_frontend_detail

    return get_asset_category_frontend_detail(context, **kwargs)


def _create_asset_category_record(context, **kwargs):
    from msm.services import create_asset_category_record

    return create_asset_category_record(context, **kwargs)


def _update_asset_category_record(context, **kwargs):
    from msm.services import update_asset_category_record

    return update_asset_category_record(context, **kwargs)


def _delete_asset_category_record(context, **kwargs):
    from msm.services import delete_asset_category_record

    return delete_asset_category_record(context, **kwargs)


def _bulk_delete_asset_category_records(context, **kwargs):
    from msm.services import bulk_delete_asset_category_records

    return bulk_delete_asset_category_records(context, **kwargs)
