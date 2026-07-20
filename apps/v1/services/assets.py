from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from command_center.widgets.asset_monitor import (
    ASSET_MONITOR_OPERATION_ID,
    build_asset_monitor_frame,
)
from mainsequence.client.command_center.contracts.tabular import TabularFrameResponse

from apps.v1.schemas.assets import Asset, AssetCurrentPricingDetailsResponse, AssetDetailResponse
from apps.v1.schemas.common import FrontEndDetailSummary


def list_assets(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    category_uid: str | None = None,
    unique_identifiers: Sequence[str] | None = None,
) -> list[Asset]:
    runtime = _get_runtime()
    rows = _list_asset_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
        category_uid=category_uid,
        unique_identifiers=unique_identifiers,
    )
    return [Asset.model_validate(row) for row in rows]


def get_asset_monitor_frame(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    asset_type: str | None = None,
    unique_identifiers: Sequence[str] | None = None,
    request_url: str | None = None,
) -> TabularFrameResponse:
    fetch_limit = 500 if asset_type else limit
    fetch_offset = 0 if asset_type else offset
    rows = list_assets(
        search=search,
        limit=fetch_limit,
        offset=fetch_offset,
        unique_identifiers=unique_identifiers,
    )
    if asset_type:
        rows = [row for row in rows if row.asset_type == asset_type][offset : offset + limit]

    source_context: dict[str, Any] = {"operationId": ASSET_MONITOR_OPERATION_ID}
    if unique_identifiers:
        source_context["uniqueIdentifiers"] = list(unique_identifiers)
    if request_url is not None:
        source_context["url"] = request_url

    return build_asset_monitor_frame(
        rows[:limit],
        source={
            "kind": "api",
            "id": ASSET_MONITOR_OPERATION_ID,
            "label": "apps/v1 Asset Monitor",
            "context": source_context,
        },
    )


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


def list_asset_related_meta_tables(
    *,
    uid: str,
    numeric: bool = True,
    timestamped: bool = True,
):
    _get_runtime()
    from msm.api.assets import Asset

    try:
        return Asset.list_related_meta_tables(
            uid,
            numeric=numeric,
            timestamped=timestamped,
        )
    except LookupError:
        return None


def get_asset_pricing_details(*, uid: str) -> AssetCurrentPricingDetailsResponse | None:
    _ensure_pricing_runtime()
    details = _get_asset_current_pricing_details(uid)
    if details is None:
        return None
    payload = _model_dump(details)
    payload["pricing_support"] = _build_asset_pricing_support(
        asset_uid=payload["asset_uid"],
        instrument_type=payload["instrument_type"],
    )
    return AssetCurrentPricingDetailsResponse.model_validate(payload)


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


def _build_asset_pricing_support(*, asset_uid: str, instrument_type: str):
    from msm_pricing.api import build_asset_pricing_support

    return build_asset_pricing_support(
        asset_uid=asset_uid,
        instrument_type=instrument_type,
    )


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)
