from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import pandas as pd

from mainsequence.client import dtype_codec as dc
from msm.api.base import operation_result_rows
from msm.data_nodes.accounts.constants import (
    TARGET_TYPE_ASSET,
    TARGET_TYPE_PORTFOLIO,
)
from msm.data_nodes.accounts.storage import TargetPositionsStorage
from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
)
from msm.repositories import MarketsRepositoryContext
from msm.repositories.crud import search_model
from msm.services.accounts import (
    get_account_by_uid,
    search_account_target_allocations,
    search_position_sets,
)
from msm.services.assets import asset_reference_details_by_uids
from msm.services.portfolios import search_portfolios

TARGET_POSITION_EXPOSURE_FIELDS = (
    "weight_notional_exposure",
    "constant_notional_exposure",
    "single_asset_quantity",
)

DEFAULT_TARGET_POSITION_SCAN_LIMIT = 500
PortfolioWeightResolver = Callable[[str], Sequence[Mapping[str, Any]] | pd.DataFrame]


class AccountTargetPositionsSnapshotExistsError(ValueError):
    """Raised when a target-position snapshot exists and overwrite is disabled."""


def validate_target_position_payload(position: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(position)
    if "asset_identifier" in payload:
        raise ValueError("Target positions use asset_uid or portfolio_uid, not asset_identifier.")

    provided_fields = [
        field_name
        for field_name in TARGET_POSITION_EXPOSURE_FIELDS
        if not _is_missing(payload.get(field_name))
    ]
    if len(provided_fields) != 1:
        raise ValueError(
            "Each target position must provide exactly one of "
            "`weight_notional_exposure`, `constant_notional_exposure`, "
            "or `single_asset_quantity`."
        )

    asset_uid = _optional_uuid_string(payload.get("asset_uid"), field_name="asset_uid")
    portfolio_uid = _optional_uuid_string(payload.get("portfolio_uid"), field_name="portfolio_uid")
    if (asset_uid is None) == (portfolio_uid is None):
        raise ValueError(
            "Each target position must provide exactly one of asset_uid or portfolio_uid."
        )

    target_type = TARGET_TYPE_ASSET if asset_uid is not None else TARGET_TYPE_PORTFOLIO
    if target_type == TARGET_TYPE_PORTFOLIO and not _is_missing(
        payload.get("single_asset_quantity")
    ):
        raise ValueError("Portfolio target positions cannot use single_asset_quantity.")

    target_uid = asset_uid or portfolio_uid
    declared_target_type = payload.get("target_type")
    if declared_target_type not in (None, "") and str(declared_target_type) != target_type:
        raise ValueError("target_type must match the concrete target UID field.")

    declared_target_uid = payload.get("target_uid")
    if declared_target_uid not in (None, ""):
        normalized_declared_target_uid = _required_uuid_string(
            declared_target_uid,
            field_name="target_uid",
        )
        if normalized_declared_target_uid != target_uid:
            raise ValueError("target_uid must match asset_uid or portfolio_uid.")

    payload["target_type"] = target_type
    payload["target_uid"] = target_uid
    payload["asset_uid"] = asset_uid
    payload["portfolio_uid"] = portfolio_uid
    payload["metadata_json"] = _mapping_or_empty(payload.get("metadata_json"))
    return payload


def build_target_positions_frame(
    *,
    target_positions_date: dt.datetime | str,
    position_set_uid: UUID | str,
    positions: Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    if not positions:
        raise ValueError("At least one target position is required.")

    position_set_uid_string = _required_uuid_string(
        position_set_uid,
        field_name="position_set_uid",
    )
    rows = []
    for position in positions:
        payload = validate_target_position_payload(position)
        rows.append(
            {
                "time_index": target_positions_date,
                "position_set_uid": position_set_uid_string,
                "target_type": payload["target_type"],
                "target_uid": payload["target_uid"],
                "asset_uid": payload["asset_uid"],
                "portfolio_uid": payload["portfolio_uid"],
                "weight_notional_exposure": payload.get("weight_notional_exposure"),
                "constant_notional_exposure": payload.get("constant_notional_exposure"),
                "single_asset_quantity": payload.get("single_asset_quantity"),
                "metadata_json": payload.get("metadata_json") or {},
            }
        )
    return validate_target_positions_frame(pd.DataFrame(rows))


def validate_target_positions_frame(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    index_names = list(TargetPositionsStorage.__index_names__)
    if list(frame.index.names) != index_names:
        if all(index_name in frame.columns for index_name in index_names):
            frame = frame.set_index(index_names)
        else:
            raise ValueError(
                "Target positions frame must use index_names "
                f"{index_names} or include those columns before validation."
            )

    flat = frame.reset_index()
    column_dtypes_map = storage_column_dtypes_map(TargetPositionsStorage)
    column_nullable_map = storage_column_nullable_map(TargetPositionsStorage)
    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Target positions frame is missing required columns: {', '.join(missing_columns)}."
        )

    for column_name, dtype in column_dtypes_map.items():
        values = flat[column_name]
        if column_name == TargetPositionsStorage.__time_index_name__:
            flat[column_name] = pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]")
        elif dtype == dc.UUID_TOKEN:
            flat[column_name] = _normalize_uuid_column(
                values,
                nullable=column_nullable_map[column_name],
                field_name=column_name,
            )
        elif dtype == dc.STRING:
            flat[column_name] = values.map(_required_string)
        elif dtype == dc.FLOAT64:
            flat[column_name] = _normalize_float64_column(
                values,
                nullable=column_nullable_map[column_name],
            )
        elif dtype == dc.JSONB:
            flat[column_name] = values.map(_normalize_jsonb)
        else:
            raise ValueError(f"Unsupported target-position dtype {dtype!r} for {column_name!r}.")

    for row in flat.to_dict("records"):
        validate_target_position_payload(row)

    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"Target positions frame contains duplicate rows for index names {index_names}."
        )
    return frame


