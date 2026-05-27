from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.v1.schemas.assets import AssetListRow

DEFAULT_SCAN_FLOOR = 100
MAX_SCAN_LIMIT = 500


def list_assets(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[AssetListRow]:
    runtime = _get_runtime()
    context = runtime.context
    scan_limit = min(max(offset + limit, DEFAULT_SCAN_FLOOR), MAX_SCAN_LIMIT)

    asset_rows = _operation_result_rows(
        _search_assets(
            context,
            limit=scan_limit,
        )
    )
    detail_rows = _operation_result_rows(
        _search_openfigi_details(
            context,
            limit=scan_limit,
        )
    )
    details_by_asset_uid = {
        str(row["asset_uid"]): row
        for row in detail_rows
        if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
    }

    merged_rows = [
        _build_asset_list_row(
            asset_row=asset_row,
            detail_row=details_by_asset_uid.get(str(asset_row.get("uid"))),
        )
        for asset_row in asset_rows
    ]
    merged_rows.sort(key=lambda row: (row.unique_identifier.lower(), str(row.uid)))

    normalized_search = search.strip().lower()
    if normalized_search:
        merged_rows = [
            row for row in merged_rows if _matches_search(row=row, normalized_search=normalized_search)
        ]

    return merged_rows[offset : offset + limit]


def _build_asset_list_row(
    *,
    asset_row: Mapping[str, Any],
    detail_row: Mapping[str, Any] | None,
) -> AssetListRow:
    uid = str(asset_row["uid"])
    detail = detail_row or {}
    return AssetListRow(
        id=uid,
        uid=uid,
        unique_identifier=str(asset_row["unique_identifier"]),
        figi=_string_or_none(detail.get("figi")),
        name=_string_or_none(detail.get("name")),
        ticker=_string_or_none(detail.get("ticker")),
        exchange_code=_string_or_none(detail.get("exchange_code")),
        security_market_sector=_string_or_none(detail.get("security_market_sector")),
        security_type=_string_or_none(detail.get("security_type"))
        or _string_or_none(asset_row.get("asset_type")),
        is_custom_by_organization=True,
    )


def _matches_search(*, row: AssetListRow, normalized_search: str) -> bool:
    searchable_values = (
        row.id,
        str(row.uid),
        row.unique_identifier,
        row.figi,
        row.name,
        row.ticker,
        row.exchange_code,
        row.security_market_sector,
        row.security_type,
    )
    return any(
        normalized_search in value.lower()
        for value in searchable_values
        if isinstance(value, str) and value
    )


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    if isinstance(result, Mapping):
        return [dict(result)]
    return []


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _get_runtime():
    from msm.bootstrap import resolve_runtime
    from msm.models import AssetTable, OpenFigiDetailsTable

    return resolve_runtime(
        models=[AssetTable, OpenFigiDetailsTable],
        row_model_name="GET /api/v1/asset/",
    )


def _search_assets(context, **kwargs: Any):
    from msm.services import search_assets

    return search_assets(context, **kwargs)


def _search_openfigi_details(context, **kwargs: Any):
    from msm.services import search_openfigi_details

    return search_openfigi_details(context, **kwargs)
