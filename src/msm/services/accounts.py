from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext
from msm.repositories import accounts as account_repository

DEFAULT_ACCOUNT_PAGE_SIZE = 25
DEFAULT_ACCOUNT_SCAN_FLOOR = 100
MAX_ACCOUNT_SCAN_LIMIT = 500


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
        _build_account_list_row(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("uid") not in (None, "")
    ]
    normalized_rows.sort(
        key=lambda row: (
            str(row["display_name"]).lower(),
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
                    row["display_name"],
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


def update_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.update_account(context, **kwargs)


def delete_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.delete_account(context, **kwargs)


def create_account_target_position_assignment(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.create_account_target_position_assignment(context, **kwargs)


def search_account_target_position_assignments(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.search_account_target_position_assignments(context, **kwargs)


def delete_account_target_position_assignment(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.delete_account_target_position_assignment(context, **kwargs)


def _build_account_list_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": str(row["uid"]),
        "display_name": _string_or_empty(row.get("account_name")),
        "is_paper": bool(row.get("is_paper", False)),
        "account_is_active": bool(row.get("account_is_active", False)),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
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


__all__ = [
    "create_account",
    "create_account_target_position_assignment",
    "delete_account",
    "delete_account_target_position_assignment",
    "get_account_by_uid",
    "get_account_frontend_detail_summary",
    "get_account_by_unique_identifier",
    "list_account_rows_response",
    "search_account_target_position_assignments",
    "search_accounts",
    "update_account",
]