def expand_portfolio_target_positions(
    target_positions: pd.DataFrame | Sequence[Mapping[str, Any]],
    *,
    portfolio_weight_resolver: PortfolioWeightResolver | None = None,
) -> pd.DataFrame:
    frame = validate_target_positions_frame(_target_positions_to_frame(target_positions))
    flat = frame.reset_index()
    rows: list[dict[str, Any]] = []
    for row in flat.to_dict("records"):
        if row["target_type"] == TARGET_TYPE_ASSET:
            rows.append(
                {
                    **_exposure_columns(row),
                    "source_target_type": TARGET_TYPE_ASSET,
                    "source_target_uid": row["target_uid"],
                    "asset_uid": row["asset_uid"],
                    "portfolio_uid": None,
                    "portfolio_weight": None,
                }
            )
            continue

        if portfolio_weight_resolver is None:
            raise ValueError(
                "Portfolio target expansion requires an explicit portfolio_weight_resolver."
            )
        for weight_row in _portfolio_weight_rows(
            portfolio_weight_resolver(str(row["portfolio_uid"]))
        ):
            rows.append(
                {
                    **_expanded_exposure_columns(row, weight_row),
                    "source_target_type": TARGET_TYPE_PORTFOLIO,
                    "source_target_uid": row["target_uid"],
                    "asset_uid": _required_uuid_string(
                        weight_row.get("asset_uid"),
                        field_name="asset_uid",
                    ),
                    "portfolio_uid": row["portfolio_uid"],
                    "portfolio_weight": float(weight_row.get("weight") or 0.0),
                }
            )
    return pd.DataFrame(rows)


def get_account_target_positions_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    target_positions_date: dt.datetime | str | None = None,
) -> dict[str, Any] | None:
    account_row = _first_operation_row(get_account_by_uid(context, uid=account_uid))
    if account_row is None:
        return None

    resolved_account_uid = str(account_row["uid"])
    target_allocation_rows = _search_active_account_target_allocation_rows(
        context,
        account_uid=resolved_account_uid,
    )
    if not target_allocation_rows:
        return _empty_account_target_positions_snapshot(account_uid=resolved_account_uid)

    position_set_rows = _search_position_set_rows_for_target_allocations(
        context,
        target_allocation_uids=[
            str(row["uid"]) for row in target_allocation_rows if row.get("uid") not in (None, "")
        ],
        position_set_time=target_positions_date,
    )
    position_set_row = _select_account_position_set_row(
        position_set_rows,
        target_positions_date=target_positions_date,
        order=order,
        limit=limit,
    )
    if position_set_row is None:
        return _empty_account_target_positions_snapshot(account_uid=resolved_account_uid)

    position_set_uid = _string_or_none(position_set_row.get("uid"))
    if position_set_uid is None:
        return _empty_account_target_positions_snapshot(account_uid=resolved_account_uid)

    snapshot_time = _datetime_or_none(position_set_row.get("position_set_time"))
    position_rows = _search_target_position_rows(
        context,
        position_set_uid=position_set_uid,
        target_positions_date=snapshot_time,
        limit=DEFAULT_TARGET_POSITION_SCAN_LIMIT,
    )
    asset_references = (
        _asset_references_by_uid(context, rows=position_rows) if include_asset_detail else {}
    )
    portfolio_references = _portfolio_references_by_uid(context, rows=position_rows)
    return _build_account_target_positions_snapshot(
        account_uid=resolved_account_uid,
        position_set_row=position_set_row,
        rows=position_rows,
        asset_references=asset_references,
        portfolio_references=portfolio_references,
        include_asset_detail=include_asset_detail,
    )


