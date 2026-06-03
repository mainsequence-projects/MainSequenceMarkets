from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd

from msm.data_nodes.storage import TargetPositionsStorage
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.settings import ASSET_IDENTIFIER_DIMENSION


TARGET_POSITION_EXPOSURE_FIELDS = (
    "weight_notional_exposure",
    "constant_notional_exposure",
    "single_asset_quantity",
)


def validate_target_position_payload(position: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(position)
    asset_identifier = payload.get("asset_identifier")
    if not isinstance(asset_identifier, str) or not asset_identifier.strip():
        raise ValueError("Target positions require a non-empty asset_identifier.")
    payload[ASSET_IDENTIFIER_DIMENSION] = asset_identifier.strip()

    provided_fields = [
        field_name
        for field_name in TARGET_POSITION_EXPOSURE_FIELDS
        if payload.get(field_name) is not None
    ]
    if len(provided_fields) != 1:
        raise ValueError(
            "Each target position must provide exactly one of "
            "`weight_notional_exposure`, `constant_notional_exposure`, "
            "or `single_asset_quantity`."
        )
    return payload


def build_target_positions_frame(
    *,
    target_positions_date: dt.datetime | str,
    position_set_uid: UUID | str,
    positions: Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    rows = []
    for position in positions:
        payload = validate_target_position_payload(position)
        row = {
            "time_index": target_positions_date,
            "position_set_uid": position_set_uid,
            ASSET_IDENTIFIER_DIMENSION: payload[ASSET_IDENTIFIER_DIMENSION],
            "weight_notional_exposure": payload.get("weight_notional_exposure"),
            "constant_notional_exposure": payload.get("constant_notional_exposure"),
            "single_asset_quantity": payload.get("single_asset_quantity"),
        }
        rows.append(row)

    if not rows:
        raise ValueError("At least one target position is required.")
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
    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Target positions frame is missing required columns: {', '.join(missing_columns)}."
        )

    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype("datetime64[ns, UTC]")
    flat["position_set_uid"] = flat["position_set_uid"].map(lambda value: str(UUID(str(value))))
    flat[ASSET_IDENTIFIER_DIMENSION] = flat[ASSET_IDENTIFIER_DIMENSION].map(str)
    for field_name in TARGET_POSITION_EXPOSURE_FIELDS:
        flat[field_name] = _normalize_optional_float64_column(flat[field_name])

    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"Target positions frame contains duplicate rows for index names {index_names}."
        )
    return frame


def _normalize_optional_float64_column(values: pd.Series) -> pd.Series:
    normalized = values.map(_normalize_optional_float64)
    return pd.to_numeric(normalized, errors="raise").astype("float64")


def _normalize_optional_float64(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric target-position value {value!r}.") from exc


__all__ = [
    "TARGET_POSITION_EXPOSURE_FIELDS",
    "build_target_positions_frame",
    "validate_target_position_payload",
    "validate_target_positions_frame",
]
