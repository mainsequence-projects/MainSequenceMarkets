from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.v1.schemas.asset_categories import (
    AssetCategoryDetailResponse,
    AssetCategoryListResponse,
    AssetCategoryRecord,
    BulkDeleteAssetCategoriesResponse,
)


def list_asset_categories(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> AssetCategoryListResponse:
    runtime = _get_runtime()
    payload = _list_asset_category_rows_response(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AssetCategoryListResponse.model_validate(payload)


def get_asset_category_detail(*, uid: str) -> AssetCategoryDetailResponse | None:
    runtime = _get_runtime()
    payload = _get_asset_category_frontend_detail(runtime.context, uid=uid)
    if payload is None:
        return None
    return AssetCategoryDetailResponse.model_validate(payload)


def create_asset_category(*, payload: Mapping[str, Any]) -> AssetCategoryRecord:
    runtime = _get_runtime()
    record = _create_asset_category_record(runtime.context, **dict(payload))
    return AssetCategoryRecord.model_validate(record)


def update_asset_category(*, uid: str, payload: Mapping[str, Any]) -> AssetCategoryRecord | None:
    runtime = _get_runtime()
    record = _update_asset_category_record(runtime.context, uid=uid, **dict(payload))
    if record is None:
        return None
    return AssetCategoryRecord.model_validate(record)


def delete_asset_category(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_asset_category_record(runtime.context, uid=uid))


def bulk_delete_asset_categories(*, payload: Mapping[str, Any]) -> BulkDeleteAssetCategoriesResponse:
    runtime = _get_runtime()
    result = _bulk_delete_asset_category_records(runtime.context, **dict(payload))
    return BulkDeleteAssetCategoriesResponse.model_validate(result)


def _get_runtime():
    from msm.bootstrap import resolve_runtime
    from msm.models import AssetCategoryMembershipTable, AssetCategoryTable, AssetTable

    return resolve_runtime(
        models=[
            AssetTable,
            AssetCategoryTable,
            AssetCategoryMembershipTable,
        ],
        row_model_name="AssetCategory apps/v1",
    )


def _list_asset_category_rows_response(context, **kwargs):
    from msm.services import list_asset_category_rows_response

    return list_asset_category_rows_response(context, **kwargs)


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