def add_account_target_positions_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    target_positions_date: dt.datetime | str,
    positions: Sequence[Mapping[str, Any] | Any],
    overwrite: bool = False,
    include_asset_detail: bool = True,
) -> dict[str, Any] | None:
    account_row = _first_operation_row(get_account_by_uid(context, uid=account_uid))
    if account_row is None:
        return None

    resolved_account_uid = _required_uuid_string(account_row["uid"], field_name="account_uid")
    account_name = _string_or_empty(account_row.get("account_name")) or resolved_account_uid
    normalized_target_positions_date = _required_datetime(
        target_positions_date,
        field_name="target_positions_date",
    )
    position_payloads = [_position_payload(position) for position in positions]
    candidate_position_set_uid = str(uuid4())
    target_positions_frame = build_target_positions_frame(
        target_positions_date=normalized_target_positions_date,
        position_set_uid=candidate_position_set_uid,
        positions=position_payloads,
    )

    from msm.repositories.accounts import replace_account_target_positions_snapshot

    write_result = replace_account_target_positions_snapshot(
        context,
        account_allocation_model_uid=str(uuid4()),
        account_target_allocation_uid=str(uuid4()),
        position_set_uid=candidate_position_set_uid,
        account_uid=resolved_account_uid,
        account_name=account_name,
        target_positions_date=normalized_target_positions_date,
        positions=_target_positions_frame_operation_rows(target_positions_frame),
        overwrite=overwrite,
    )
    if not operation_result_rows(write_result):
        if not overwrite:
            raise AccountTargetPositionsSnapshotExistsError(
                "Account target-position snapshot already exists for "
                f"account_uid={resolved_account_uid!r} and target_positions_date="
                f"{normalized_target_positions_date.isoformat()}."
            )
        raise RuntimeError("Account target-position replacement did not insert any rows.")

    return get_account_target_positions_snapshot_response(
        context,
        account_uid=resolved_account_uid,
        order="desc",
        limit=1,
        include_asset_detail=include_asset_detail,
        target_positions_date=normalized_target_positions_date,
    )


