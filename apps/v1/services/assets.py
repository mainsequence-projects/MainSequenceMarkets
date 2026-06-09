from __future__ import annotations

from typing import Any

from apps.v1.schemas.assets import Asset, AssetCurrentPricingDetailsResponse, AssetDetailResponse
from apps.v1.schemas.common import FrontEndDetailSummary


def list_assets(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    category_uid: str | None = None,
) -> list[Asset]:
    runtime = _get_runtime()
    rows = _list_asset_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
        category_uid=category_uid,
    )
    return [Asset.model_validate(row) for row in rows]


def get_asset(*, uid: str) -> AssetDetailResponse | None:
    runtime = _get_runtime()
    record = _get_asset_record(runtime.context, uid=uid)
    if record is None:
        return None
    return AssetDetailResponse.model_validate(record)


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


def delete_asset(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_asset_record(runtime.context, uid=uid))


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "Asset",
            "OpenFigiAssetDetails",
            "AssetCategory",
            "AssetCategoryMembership",
            "AssetSnapshotsStorage",
        ],
        row_model_name="GET /api/v1/asset/",
    )


def _list_asset_rows(context, **kwargs):
    from msm.services import list_asset_rows

    return list_asset_rows(context, **kwargs)


def _get_asset_record(context, **kwargs):
    from msm.services import get_asset_record

    return get_asset_record(context, **kwargs)


def _get_asset_frontend_detail_summary(context, **kwargs):
    from msm.services import get_asset_frontend_detail_summary

    return get_asset_frontend_detail_summary(context, **kwargs)


def _delete_asset_record(context, **kwargs):
    from msm.services import delete_asset_record

    return delete_asset_record(context, **kwargs)


def _ensure_pricing_runtime() -> None:
    from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime

    ensure_apps_v1_pricing_runtime()


def _get_asset_current_pricing_details(asset_uid: str):
    from msm_pricing.api import AssetCurrentPricingDetails

    return AssetCurrentPricingDetails.get_by_asset_uid(asset_uid)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)
