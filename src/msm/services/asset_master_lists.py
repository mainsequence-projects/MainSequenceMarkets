from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlparse

from mainsequence.meta_tables import slugify_identifier

from msm.models import IndexTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.crud import delete_model, get_model_by_uid, search_model
from msm.services.asset_categories import (
    create_asset_category as service_create_asset_category,
    delete_asset_category as service_delete_asset_category,
    get_asset_category_by_uid as service_get_asset_category_by_uid,
    get_asset_category_by_unique_identifier as service_get_asset_category_by_unique_identifier,
    list_asset_category_memberships as service_list_asset_category_memberships,
    replace_asset_category_memberships as service_replace_asset_category_memberships,
    search_asset_categories as service_search_asset_categories,
    update_asset_category as service_update_asset_category,
)
from msm.services.assets import (
    get_asset_by_uid as service_get_asset_by_uid,
    search_assets as service_search_assets,
)
from msm.services.provider_details import search_openfigi_details as service_search_openfigi_details

DEFAULT_SCAN_FLOOR = 100
MAX_SCAN_LIMIT = 500
DEFAULT_FRONTEND_PAGE_SIZE = 50
_UNSET = object()


def list_index_catalog_rows(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_FRONTEND_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, Any]]:
    scan_limit = _scan_limit(offset=offset, limit=limit)
    index_rows = _operation_result_rows(search_model(context, model=IndexTable, limit=scan_limit))
    normalized_rows = [
        _build_index_list_row(index_row)
        for index_row in index_rows
        if isinstance(index_row, Mapping) and index_row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(
        key=lambda row: (
            str(row["display_name"]).lower(),
            str(row["unique_identifier"]).lower(),
            str(row["uid"]),
        )
    )

    normalized_search = search.strip().lower()
    if normalized_search:
        normalized_rows = [
            row
            for row in normalized_rows
            if _matches_search(
                values=(
                    row["uid"],
                    row["unique_identifier"],
                    row.get("index_type"),
                    row["display_name"],
                    row.get("description"),
                    row.get("provider"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return normalized_rows[offset : offset + limit]


def list_asset_catalog_rows(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_FRONTEND_PAGE_SIZE,
    offset: int = 0,
    category_uid: str | None = None,
) -> list[dict[str, Any]]:
    scan_limit = _scan_limit(offset=offset, limit=limit)
    asset_rows = _operation_result_rows(service_search_assets(context, limit=scan_limit))

    if category_uid not in (None, ""):
        membership_rows = _operation_result_rows(
            service_list_asset_category_memberships(
                context,
                category_uid=category_uid,
                limit=MAX_SCAN_LIMIT,
            )
        )
        allowed_asset_uids = {
            str(row["asset_uid"])
            for row in membership_rows
            if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
        }
        asset_rows = [
            row
            for row in asset_rows
            if isinstance(row, Mapping) and str(row.get("uid")) in allowed_asset_uids
        ]

    detail_rows = _operation_result_rows(
        service_search_openfigi_details(context, limit=MAX_SCAN_LIMIT)
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
        if isinstance(asset_row, Mapping) and asset_row.get("uid") not in (None, "")
    ]
    merged_rows.sort(key=lambda row: (str(row["unique_identifier"]).lower(), str(row["uid"])))

    normalized_search = search.strip().lower()
    if normalized_search:
        merged_rows = [
            row
            for row in merged_rows
            if _matches_search(
                values=(
                    row["uid"],
                    row["unique_identifier"],
                    row.get("figi"),
                    row.get("name"),
                    row.get("ticker"),
                    row.get("exchange_code"),
                    row.get("security_market_sector"),
                    row.get("security_type"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return merged_rows[offset : offset + limit]


def list_asset_rows(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_FRONTEND_PAGE_SIZE,
    offset: int = 0,
    category_uid: str | None = None,
) -> list[dict[str, Any]]:
    scan_limit = _scan_limit(offset=offset, limit=limit)
    asset_rows = _operation_result_rows(service_search_assets(context, limit=scan_limit))

    if category_uid not in (None, ""):
        membership_rows = _operation_result_rows(
            service_list_asset_category_memberships(
                context,
                category_uid=category_uid,
                limit=MAX_SCAN_LIMIT,
            )
        )
        allowed_asset_uids = {
            str(row["asset_uid"])
            for row in membership_rows
            if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
        }
        asset_rows = [
            row
            for row in asset_rows
            if isinstance(row, Mapping) and str(row.get("uid")) in allowed_asset_uids
        ]

    normalized_rows = [
        _build_asset_record(asset_row)
        for asset_row in asset_rows
        if isinstance(asset_row, Mapping) and asset_row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(key=lambda row: (str(row["unique_identifier"]).lower(), str(row["uid"])))

    normalized_search = search.strip().lower()
    if normalized_search:
        normalized_rows = [
            row
            for row in normalized_rows
            if _matches_search(
                values=(
                    row["uid"],
                    row["unique_identifier"],
                    row.get("asset_type"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return normalized_rows[offset : offset + limit]


def get_asset_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    asset_row = _first_operation_row(service_get_asset_by_uid(context, uid=uid))
    if asset_row is None:
        return None
    unique_identifier = _string_or_empty(asset_row.get("unique_identifier"))
    snapshot_row = _latest_asset_snapshot_by_unique_identifier(
        context,
        unique_identifier=unique_identifier,
    )
    return _build_asset_detail_record(
        asset_row=asset_row,
        snapshot_row=snapshot_row,
    )


def get_asset_frontend_detail_summary(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    asset_row = _first_operation_row(service_get_asset_by_uid(context, uid=uid))
    if asset_row is None:
        return None

    detail_row = _first_operation_row(
        service_search_openfigi_details(context, asset_uid=uid, limit=1)
    )
    asset_list_row = _build_asset_list_row(
        asset_row=asset_row,
        detail_row=detail_row,
    )
    asset_uid = str(asset_list_row["uid"])
    unique_identifier = _string_or_empty(asset_list_row.get("unique_identifier"))
    name = _string_or_none(asset_list_row.get("name"))
    ticker = _string_or_none(asset_list_row.get("ticker"))
    exchange_code = _string_or_none(asset_list_row.get("exchange_code"))
    security_market_sector = _string_or_none(asset_list_row.get("security_market_sector"))
    security_type = _string_or_none(asset_list_row.get("security_type"))
    figi = _string_or_none(asset_list_row.get("figi"))
    title = name or ticker or unique_identifier or asset_uid

    badges: list[dict[str, Any]] = []
    if security_type:
        badges.append(
            {
                "key": "security_type",
                "label": security_type,
                "tone": "neutral",
            }
        )
    if security_market_sector:
        badges.append(
            {
                "key": "security_market_sector",
                "label": security_market_sector,
                "tone": "info",
            }
        )

    highlight_fields = [
        {
            "key": "unique_identifier",
            "label": "Identifier",
            "value": unique_identifier,
            "kind": "code",
            "icon": "database",
        }
    ]
    if name:
        highlight_fields.insert(
            0,
            {
                "key": "name",
                "label": "Name",
                "value": name,
                "kind": "text",
                "icon": "database",
            },
        )
    if ticker:
        highlight_fields.append(
            {
                "key": "ticker",
                "label": "Ticker",
                "value": ticker,
                "kind": "code",
                "icon": "tag",
            }
        )

    return {
        "entity": {
            "id": asset_uid,
            "type": "asset",
            "title": title,
        },
        "badges": badges,
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": asset_uid,
                "kind": "code",
            },
            {
                "key": "figi",
                "label": "FIGI",
                "value": figi,
                "kind": "code",
            },
            {
                "key": "exchange_code",
                "label": "Exchange",
                "value": exchange_code,
                "kind": "text",
            },
        ],
        "highlight_fields": highlight_fields,
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "asset_type": _string_or_none(asset_row.get("asset_type")),
            "is_custom_by_organization": bool(
                asset_list_row.get("is_custom_by_organization", True)
            ),
        },
    }


def list_asset_category_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_FRONTEND_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    scan_limit = _scan_limit(offset=offset, limit=limit)
    category_rows = _operation_result_rows(
        service_search_asset_categories(context, limit=scan_limit)
    )
    membership_rows = _operation_result_rows(
        service_list_asset_category_memberships(context, limit=MAX_SCAN_LIMIT)
    )
    membership_counts = Counter(
        str(row["category_uid"])
        for row in membership_rows
        if isinstance(row, Mapping) and row.get("category_uid") not in (None, "")
    )

    normalized_rows = [
        _build_asset_category_list_row(
            category_row=category_row,
            number_of_assets=membership_counts.get(str(category_row.get("uid")), 0),
        )
        for category_row in category_rows
        if isinstance(category_row, Mapping) and category_row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(
        key=lambda row: (
            str(row["display_name"]).lower(),
            str(row["unique_identifier"]).lower(),
            str(row["uid"]),
        )
    )

    normalized_search = search.strip().lower()
    if normalized_search:
        normalized_rows = [
            row
            for row in normalized_rows
            if _matches_search(
                values=(
                    row["uid"],
                    row["unique_identifier"],
                    row["display_name"],
                    row["description"],
                    row["number_of_assets"],
                ),
                normalized_search=normalized_search,
            )
        ]

    total_items = len(normalized_rows)
    return {
        "search": search.strip(),
        "rows": normalized_rows[offset : offset + limit],
        "pagination": _build_frontend_list_pagination(
            total_items=total_items,
            limit=limit,
            offset=offset,
        ),
    }


def list_asset_category_rows(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_FRONTEND_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, Any]]:
    scan_limit = _scan_limit(offset=offset, limit=limit)
    category_rows = _operation_result_rows(
        service_search_asset_categories(context, limit=scan_limit)
    )
    normalized_rows = [
        _build_asset_category_record(category_row)
        for category_row in category_rows
        if isinstance(category_row, Mapping) and category_row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(
        key=lambda row: (
            str(row["display_name"]).lower(),
            str(row["unique_identifier"]).lower(),
            str(row["uid"]),
        )
    )

    normalized_search = search.strip().lower()
    if normalized_search:
        normalized_rows = [
            row
            for row in normalized_rows
            if _matches_search(
                values=(
                    row["uid"],
                    row["unique_identifier"],
                    row["display_name"],
                    row["description"],
                ),
                normalized_search=normalized_search,
            )
        ]

    return normalized_rows[offset : offset + limit]


def get_asset_category_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    category_row = _first_operation_row(service_get_asset_category_by_uid(context, uid=uid))
    if category_row is None:
        return None
    return _build_asset_category_record(category_row)


def get_asset_category_frontend_detail(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    category_row = _first_operation_row(service_get_asset_category_by_uid(context, uid=uid))
    if category_row is None:
        return None

    membership_asset_uids = _category_membership_asset_uids(
        context,
        category_uid=str(category_row["uid"]),
    )
    category_uid = str(category_row["uid"])
    display_name = _string_or_empty(category_row.get("display_name"))
    unique_identifier = _string_or_empty(category_row.get("unique_identifier"))

    return {
        "uid": category_uid,
        "title": display_name or unique_identifier or f"Asset Category {category_uid}",
        "selected_category": {
            "text": display_name,
            "sub_text": unique_identifier,
        },
        "details": [
            {
                "name": "display_name",
                "label": "Display name",
                "value_type": "text",
                "value": display_name,
            },
            {
                "name": "unique_identifier",
                "label": "Identifier",
                "value_type": "text",
                "value": unique_identifier,
            },
            {
                "name": "description",
                "label": "Description",
                "value_type": "text",
                "value": _string_or_empty(category_row.get("description")),
            },
            {
                "name": "number_of_assets",
                "label": "Assets",
                "value_type": "number",
                "value": len(membership_asset_uids),
            },
        ],
        "actions": {
            "can_edit": True,
            "can_delete": True,
            "update_endpoint": f"/api/v1/asset-category/{category_uid}/",
            "delete_endpoint": f"/api/v1/asset-category/{category_uid}/",
        },
        "assets_list": {
            "list_endpoint": "/api/v1/asset/",
            "query_endpoint": "/api/v1/asset/query/",
            "response_format": "frontend_list",
            "default_filters": {
                "categories__uid": category_uid,
            },
        },
    }


def get_index_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    row = _first_operation_row(get_model_by_uid(context, model=IndexTable, uid=uid))
    if row is None:
        return None
    return _build_index_record(row)


def create_asset_category_record(
    context: MarketsRepositoryContext,
    *,
    display_name: str,
    description: str | None = None,
    unique_identifier: str | None = None,
    assets: Sequence[str] | None = None,
) -> dict[str, Any]:
    resolved_unique_identifier = _resolve_asset_category_unique_identifier(
        context,
        display_name=display_name,
        unique_identifier=unique_identifier,
    )
    create_result = service_create_asset_category(
        context,
        unique_identifier=resolved_unique_identifier,
        display_name=display_name.strip(),
        description=_normalize_optional_text(description),
    )
    created_row = _first_operation_row(create_result)
    if created_row is None:
        raise RuntimeError("Asset category creation did not return a category row.")

    asset_uids = _normalize_asset_uid_values(assets)
    if asset_uids is not None:
        service_replace_asset_category_memberships(
            context,
            category_uid=created_row["uid"],
            asset_uids=asset_uids,
        )

    return get_asset_category_record(context, uid=str(created_row["uid"]))


def update_asset_category_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    display_name: str | object = _UNSET,
    description: str | None | object = _UNSET,
    assets: Sequence[str] | None | object = _UNSET,
) -> dict[str, Any] | None:
    existing_row = _first_operation_row(service_get_asset_category_by_uid(context, uid=uid))
    if existing_row is None:
        return None

    update_values: dict[str, Any] = {}
    if display_name is not _UNSET:
        update_values["display_name"] = str(display_name).strip()
    if description is not _UNSET:
        update_values["description"] = _normalize_optional_text(description)

    if update_values:
        service_update_asset_category(
            context,
            uid=uid,
            **update_values,
        )

    if assets is not _UNSET:
        service_replace_asset_category_memberships(
            context,
            category_uid=uid,
            asset_uids=_normalize_asset_uid_values(assets) or [],
        )

    return get_asset_category_record(context, uid=uid)


def delete_asset_category_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    existing_row = _first_operation_row(service_get_asset_category_by_uid(context, uid=uid))
    if existing_row is None:
        return False

    service_delete_asset_category(context, uid=uid)
    return True


def delete_index_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    existing_row = _first_operation_row(get_model_by_uid(context, model=IndexTable, uid=uid))
    if existing_row is None:
        return False

    delete_model(context, model=IndexTable, uid=uid)
    return True


def bulk_delete_asset_category_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str] | None = None,
    select_all: bool = False,
    current_url: str | None = None,
    search: str | None = None,
    display_name: str | None = None,
    display_name_contains: str | None = None,
    unique_identifier: str | None = None,
    unique_identifier_contains: str | None = None,
    description: str | None = None,
    description_contains: str | None = None,
    organization_owner_uid: str | None = None,
) -> dict[str, Any]:
    deletion_filters = _merge_bulk_delete_filters(
        current_url=current_url,
        search=search,
        display_name=display_name,
        display_name_contains=display_name_contains,
        unique_identifier=unique_identifier,
        unique_identifier_contains=unique_identifier_contains,
        description=description,
        description_contains=description_contains,
        organization_owner_uid=organization_owner_uid,
    )

    if deletion_filters["organization_owner_uid"]:
        target_uids: list[str] = []
    elif select_all:
        target_uids = [
            str(row["uid"])
            for row in _filter_asset_category_rows_for_bulk_delete(
                context,
                search=deletion_filters["search"],
                display_name=deletion_filters["display_name"],
                display_name_contains=deletion_filters["display_name_contains"],
                unique_identifier=deletion_filters["unique_identifier"],
                unique_identifier_contains=deletion_filters["unique_identifier_contains"],
                description=deletion_filters["description"],
                description_contains=deletion_filters["description_contains"],
            )
        ]
    else:
        target_uids = [str(uid) for uid in (uids or []) if str(uid).strip()]

    deleted_count = 0
    for target_uid in dict.fromkeys(target_uids):
        if delete_asset_category_record(context, uid=target_uid):
            deleted_count += 1

    detail = (
        "No asset categories matched the deletion request."
        if deleted_count == 0
        else f"Deleted {deleted_count} asset categor{'y' if deleted_count == 1 else 'ies'}."
    )
    return {
        "detail": detail,
        "deleted_count": deleted_count,
    }


def get_asset_category_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any]:
    category_row = _first_operation_row(service_get_asset_category_by_uid(context, uid=uid))
    if category_row is None:
        raise LookupError(f"Asset category {uid!r} was not found.")

    membership_asset_uids = _category_membership_asset_uids(
        context,
        category_uid=str(category_row["uid"]),
    )
    category_uid = str(category_row["uid"])
    return {
        "uid": category_uid,
        "unique_identifier": _string_or_empty(category_row.get("unique_identifier")),
        "display_name": _string_or_empty(category_row.get("display_name")),
        "description": _string_or_empty(category_row.get("description")),
        "assets": membership_asset_uids,
    }


def _build_asset_list_row(
    *,
    asset_row: Mapping[str, Any],
    detail_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    uid = str(asset_row["uid"])
    detail = detail_row or {}
    return {
        "uid": uid,
        "unique_identifier": str(asset_row["unique_identifier"]),
        "figi": _string_or_none(detail.get("figi")),
        "name": _string_or_none(detail.get("name")),
        "ticker": _string_or_none(detail.get("ticker")),
        "exchange_code": _string_or_none(detail.get("exchange_code")),
        "security_market_sector": _string_or_none(detail.get("security_market_sector")),
        "security_type": _string_or_none(detail.get("security_type"))
        or _string_or_none(asset_row.get("asset_type")),
        "is_custom_by_organization": True,
    }


def _build_asset_record(asset_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": str(asset_row["uid"]),
        "unique_identifier": _string_or_empty(asset_row.get("unique_identifier")),
        "asset_type": _string_or_none(asset_row.get("asset_type")),
    }


def _build_asset_detail_record(
    *,
    asset_row: Mapping[str, Any],
    snapshot_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    asset_record = _build_asset_record(asset_row)
    return {
        **asset_record,
        "current_snapshot": _build_asset_current_snapshot(
            unique_identifier=asset_record["unique_identifier"],
            snapshot_row=snapshot_row,
        ),
        "details": [],
        "trading_view": None,
        "order_form": None,
    }


def _build_asset_current_snapshot(
    *,
    unique_identifier: str,
    snapshot_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "time_index": (
            _datetime_or_none(snapshot_row.get("time_index"))
            if snapshot_row is not None
            else None
        ),
        "asset_identifier": (
            _string_or_none(snapshot_row.get("asset_identifier"))
            if snapshot_row is not None
            else _string_or_none(unique_identifier)
        ),
        "name": _string_or_none(snapshot_row.get("name")) if snapshot_row is not None else None,
        "ticker": (
            _string_or_none(snapshot_row.get("ticker")) if snapshot_row is not None else None
        ),
        "exchange_code": (
            _string_or_none(snapshot_row.get("exchange_code"))
            if snapshot_row is not None
            else None
        ),
        "asset_ticker_group_id": (
            _string_or_none(snapshot_row.get("asset_ticker_group_id"))
            if snapshot_row is not None
            else None
        ),
    }


def _latest_asset_snapshot_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any] | None:
    if not unique_identifier:
        return None

    from msm.data_nodes.storage import AssetSnapshotsStorage

    rows = _operation_result_rows(
        search_model(
            context,
            model=AssetSnapshotsStorage,
            filters={"asset_identifier": unique_identifier},
            limit=MAX_SCAN_LIMIT,
        )
    )
    latest_row: dict[str, Any] | None = None
    latest_time: dt.datetime | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        snapshot_time = _datetime_or_none(row.get("time_index"))
        if snapshot_time is None:
            continue
        if latest_time is not None and snapshot_time <= latest_time:
            continue
        latest_row = dict(row)
        latest_time = snapshot_time
    return latest_row


def _build_index_list_row(index_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": str(index_row["uid"]),
        "unique_identifier": _string_or_empty(index_row.get("unique_identifier")),
        "index_type": _string_or_empty(index_row.get("index_type")),
        "display_name": _string_or_empty(index_row.get("display_name")),
        "description": _string_or_none(index_row.get("description")),
        "provider": _string_or_none(index_row.get("provider")),
        "metadata_json": _mapping_or_none(index_row.get("metadata_json")),
    }


def _build_index_record(index_row: Mapping[str, Any]) -> dict[str, Any]:
    return _build_index_list_row(index_row)


def _build_asset_category_list_row(
    *,
    category_row: Mapping[str, Any],
    number_of_assets: int,
) -> dict[str, Any]:
    uid = str(category_row["uid"])
    return {
        "uid": uid,
        "unique_identifier": _string_or_empty(category_row.get("unique_identifier")),
        "display_name": _string_or_empty(category_row.get("display_name")),
        "description": _string_or_empty(category_row.get("description")),
        "number_of_assets": number_of_assets,
    }


def _build_asset_category_record(category_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": str(category_row["uid"]),
        "unique_identifier": _string_or_empty(category_row.get("unique_identifier")),
        "display_name": _string_or_empty(category_row.get("display_name")),
        "description": _string_or_none(category_row.get("description")),
        "metadata_json": _mapping_or_none(category_row.get("metadata_json")),
    }


def _category_membership_asset_uids(
    context: MarketsRepositoryContext,
    *,
    category_uid: str,
) -> list[str]:
    membership_rows = _operation_result_rows(
        service_list_asset_category_memberships(
            context,
            category_uid=category_uid,
            limit=MAX_SCAN_LIMIT,
        )
    )
    return [
        str(row["asset_uid"])
        for row in membership_rows
        if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
    ]


def _filter_asset_category_rows_for_bulk_delete(
    context: MarketsRepositoryContext,
    *,
    search: str | None,
    display_name: str | None,
    display_name_contains: str | None,
    unique_identifier: str | None,
    unique_identifier_contains: str | None,
    description: str | None,
    description_contains: str | None,
) -> list[dict[str, Any]]:
    category_rows = _operation_result_rows(
        service_search_asset_categories(
            context,
            limit=MAX_SCAN_LIMIT,
        )
    )
    membership_rows = _operation_result_rows(
        service_list_asset_category_memberships(context, limit=MAX_SCAN_LIMIT)
    )
    membership_counts = Counter(
        str(row["category_uid"])
        for row in membership_rows
        if isinstance(row, Mapping) and row.get("category_uid") not in (None, "")
    )
    normalized_rows = [
        _build_asset_category_list_row(
            category_row=row,
            number_of_assets=membership_counts.get(str(row.get("uid")), 0),
        )
        for row in category_rows
        if isinstance(row, Mapping) and row.get("uid") not in (None, "")
    ]

    normalized_search = (search or "").strip().lower()
    normalized_display_name = _normalize_exact_string(display_name)
    normalized_display_name_contains = _normalize_contains_string(display_name_contains)
    normalized_unique_identifier = _normalize_exact_string(unique_identifier)
    normalized_unique_identifier_contains = _normalize_contains_string(unique_identifier_contains)
    normalized_description = _normalize_exact_string(description)
    normalized_description_contains = _normalize_contains_string(description_contains)

    def matches(row: Mapping[str, Any]) -> bool:
        if normalized_search and not _matches_search(
            values=(
                row["uid"],
                row["unique_identifier"],
                row["display_name"],
                row["description"],
                row["number_of_assets"],
            ),
            normalized_search=normalized_search,
        ):
            return False
        if (
            normalized_display_name
            and row["display_name"].strip().lower() != normalized_display_name
        ):
            return False
        if (
            normalized_display_name_contains
            and normalized_display_name_contains not in row["display_name"].lower()
        ):
            return False
        if (
            normalized_unique_identifier
            and row["unique_identifier"].strip().lower() != normalized_unique_identifier
        ):
            return False
        if (
            normalized_unique_identifier_contains
            and normalized_unique_identifier_contains not in row["unique_identifier"].lower()
        ):
            return False
        if normalized_description and row["description"].strip().lower() != normalized_description:
            return False
        if (
            normalized_description_contains
            and normalized_description_contains not in row["description"].lower()
        ):
            return False
        return True

    return [row for row in normalized_rows if matches(row)]


def _resolve_asset_category_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    display_name: str,
    unique_identifier: str | None,
) -> str:
    requested_identifier = _normalize_optional_text(unique_identifier)
    if requested_identifier:
        return requested_identifier

    base_identifier = slugify_identifier(display_name.strip()) or "asset_category"
    candidate = base_identifier[:255]
    suffix = 2
    while (
        _first_operation_row(
            service_get_asset_category_by_unique_identifier(
                context,
                unique_identifier=candidate,
            )
        )
        is not None
    ):
        suffix_text = f"_{suffix}"
        candidate = f"{base_identifier[: max(1, 255 - len(suffix_text))]}{suffix_text}"
        suffix += 1
    return candidate


def _merge_bulk_delete_filters(
    *,
    current_url: str | None,
    search: str | None,
    display_name: str | None,
    display_name_contains: str | None,
    unique_identifier: str | None,
    unique_identifier_contains: str | None,
    description: str | None,
    description_contains: str | None,
    organization_owner_uid: str | None,
) -> dict[str, str | None]:
    current_url_filters = _filters_from_current_url(current_url)
    return {
        "search": search if search not in (None, "") else current_url_filters.get("search"),
        "display_name": (
            display_name
            if display_name not in (None, "")
            else current_url_filters.get("display_name")
        ),
        "display_name_contains": (
            display_name_contains
            if display_name_contains not in (None, "")
            else current_url_filters.get("display_name__contains")
        ),
        "unique_identifier": (
            unique_identifier
            if unique_identifier not in (None, "")
            else current_url_filters.get("unique_identifier")
        ),
        "unique_identifier_contains": (
            unique_identifier_contains
            if unique_identifier_contains not in (None, "")
            else current_url_filters.get("unique_identifier__contains")
        ),
        "description": (
            description if description not in (None, "") else current_url_filters.get("description")
        ),
        "description_contains": (
            description_contains
            if description_contains not in (None, "")
            else current_url_filters.get("description__contains")
        ),
        "organization_owner_uid": (
            organization_owner_uid
            if organization_owner_uid not in (None, "")
            else current_url_filters.get("organization_owner__uid")
        ),
    }


def _filters_from_current_url(current_url: str | None) -> dict[str, str]:
    if current_url in (None, ""):
        return {}
    parsed = urlparse(current_url)
    query = parse_qs(parsed.query, keep_blank_values=False)
    return {key: values[-1] for key, values in query.items() if values and values[-1].strip()}


def _build_frontend_list_pagination(
    *,
    total_items: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    safe_page_size = max(1, int(limit))
    safe_offset = max(0, int(offset))
    page = (safe_offset // safe_page_size) + 1
    total_pages = max(1, -(-total_items // safe_page_size))
    has_previous = safe_offset > 0
    has_next = safe_offset + safe_page_size < total_items
    start_index = 0 if total_items == 0 else safe_offset + 1
    end_index = 0 if total_items == 0 else min(total_items, safe_offset + safe_page_size)
    return {
        "page": page,
        "page_size": safe_page_size,
        "total_pages": total_pages,
        "total_items": total_items,
        "has_next": has_next,
        "has_previous": has_previous,
        "start_index": start_index,
        "end_index": end_index,
    }


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, Mapping)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            return [dict(value)]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]

    return [dict(result)]


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = _operation_result_rows(result)
    return rows[0] if rows else None


def _matches_search(*, values: Sequence[Any], normalized_search: str) -> bool:
    return any(
        normalized_search in str(value).lower() for value in values if value not in (None, "")
    )


def _normalize_asset_uid_values(values: Sequence[str] | None | object) -> list[str] | None:
    if values is _UNSET:
        return None
    if values in (None, ""):
        return []
    normalized: list[str] = []
    for value in values:  # type: ignore[union-attr]
        text = str(value).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_optional_text(value: Any) -> str | None:
    if value is _UNSET or value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _normalize_exact_string(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return value.strip().lower() or None


def _normalize_contains_string(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return value.strip().lower() or None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _string_or_empty(value: Any) -> str:
    return _string_or_none(value) or ""


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _scan_limit(*, offset: int, limit: int) -> int:
    return min(max(offset + limit, DEFAULT_SCAN_FLOOR), MAX_SCAN_LIMIT)


__all__ = [
    "bulk_delete_asset_category_records",
    "create_asset_category_record",
    "delete_asset_category_record",
    "get_asset_frontend_detail_summary",
    "delete_index_record",
    "get_asset_category_frontend_detail",
    "get_asset_category_row",
    "get_asset_category_record",
    "get_asset_record",
    "get_index_record",
    "list_asset_catalog_rows",
    "list_asset_rows",
    "list_asset_category_rows",
    "list_asset_category_rows_response",
    "list_index_catalog_rows",
    "update_asset_category_record",
]
