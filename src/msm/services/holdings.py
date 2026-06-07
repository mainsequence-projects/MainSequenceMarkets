from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd

from mainsequence.client import dtype_codec as dc
from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
)
from msm.settings import ASSET_IDENTIFIER_DIMENSION


def build_account_holdings_frame(
    *,
    holdings_date: dt.datetime | str,
    account_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    return build_holdings_frame(
        storage_table=AccountHoldingsStorage,
        holdings_date=holdings_date,
        owner_uid=account_uid,
        positions=positions,
        holdings_set_uid=holdings_set_uid,
        is_trade_snapshot=is_trade_snapshot,
        target_trade_time=target_trade_time,
    )


def build_holdings_frame(
    *,
    storage_table: Any,
    holdings_date: dt.datetime | str,
    owner_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    if not positions:
        raise ValueError("At least one holdings position is required.")
    if holdings_set_uid is None or str(holdings_set_uid).strip() == "":
        raise ValueError("Holdings rows require a holdings_set_uid.")

    owner_index_name = list(storage_table.__index_names__)[1]
    rows: list[dict[str, Any]] = []
    seen_identifiers: set[str] = set()
    duplicate_identifiers: set[str] = set()

    for raw_position in positions:
        position = _position_payload(raw_position)
        asset_identifier = _required_position_string(position, "asset_identifier")
        if asset_identifier in seen_identifiers:
            duplicate_identifiers.add(asset_identifier)
        seen_identifiers.add(asset_identifier)

        row: dict[str, Any] = {
            storage_table.__time_index_name__: holdings_date,
            owner_index_name: owner_uid,
            ASSET_IDENTIFIER_DIMENSION: asset_identifier,
            "holdings_set_uid": holdings_set_uid,
            "is_trade_snapshot": bool(position.get("is_trade_snapshot", is_trade_snapshot)),
            "quantity": position.get("quantity", "0"),
            "direction": position.get("direction", 1),
            "target_trade_time": position.get("target_trade_time", target_trade_time),
            "extra_details": position.get("extra_details") or {},
        }
        rows.append(row)

    if duplicate_identifiers:
        raise ValueError(
            "Each holdings position must use a unique asset_identifier. "
            "Duplicate values: " + ", ".join(sorted(duplicate_identifiers)) + "."
        )

    return validate_holdings_frame(pd.DataFrame(rows), storage_table=storage_table)


def validate_holdings_frame(
    data_frame: pd.DataFrame,
    *,
    storage_table: Any,
) -> pd.DataFrame:
    frame = data_frame.copy()
    index_names = list(storage_table.__index_names__)
    if list(frame.index.names) != index_names:
        if all(index_name in frame.columns for index_name in index_names):
            frame = frame.set_index(index_names)
        else:
            raise ValueError(
                "Holdings frame must use index_names "
                f"{index_names} or include those columns before validation."
            )

    flat = frame.reset_index()
    column_dtypes_map = storage_column_dtypes_map(storage_table)
    column_nullable_map = storage_column_nullable_map(storage_table)
    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Holdings frame is missing required columns: {', '.join(missing_columns)}."
        )

    for column_name, dtype in column_dtypes_map.items():
        values = flat[column_name]
        if column_name == storage_table.__time_index_name__ or dtype == dc.TIMESTAMP_TZ:
            flat[column_name] = values.map(_normalize_optional_datetime)
            if column_name == storage_table.__time_index_name__ and flat[column_name].isna().any():
                raise ValueError("Holdings time_index cannot contain null values.")
            flat[column_name] = pd.to_datetime(flat[column_name], utc=True).astype(
                "datetime64[ns, UTC]"
            )
        elif dtype == dc.UUID_TOKEN:
            flat[column_name] = values.map(lambda value: str(UUID(str(value))))
        elif dtype == dc.FLOAT64:
            flat[column_name] = _normalize_float64_column(
                values,
                nullable=column_nullable_map[column_name],
            )
            if (
                column_name in {"quantity", "allocated_quantity"}
                and (flat[column_name].isna() | (flat[column_name] <= 0)).any()
            ):
                raise ValueError(f"{column_name} must contain positive quantities.")
        elif dtype in {dc.INT16, dc.INT32, dc.INT64}:
            flat[column_name] = values.map(_normalize_direction_int).astype("int16")
        elif dtype == dc.BOOL:
            flat[column_name] = values.map(_normalize_bool)
        elif dtype == dc.JSONB:
            flat[column_name] = values.map(_normalize_jsonb)
        elif dtype == dc.STRING:
            flat[column_name] = values.map(_normalize_required_string)
        else:
            raise ValueError(f"Unsupported holdings dtype {dtype!r} for {column_name!r}.")

    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f"Holdings frame contains duplicate rows for index names {index_names}.")
    return frame


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
            "quantity",
            "direction",
            "target_trade_time",
            "is_trade_snapshot",
            "extra_details",
        )
        if hasattr(position, key)
    }


def _required_position_string(position: Mapping[str, Any], field_name: str) -> str:
    value = position.get(field_name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Holdings positions require a non-empty {field_name}.")
    return str(value)


def _normalize_optional_datetime(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(value, utc=True)


def _normalize_float64_column(values: pd.Series, *, nullable: bool) -> pd.Series:
    normalized = values.map(lambda value: _normalize_optional_float64(value, nullable=nullable))
    return pd.to_numeric(normalized, errors="raise").astype("float64")


def _normalize_optional_float64(value: Any, *, nullable: bool) -> float | None:
    if value is None or pd.isna(value):
        return None if nullable else 0.0
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric holdings value {value!r}.") from exc


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"Invalid boolean holdings value {value!r}.")


def _normalize_direction_int(value: Any) -> int:
    try:
        direction = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid holdings direction {value!r}.") from exc
    if direction not in {1, -1}:
        raise ValueError("Holdings direction must be 1 for long or -1 for short.")
    return direction


def _normalize_jsonb(value: Any) -> dict[str, Any] | list[Any]:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    raise ValueError(f"Invalid jsonb holdings value {value!r}.")


def _normalize_required_string(value: Any) -> str:
    if value is None or pd.isna(value):
        raise ValueError("Required holdings string columns cannot contain null values.")
    return str(value)


__all__ = [
    "build_account_holdings_frame",
    "build_holdings_frame",
    "validate_holdings_frame",
]
