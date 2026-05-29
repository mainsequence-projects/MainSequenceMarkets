from __future__ import annotations

import os
from typing import Any

from apps.v1.schemas.assets import AssetCurrentPricingDetailsResponse, AssetListRow
from apps.v1.schemas.common import FrontEndDetailSummary


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


def get_asset_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    summary = _get_asset_frontend_detail_summary(runtime.context, uid=uid)
    if summary is None:
        return None
    return FrontEndDetailSummary.model_validate(summary)


def get_asset_pricing_details(*, uid: str) -> AssetCurrentPricingDetailsResponse | None:
    _ensure_pricing_runtime()
    details = _get_asset_current_pricing_details(uid)
    if details is None:
        return None
    return AssetCurrentPricingDetailsResponse.model_validate(_model_dump(details))


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Asset",
            "OpenFigiAssetDetails",
            "AssetCategory",
            "AssetCategoryMembership",
        ],
        row_model_name="GET /api/v1/asset/",
    )


def _list_asset_catalog_rows(context, **kwargs):
    from msm.services import list_asset_catalog_rows

    return list_asset_catalog_rows(context, **kwargs)


def _get_asset_frontend_detail_summary(context, **kwargs):
    from msm.services import get_asset_frontend_detail_summary

    return get_asset_frontend_detail_summary(context, **kwargs)


def _ensure_pricing_runtime() -> None:
    from apps.v1.runtime_bootstrap import ensure_apps_v1_runtime

    ensure_apps_v1_runtime()
    namespace = os.getenv("MSM_AUTO_REGISTER_NAMESPACE")
    if not namespace:
        return

    from msm_pricing.bootstrap import create_pricing_schemas, resolve_pricing_runtime

    models = ["Asset", "AssetCurrentPricingDetails"]
    try:
        resolve_pricing_runtime(
            models=models,
            row_model_name="GET /api/v1/asset/{uid}/get_pricing_details/",
        )
    except RuntimeError as exc:
        if "requires an initialized pricing runtime" not in str(exc):
            raise
        create_pricing_schemas(
            namespace=namespace,
            models=models,
            seed_default_market_data_bindings=False,
        )


def _get_asset_current_pricing_details(asset_uid: str):
    from msm_pricing.api import AssetCurrentPricingDetails

    return AssetCurrentPricingDetails.get_by_asset_uid(asset_uid)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)