def search_account_target_allocation_candidates(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    target_type: str = "all",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Return asset and portfolio rows that can be assigned as target positions."""

    normalized_target_type = target_type.strip().lower()
    if normalized_target_type not in {"all", TARGET_TYPE_ASSET, TARGET_TYPE_PORTFOLIO}:
        raise ValueError("target_type must be one of: all, asset, portfolio.")
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")

    from msm.repositories.accounts import (
        search_account_target_allocation_candidates as repository_search_candidates,
    )

    operation_rows = operation_result_rows(
        repository_search_candidates(
            context,
            search=search,
            target_type=normalized_target_type,
            limit=limit,
            offset=offset,
        )
    )
    count = 0
    candidates: list[dict[str, Any]] = []
    for row in operation_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("row_kind") == "__count__":
            count = _int_or_zero(row.get("total_count"))
            continue
        if row.get("row_kind") == "data":
            candidates.append(_build_account_target_allocation_candidate(row))
    return {"count": count, "results": candidates}


def _target_positions_to_frame(
    target_positions: pd.DataFrame | Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    if isinstance(target_positions, pd.DataFrame):
        return target_positions
    return pd.DataFrame([dict(row) for row in target_positions])


def _portfolio_weight_rows(
    value: Sequence[Mapping[str, Any]] | pd.DataFrame,
) -> list[dict[str, Any]]:
    frame = value.reset_index() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
    required = {"asset_uid", "weight"}
    missing = [column for column in sorted(required) if column not in frame.columns]
    if missing:
        raise ValueError(
            "Portfolio weight rows are missing required columns: " + ", ".join(missing)
        )
    return [dict(row) for row in frame.to_dict("records")]


def _exposure_columns(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "weight_notional_exposure": row.get("weight_notional_exposure"),
        "constant_notional_exposure": row.get("constant_notional_exposure"),
        "single_asset_quantity": row.get("single_asset_quantity"),
    }


def _expanded_exposure_columns(
    target_row: Mapping[str, Any],
    weight_row: Mapping[str, Any],
) -> dict[str, Any]:
    portfolio_weight = float(weight_row.get("weight") or 0.0)
    exposure = _exposure_columns(target_row)
    if exposure["weight_notional_exposure"] is not None:
        exposure["weight_notional_exposure"] = (
            float(exposure["weight_notional_exposure"]) * portfolio_weight
        )
    if exposure["constant_notional_exposure"] is not None:
        exposure["constant_notional_exposure"] = (
            float(exposure["constant_notional_exposure"]) * portfolio_weight
        )
    return exposure


def _search_active_account_target_allocation_rows(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in operation_result_rows(
            search_account_target_allocations(
                context,
                account_uid=account_uid,
                is_active=True,
                limit=DEFAULT_TARGET_POSITION_SCAN_LIMIT,
            )
        )
        if isinstance(row, Mapping)
    ]


def _search_position_set_rows_for_target_allocations(
    context: MarketsRepositoryContext,
    *,
    target_allocation_uids: Sequence[str],
    position_set_time: dt.datetime | str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target_allocation_uid in target_allocation_uids:
        rows.extend(
            row
            for row in operation_result_rows(
                search_position_sets(
                    context,
                    account_target_allocation_uid=target_allocation_uid,
                    position_set_time=position_set_time,
                    limit=DEFAULT_TARGET_POSITION_SCAN_LIMIT,
                )
            )
            if isinstance(row, Mapping)
        )
    return rows


def _select_account_position_set_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_positions_date: dt.datetime | str | None,
    order: str,
    limit: int,
) -> dict[str, Any] | None:
    normalized_order = order.lower()
    if normalized_order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'.")
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")

    rows_with_time = [
        (dict(row), position_set_time)
        for row in rows
        if (position_set_time := _datetime_or_none(row.get("position_set_time"))) is not None
    ]
    if not rows_with_time:
        return None

    target_time = _datetime_or_none(target_positions_date)
    if target_time is not None:
        exact_rows = [row for row, row_time in rows_with_time if row_time == target_time]
        if not exact_rows:
            return None
        return sorted(exact_rows, key=lambda row: str(row.get("uid", "")))[0]

    ordered_rows = sorted(
        rows_with_time,
        key=lambda item: (item[1], str(item[0].get("uid", ""))),
        reverse=normalized_order == "desc",
    )
    return ordered_rows[0][0]


def _search_target_position_rows(
    context: MarketsRepositoryContext,
    *,
    position_set_uid: str,
    target_positions_date: dt.datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [
        row
        for row in operation_result_rows(
            search_model(
                context,
                model=TargetPositionsStorage,
                filters={"position_set_uid": position_set_uid},
                limit=limit,
            )
        )
        if isinstance(row, Mapping)
    ]
    if target_positions_date is None:
        return rows
    return [
        row for row in rows if _datetime_or_none(row.get("time_index")) == target_positions_date
    ]


def _build_account_target_positions_snapshot(
    *,
    account_uid: str,
    position_set_row: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    asset_references: Mapping[str, dict[str, Any]],
    portfolio_references: Mapping[str, dict[str, Any]],
    include_asset_detail: bool,
) -> dict[str, Any]:
    positions = [
        _build_account_target_position_row(
            row=row,
            asset_reference=asset_references.get(str(row.get("asset_uid"))),
            portfolio_reference=portfolio_references.get(str(row.get("portfolio_uid"))),
            include_asset_detail=include_asset_detail,
        )
        for row in sorted(rows, key=_target_position_sort_key)
    ]
    return {
        "related_account_uid": account_uid,
        "target_positions_date": _datetime_or_none(position_set_row.get("position_set_time")),
        "position_set_uid": _string_or_none(position_set_row.get("uid")),
        "positions": positions,
    }


def _target_position_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("target_type", "")), str(row.get("target_uid", "")))


def _build_account_target_position_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    portfolio_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    target_type = _required_string(row.get("target_type"))
    target_uid = _string_or_empty(row.get("target_uid"))
    return {
        "target_type": target_type,
        "target_uid": target_uid,
        "asset_uid": _string_or_none(row.get("asset_uid")),
        "portfolio_uid": _string_or_none(row.get("portfolio_uid")),
        "unique_identifier": _target_unique_identifier(
            target_type=target_type,
            target_uid=target_uid,
            asset_reference=asset_reference,
            portfolio_reference=portfolio_reference,
        ),
        "weight_notional_exposure": _number_string_or_none(row.get("weight_notional_exposure")),
        "constant_notional_exposure": _number_string_or_none(row.get("constant_notional_exposure")),
        "single_asset_quantity": _number_string_or_none(row.get("single_asset_quantity")),
        "asset": asset_reference if include_asset_detail else None,
        "portfolio": portfolio_reference,
    }


def _target_unique_identifier(
    *,
    target_type: str,
    target_uid: str,
    asset_reference: Mapping[str, Any] | None,
    portfolio_reference: Mapping[str, Any] | None,
) -> str:
    if target_type == TARGET_TYPE_ASSET and asset_reference is not None:
        return _string_or_empty(asset_reference.get("unique_identifier")) or target_uid
    if target_type == TARGET_TYPE_PORTFOLIO and portfolio_reference is not None:
        return _string_or_empty(portfolio_reference.get("unique_identifier")) or target_uid
    return target_uid


def _empty_account_target_positions_snapshot(*, account_uid: str | None) -> dict[str, Any]:
    return {
        "related_account_uid": account_uid,
        "target_positions_date": None,
        "position_set_uid": None,
        "positions": [],
    }


def _asset_references_by_uid(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    asset_uids = {str(row["asset_uid"]) for row in rows if row.get("asset_uid") not in (None, "")}
    if not asset_uids:
        return {}

    details_by_uid = {
        str(row["asset_uid"]): row
        for row in asset_reference_details_by_uids(
            sorted(asset_uids),
            repository_context=context,
        )
        if isinstance(row, Mapping) and row.get("asset_uid") not in (None, "")
    }
    return {
        uid: _build_asset_snapshot_reference(
            asset_row=_asset_row_from_reference_detail(details_by_uid.get(uid)),
            snapshot_row=details_by_uid.get(uid),
        )
        for uid in sorted(asset_uids)
    }


def _portfolio_references_by_uid(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    portfolio_uids = {
        str(row["portfolio_uid"]) for row in rows if row.get("portfolio_uid") not in (None, "")
    }
    if not portfolio_uids:
        return {}
    portfolio_rows = operation_result_rows(
        search_portfolios(context, limit=DEFAULT_TARGET_POSITION_SCAN_LIMIT)
    )
    references: dict[str, dict[str, Any]] = {}
    for row in portfolio_rows:
        if not isinstance(row, Mapping):
            continue
        portfolio_uid = _string_or_none(row.get("uid"))
        if portfolio_uid not in portfolio_uids:
            continue
        references[portfolio_uid] = {
            "uid": portfolio_uid,
            "unique_identifier": _string_or_empty(row.get("unique_identifier")),
            "published_index_uid": _string_or_none(row.get("published_index_uid")),
        }
    return references


def _build_asset_snapshot_reference(
    *,
    asset_row: Mapping[str, Any] | None,
    snapshot_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "uid": _string_or_none(asset_row.get("uid")) if asset_row is not None else None,
        "unique_identifier": (
            _string_or_none(asset_row.get("unique_identifier")) if asset_row is not None else None
        ),
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


def _build_account_target_allocation_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    target_type = _required_string(row.get("target_type"))
    metadata = (
        {"asset_type": _string_or_none(row.get("asset_type"))}
        if target_type == TARGET_TYPE_ASSET
        else {"published_index_uid": _string_or_none(row.get("published_index_uid"))}
    )
    current_snapshot = None
    if target_type == TARGET_TYPE_ASSET:
        current_snapshot = {
            "name": _string_or_none(row.get("snapshot_name")),
            "ticker": _string_or_none(row.get("snapshot_ticker")),
        }
    return {
        "target_type": target_type,
        "target_uid": _string_or_empty(row.get("target_uid")),
        "asset_uid": _string_or_none(row.get("asset_uid")),
        "portfolio_uid": _string_or_none(row.get("portfolio_uid")),
        "identifier": _string_or_empty(row.get("identifier")),
        "display_label": _string_or_empty(row.get("display_label"))
        or _string_or_empty(row.get("identifier")),
        "secondary_label": _string_or_none(row.get("secondary_label")),
        "current_snapshot": current_snapshot,
        "metadata": metadata,
    }


def _position_payload(position: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(position, Mapping):
        return dict(position)
    model_dump = getattr(position, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    return {
        key: getattr(position, key)
        for key in (
            "target_type",
            "target_uid",
            "asset_uid",
            "portfolio_uid",
            "weight_notional_exposure",
            "constant_notional_exposure",
            "single_asset_quantity",
            "metadata_json",
        )
        if hasattr(position, key)
    }


def _target_positions_frame_operation_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "target_type": _required_string(row.get("target_type")),
            "target_uid": _required_uuid_string(row.get("target_uid"), field_name="target_uid"),
            "asset_uid": _optional_uuid_string(row.get("asset_uid"), field_name="asset_uid"),
            "portfolio_uid": _optional_uuid_string(
                row.get("portfolio_uid"),
                field_name="portfolio_uid",
            ),
            "weight_notional_exposure": _none_if_missing(row.get("weight_notional_exposure")),
            "constant_notional_exposure": _none_if_missing(row.get("constant_notional_exposure")),
            "single_asset_quantity": _none_if_missing(row.get("single_asset_quantity")),
            "metadata_json": _mapping_or_empty(row.get("metadata_json")),
        }
        for row in frame.reset_index().to_dict("records")
    ]


def _normalize_uuid_column(values: pd.Series, *, nullable: bool, field_name: str) -> pd.Series:
    return values.map(
        lambda value: (
            _optional_uuid_string(value, field_name=field_name)
            if nullable
            else _required_uuid_string(value, field_name=field_name)
        )
    )


def _optional_uuid_string(value: Any, *, field_name: str) -> str | None:
    if _is_missing(value):
        return None
    return _required_uuid_string(value, field_name=field_name)


def _required_uuid_string(value: Any, *, field_name: str) -> str:
    if _is_missing(value):
        raise ValueError(f"{field_name} is required.")
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID.") from exc


def _normalize_float64_column(values: pd.Series, *, nullable: bool) -> pd.Series:
    normalized = values.map(lambda value: _normalize_optional_float64(value, nullable=nullable))
    return pd.to_numeric(normalized, errors="raise").astype("float64")


def _normalize_optional_float64(value: Any, *, nullable: bool) -> float | None:
    if _is_missing(value):
        return None if nullable else 0.0
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric target-position value {value!r}.") from exc


def _normalize_jsonb(value: Any) -> dict[str, Any] | None:
    if _is_missing(value):
        return None
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("Target-position metadata_json must be a JSON object when provided.")


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = operation_result_rows(result)
    return rows[0] if rows else None


def _string_or_empty(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _required_string(value: Any) -> str:
    text = _string_or_none(value)
    if text is None:
        raise ValueError("Target-position string field is required.")
    return text


def _required_datetime(value: Any, *, field_name: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        timestamp = value
    else:
        raw_value = str(value)
        if raw_value.endswith("Z"):
            raw_value = f"{raw_value[:-1]}+00:00"
        try:
            timestamp = dt.datetime.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp.") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware UTC timestamp.")
    return timestamp.astimezone(dt.UTC)


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


def _int_or_zero(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _none_if_missing(value: Any) -> Any:
    return None if _is_missing(value) else value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


__all__ = [
    "AccountTargetPositionsSnapshotExistsError",
    "TARGET_POSITION_EXPOSURE_FIELDS",
    "add_account_target_positions_snapshot_response",
    "build_target_positions_frame",
    "expand_portfolio_target_positions",
    "get_account_target_positions_snapshot_response",
    "search_account_target_allocation_candidates",
    "validate_target_position_payload",
    "validate_target_positions_frame",
]
