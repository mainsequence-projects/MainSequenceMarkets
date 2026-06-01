from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext
from msm.repositories import accounts as account_repository

DEFAULT_ACCOUNT_PAGE_SIZE = 25
DEFAULT_ACCOUNT_SCAN_FLOOR = 100
MAX_ACCOUNT_SCAN_LIMIT = 500
MAX_ACCOUNT_HOLDINGS_SCAN_LIMIT = 500


def create_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.create_account(context, **kwargs)


def get_account_by_unique_identifier(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.get_account_by_unique_identifier(context, **kwargs)


def get_account_by_uid(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.get_account_by_uid(context, **kwargs)


def search_accounts(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.search_accounts(context, **kwargs)


def list_account_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_ACCOUNT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    rows = operation_result_rows(
        search_accounts(
            context,
            limit=_scan_limit(offset=offset, limit=limit),
        )
    )
    normalized_rows = [
        _build_account_row(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(
        key=lambda row: (
            str(row["account_name"]).lower(),
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
                    row["account_name"],
                    row.get("unique_identifier"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return {
        "count": len(normalized_rows),
        "results": normalized_rows[offset : offset + limit],
    }


def get_account_frontend_detail_summary(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    account_row = _first_operation_row(get_account_by_uid(context, uid=uid))
    if account_row is None:
        return None

    account_uid = str(account_row["uid"])
    unique_identifier = _string_or_empty(account_row.get("unique_identifier"))
    display_name = _string_or_empty(account_row.get("account_name"))
    is_paper = bool(account_row.get("is_paper", False))
    account_is_active = bool(account_row.get("account_is_active", False))
    holdings_data_node_uid = _string_or_none(account_row.get("holdings_data_node_uid"))

    return {
        "entity": {
            "id": account_uid,
            "type": "account",
            "title": display_name or unique_identifier or account_uid,
        },
        "badges": [
            {
                "key": "account_is_active",
                "label": "Active" if account_is_active else "Inactive",
                "tone": "success" if account_is_active else "warning",
            },
            {
                "key": "is_paper",
                "label": "Paper" if is_paper else "Live",
                "tone": "neutral" if is_paper else "success",
            },
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": account_uid,
                "kind": "code",
            },
            {
                "key": "unique_identifier",
                "label": "Identifier",
                "value": unique_identifier,
                "kind": "code",
            },
        ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display name",
                "value": display_name,
                "kind": "text",
                "icon": "database",
            }
        ],
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "holdings_data_node_uid": holdings_data_node_uid,
            "metadata_json": _mapping_or_none(account_row.get("metadata_json")),
        },
    }


def get_account_holdings_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | str | None = None,
) -> dict[str, Any] | None:
    account_row = _first_operation_row(get_account_by_uid(context, uid=account_uid))
    if account_row is None:
        return None

    resolved_account_uid = str(account_row["uid"])
    rows = _search_account_holdings_rows(
        context,
        account_uid=resolved_account_uid,
        limit=MAX_ACCOUNT_HOLDINGS_SCAN_LIMIT,
    )
    snapshot_rows = _select_account_holdings_snapshot_rows(
        rows,
        holdings_date=holdings_date,
        order=order,
        limit=limit,
    )
    if not snapshot_rows:
        return _empty_account_holdings_snapshot(account_uid=resolved_account_uid)

    asset_references = (
        _asset_references_by_unique_identifier(context, rows=snapshot_rows)
        if include_asset_detail
        else {}
    )
    return _build_account_holdings_snapshot(
        account_uid=resolved_account_uid,
        rows=snapshot_rows,
        asset_references=asset_references,
        include_asset_detail=include_asset_detail,
    )


def update_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.update_account(context, **kwargs)


def delete_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.delete_account(context, **kwargs)


def create_account_target_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.create_account_target_portfolio(context, **kwargs)


def search_account_target_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.search_account_target_portfolios(context, **kwargs)


def delete_account_target_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.delete_account_target_portfolio(context, **kwargs)


def create_position_set(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.create_position_set(context, **kwargs)


def search_position_sets(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.search_position_sets(context, **kwargs)


def delete_position_set(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.delete_position_set(context, **kwargs)


def _build_account_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": str(row["uid"]),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
        "account_name": _string_or_empty(row.get("account_name")),
        "is_paper": bool(row.get("is_paper", False)),
        "account_is_active": bool(row.get("account_is_active", False)),
        "holdings_data_node_uid": _string_or_none(row.get("holdings_data_node_uid")),
        "metadata_json": _mapping_or_none(row.get("metadata_json")),
    }


def _matches_search(*, values: Sequence[Any], normalized_search: str) -> bool:
    return any(
        normalized_search in str(value).lower() for value in values if value not in (None, "")
    )


def _scan_limit(*, offset: int, limit: int) -> int:
    return min(max(offset + limit, DEFAULT_ACCOUNT_SCAN_FLOOR), MAX_ACCOUNT_SCAN_LIMIT)


def _string_or_empty(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


def _search_account_holdings_rows(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    limit: int,
) -> list[dict[str, Any]]:
    from msm.data_nodes.storage import AccountHoldingsStorage
    from msm.repositories.crud import search_model

    return [
        row
        for row in operation_result_rows(
            search_model(
                context,
                model=AccountHoldingsStorage,
                filters={"account_uid": account_uid},
                limit=limit,
            )
        )
        if isinstance(row, Mapping)
    ]


def _select_account_holdings_snapshot_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    holdings_date: dt.datetime | str | None,
    order: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized_order = order.lower()
    if normalized_order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'.")
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")

    rows_with_time = [
        (dict(row), row_time)
        for row in rows
        if (row_time := _datetime_or_none(row.get("time_index"))) is not None
    ]
    if not rows_with_time:
        return []

    target_time = _datetime_or_none(holdings_date)
    if target_time is not None:
        return [row for row, row_time in rows_with_time if row_time == target_time]

    snapshot_times = sorted(
        {row_time for _, row_time in rows_with_time},
        reverse=normalized_order == "desc",
    )
    selected_time = snapshot_times[0]
    return [row for row, row_time in rows_with_time if row_time == selected_time]


def _build_account_holdings_snapshot(
    *,
    account_uid: str,
    rows: Sequence[Mapping[str, Any]],
    asset_references: Mapping[str, dict[str, Any]],
    include_asset_detail: bool,
) -> dict[str, Any]:
    first_row = rows[0]
    holdings_date = _datetime_or_none(first_row.get("time_index"))
    target_trade_time = _first_non_null_datetime(row.get("target_trade_time") for row in rows)
    holdings = [
        _build_account_holding_row(
            row=row,
            asset_reference=asset_references.get(str(row.get("unique_identifier"))),
            include_asset_detail=include_asset_detail,
        )
        for row in sorted(rows, key=lambda row: str(row.get("unique_identifier", "")).lower())
    ]
    return {
        "id": None,
        "snapshot_uid": None,
        "holdings_set_uid": _string_or_none(first_row.get("holdings_set_uid")),
        "holdings_date": holdings_date,
        "nav": None,
        "related_account_uid": account_uid,
        "is_trade_snapshot": bool(first_row.get("is_trade_snapshot", False)),
        "target_trade_time": target_trade_time,
        "related_expected_asset_exposure_df": [],
        "holdings": holdings,
    }


def _build_account_holding_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    return {
        "time_index": _datetime_or_none(row.get("time_index")),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
        "asset_id": None,
        "asset": asset_reference if include_asset_detail else None,
        "position_type": "units",
        "price": None,
        "quantity": _number_string_or_none(row.get("quantity")),
        "missing_price": True,
        "target_trade_time": _datetime_or_none(row.get("target_trade_time")),
        "extra_details": _mapping_or_empty(row.get("extra_details")),
    }


def _empty_account_holdings_snapshot(*, account_uid: str | None) -> dict[str, Any]:
    return {
        "id": None,
        "snapshot_uid": None,
        "holdings_set_uid": None,
        "holdings_date": None,
        "nav": None,
        "related_account_uid": account_uid,
        "is_trade_snapshot": False,
        "target_trade_time": None,
        "related_expected_asset_exposure_df": [],
        "holdings": [],
    }


def _asset_references_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    identifiers = {
        str(row["unique_identifier"])
        for row in rows
        if row.get("unique_identifier") not in (None, "")
    }
    if not identifiers:
        return {}

    from msm.services.assets import search_assets as service_search_assets
    from msm.services.provider_details import search_openfigi_details as service_search_openfigi

    asset_rows = operation_result_rows(
        service_search_assets(context, limit=MAX_ACCOUNT_HOLDINGS_SCAN_LIMIT)
    )
    detail_rows = operation_result_rows(
        service_search_openfigi(context, limit=MAX_ACCOUNT_HOLDINGS_SCAN_LIMIT)
    )
    details_by_asset_uid = {
        str(row["asset_uid"]): row
        for row in detail_rows
        if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
    }

    references: dict[str, dict[str, Any]] = {}
    for asset_row in asset_rows:
        if not isinstance(asset_row, Mapping):
            continue
        unique_identifier = _string_or_none(asset_row.get("unique_identifier"))
        if unique_identifier not in identifiers:
            continue
        detail_row = details_by_asset_uid.get(str(asset_row.get("uid")))
        references[unique_identifier] = _build_asset_reference(
            asset_row=asset_row,
            detail_row=detail_row,
        )

    for unique_identifier in identifiers.difference(references):
        references[unique_identifier] = _build_asset_reference(
            asset_row=None,
            detail_row=None,
        )
    return references


def _build_asset_reference(
    *,
    asset_row: Mapping[str, Any] | None,
    detail_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "uid": _string_or_none(asset_row.get("uid")) if asset_row is not None else None,
        "figi": _string_or_none(detail_row.get("figi")) if detail_row is not None else None,
        "current_snapshot": {
            "name": _string_or_none(detail_row.get("name")) if detail_row is not None else None,
            "ticker": _string_or_none(detail_row.get("ticker")) if detail_row is not None else None,
        },
    }


def _first_non_null_datetime(values: Iterable[Any]) -> dt.datetime | None:
    for value in values:
        parsed = _datetime_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        timestamp = value
    else:
        raw_value = str(value)
        if raw_value.endswith("Z"):
            raw_value = f"{raw_value[:-1]}+00:00"
        timestamp = dt.datetime.fromisoformat(raw_value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp.replace(tzinfo=dt.UTC)
    return timestamp.astimezone(dt.UTC)


def _number_string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


__all__ = [
    "create_account",
    "create_account_target_portfolio",
    "create_position_set",
    "delete_account",
    "delete_account_target_portfolio",
    "delete_position_set",
    "get_account_by_uid",
    "get_account_frontend_detail_summary",
    "get_account_holdings_snapshot_response",
    "get_account_by_unique_identifier",
    "list_account_rows_response",
    "search_account_target_portfolios",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
