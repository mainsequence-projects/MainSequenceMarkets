from __future__ import annotations

import datetime as dt
import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext
from msm.repositories import account_allocation_models as allocation_model_repository
from msm.repositories import accounts as account_repository

DEFAULT_ACCOUNT_PAGE_SIZE = 25
DEFAULT_ACCOUNT_SCAN_FLOOR = 100
MAX_ACCOUNT_SCAN_LIMIT = 500
MAX_ACCOUNT_HOLDINGS_SCAN_LIMIT = 500
MAX_ACCOUNT_TARGET_POSITIONS_SCAN_LIMIT = 500


class AccountHoldingsSnapshotExistsError(ValueError):
    """Raised when a holdings snapshot exists and overwrite is disabled."""


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
        _asset_snapshot_references_by_unique_identifier(context, rows=snapshot_rows)
        if include_asset_detail
        else {}
    )
    return _build_account_holdings_snapshot(
        account_uid=resolved_account_uid,
        rows=snapshot_rows,
        asset_references=asset_references,
        include_asset_detail=include_asset_detail,
    )


def add_account_holdings_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    holdings_date: dt.datetime | str,
    positions: Sequence[Mapping[str, Any] | Any],
    overwrite: bool = False,
    include_asset_detail: bool = True,
) -> dict[str, Any] | None:
    account_row = _first_operation_row(get_account_by_uid(context, uid=account_uid))
    if account_row is None:
        return None

    resolved_account_uid = str(account_row["uid"])
    normalized_holdings_date = _required_datetime(holdings_date, field_name="holdings_date")
    normalized_positions = _normalize_add_holdings_positions(
        context,
        positions=positions,
        holdings_date=normalized_holdings_date,
    )
    candidate_holdings_set_uid = str(uuid.uuid4())
    holdings_frame = _build_account_holdings_frame(
        holdings_date=normalized_holdings_date,
        account_uid=resolved_account_uid,
        holdings_set_uid=candidate_holdings_set_uid,
        positions=normalized_positions,
    )
    write_result = account_repository.replace_account_holdings_snapshot(
        context,
        holdings_set_uid=candidate_holdings_set_uid,
        account_uid=resolved_account_uid,
        holdings_date=normalized_holdings_date,
        positions=_account_holdings_frame_operation_rows(holdings_frame),
        overwrite=overwrite,
    )
    if not operation_result_rows(write_result):
        if not overwrite:
            raise AccountHoldingsSnapshotExistsError(
                "Account holdings snapshot already exists for "
                f"account_uid={resolved_account_uid!r} and holdings_date="
                f"{normalized_holdings_date.isoformat()}."
            )
        raise RuntimeError("Account holdings replacement did not insert any rows.")

    return get_account_holdings_snapshot_response(
        context,
        account_uid=resolved_account_uid,
        order="desc",
        limit=1,
        include_asset_detail=include_asset_detail,
        holdings_date=normalized_holdings_date,
    )


def update_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.update_account(context, **kwargs)


