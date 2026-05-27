from __future__ import annotations

from apps.v1.schemas.assets import AssetListRow


def list_assets(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    category_uid: str | None = None,
) -> list[AssetListRow]:
    runtime = _get_runtime()
    rows = _list_asset_catalog_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
        category_uid=category_uid,
    )
    return [AssetListRow.model_validate(row) for row in rows]


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Asset",
            "OpenFigiDetails",
            "AssetCategory",
            "AssetCategoryMembership",
        ],
        row_model_name="GET /api/v1/asset/",
    )


def _list_asset_catalog_rows(context, **kwargs):
    from msm.services import list_asset_catalog_rows

    return list_asset_catalog_rows(context, **kwargs)
