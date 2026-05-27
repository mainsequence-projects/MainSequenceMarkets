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
    from msm.bootstrap import resolve_runtime
    from msm.models import (
        AssetCategoryMembershipTable,
        AssetCategoryTable,
        AssetTable,
        OpenFigiDetailsTable,
    )

    return resolve_runtime(
        models=[
            AssetTable,
            OpenFigiDetailsTable,
            AssetCategoryTable,
            AssetCategoryMembershipTable,
        ],
        row_model_name="GET /api/v1/asset/",
    )


def _list_asset_catalog_rows(context, **kwargs):
    from msm.services import list_asset_catalog_rows

    return list_asset_catalog_rows(context, **kwargs)