def delete_account(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return account_repository.delete_account(context, **kwargs)


def create_account_allocation_model(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return allocation_model_repository.create_account_allocation_model(context, **kwargs)


def search_account_allocation_models(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return allocation_model_repository.search_account_allocation_models(context, **kwargs)


def create_account_target_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.create_account_target_allocation(context, **kwargs)


def search_account_target_allocations(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.search_account_target_allocations(context, **kwargs)


def delete_account_target_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return account_repository.delete_account_target_allocation(context, **kwargs)


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


def _required_string(value: Any, field_name: str) -> str:
    text = _string_or_none(value)
    if text is None:
        raise ValueError(f"{field_name} is required.")
    return text


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
    from msm.data_nodes.accounts.storage import AccountHoldingsStorage
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


def _normalize_add_holdings_positions(
    context: MarketsRepositoryContext,
    *,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_date: dt.datetime,
) -> list[dict[str, Any]]:
    normalized_positions: list[dict[str, Any]] = []
    for position in positions:
        payload = _position_payload(position)
        asset_identifier = _required_string(payload.get("asset_identifier"), "asset_identifier")
        asset_row = _asset_row_by_unique_identifier(context, unique_identifier=asset_identifier)
        if asset_row is None:
            raise ValueError(f"Asset {asset_identifier!r} was not found.")

        asset_uid = _string_or_none(payload.get("asset_uid"))
        if asset_uid is not None and asset_uid != str(asset_row["uid"]):
            raise ValueError(
                f"asset_uid {asset_uid!r} does not match asset "
                f"{asset_identifier!r} uid {asset_row['uid']!s}."
            )

        position_type = _string_or_none(payload.get("position_type")) or "units"
        if position_type != "units":
            raise ValueError("Only position_type='units' is supported for account holdings.")

        target_trade_time = payload.get("target_trade_time")
        normalized_target_trade_time = (
            holdings_date
            if target_trade_time in (None, "")
            else _required_datetime(target_trade_time, field_name="target_trade_time")
        )
        if normalized_target_trade_time != holdings_date:
            raise ValueError("target_trade_time must match holdings_date for add-holdings.")

        normalized_positions.append(
            {
                "asset_identifier": asset_identifier,
                "quantity": payload.get("quantity"),
                "direction": payload.get("direction", 1),
                "target_trade_time": normalized_target_trade_time,
                "extra_details": _mapping_or_empty(payload.get("extra_details")),
            }
        )
    return normalized_positions


def _position_payload(position: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(position, Mapping):
        return dict(position)
    model_dump = getattr(position, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    return {
        key: getattr(position, key)
        for key in (
            "asset_identifier",
            "asset_uid",
            "position_type",
            "quantity",
            "direction",
            "target_trade_time",
            "extra_details",
        )
        if hasattr(position, key)
    }


def _asset_row_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any] | None:
    from msm.services.assets import get_asset_by_unique_identifier

    return _first_operation_row(
        get_asset_by_unique_identifier(
            context,
            unique_identifier=unique_identifier,
        )
    )


def _build_account_holdings_frame(**kwargs: Any):
    from msm.services import build_account_holdings_frame

    return build_account_holdings_frame(**kwargs)


def _account_holdings_frame_operation_rows(frame: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in frame.reset_index().to_dict("records"):
        rows.append(
            {
                "asset_identifier": _required_string(
                    row.get("asset_identifier"),
                    "asset_identifier",
                ),
                "quantity": row.get("quantity"),
                "direction": _int_or_default(row.get("direction"), default=1),
                "target_trade_time": _required_datetime(
                    row.get("target_trade_time"),
                    field_name="target_trade_time",
                ),
                "extra_details": _mapping_or_empty(row.get("extra_details")),
            }
        )
    return rows


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
    holdings = [
        _build_account_holding_row(
            row=row,
            asset_reference=asset_references.get(str(row.get("asset_identifier"))),
            include_asset_detail=include_asset_detail,
        )
        for row in sorted(rows, key=lambda row: str(row.get("asset_identifier", "")).lower())
    ]
    return {
        "holdings_set_uid": _string_or_none(first_row.get("holdings_set_uid")),
        "holdings_date": holdings_date,
        "holdings": holdings,
    }


def _build_account_holding_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    direction = _int_or_default(row.get("direction"), default=1)
    return {
        "time_index": _datetime_or_none(row.get("time_index")),
        "asset_identifier": _string_or_empty(row.get("asset_identifier")),
        "asset": asset_reference if include_asset_detail else None,
        "position_type": "units",
        "price": None,
        "quantity": _number_string_or_none(row.get("quantity")),
        "direction": direction,
        "signed_quantity": _signed_number_string_or_none(row.get("quantity"), direction=direction),
        "missing_price": True,
        "target_trade_time": _datetime_or_none(row.get("target_trade_time")),
        "extra_details": _mapping_or_empty(row.get("extra_details")),
    }


def _empty_account_holdings_snapshot(*, account_uid: str | None) -> dict[str, Any]:
    return {
        "holdings_set_uid": None,
        "holdings_date": None,
        "holdings": [],
    }


def _asset_snapshot_references_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    identifiers = {
        str(row["asset_identifier"])
        for row in rows
        if row.get("asset_identifier") not in (None, "")
    }
    if not identifiers:
        return {}

    from msm.services.assets import asset_reference_details

    details_by_identifier = {
        str(row["asset_identifier"]): row
        for row in asset_reference_details(
            sorted(identifiers),
            repository_context=context,
        )
        if isinstance(row, Mapping) and row.get("asset_identifier") not in (None, "")
    }
    return {
        unique_identifier: _build_asset_snapshot_reference(
            unique_identifier=unique_identifier,
            asset_row=_asset_row_from_reference_detail(
                details_by_identifier.get(unique_identifier)
            ),
            snapshot_row=details_by_identifier.get(unique_identifier),
        )
        for unique_identifier in sorted(identifiers)
    }


def _build_asset_snapshot_reference(
    *,
    unique_identifier: str,
    asset_row: Mapping[str, Any] | None,
    snapshot_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "uid": _string_or_none(asset_row.get("uid")) if asset_row is not None else None,
        "asset_identifier": (
            _string_or_none(asset_row.get("unique_identifier"))
            if asset_row is not None
            else unique_identifier
        )
        or unique_identifier,
        "current_snapshot": {
            "name": (
                _string_or_none(snapshot_row.get("name")) if snapshot_row is not None else None
            ),
            "ticker": (
                _string_or_none(snapshot_row.get("ticker")) if snapshot_row is not None else None
            ),
        },
    }


def _asset_row_from_reference_detail(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "uid": row.get("asset_uid"),
        "unique_identifier": row.get("asset_identifier"),
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


def _required_datetime(value: Any, *, field_name: str) -> dt.datetime:
    try:
        timestamp = _datetime_or_none(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from exc
    if timestamp is None:
        raise ValueError(f"{field_name} is required.")
    return timestamp


def _number_string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def _signed_number_string_or_none(value: Any, *, direction: int) -> str | None:
    raw_value = _number_string_or_none(value)
    if raw_value is None:
        return None
    try:
        return str(Decimal(raw_value) * Decimal(direction))
    except (InvalidOperation, ValueError):
        return raw_value


def _int_or_default(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


__all__ = [
    "AccountHoldingsSnapshotExistsError",
    "add_account_holdings_snapshot_response",
    "create_account",
    "create_account_allocation_model",
    "create_account_target_allocation",
    "create_position_set",
    "delete_account",
    "delete_account_target_allocation",
    "delete_position_set",
    "get_account_by_uid",
    "get_account_frontend_detail_summary",
    "get_account_holdings_snapshot_response",
    "get_account_by_unique_identifier",
    "list_account_rows_response",
    "search_account_allocation_models",
    "search_account_target_allocations",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
