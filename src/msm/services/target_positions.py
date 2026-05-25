from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd

from mainsequence.client.models_tdag import LOGICAL_COLUMN_DTYPES_ATTR

from msm.data_nodes import POSITION_EXPOSURE_TABLE_CONTRACT, source_table_initialization_kwargs


TARGET_POSITION_EXPOSURE_FIELDS = (
    "weight_notional_exposure",
    "constant_notional_exposure",
    "single_asset_quantity",
)


def validate_target_position_payload(position: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(position)
    unique_identifier = payload.get("unique_identifier")
    if not isinstance(unique_identifier, str) or not unique_identifier.strip():
        raise ValueError("Target positions require a non-empty unique_identifier.")

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
            "unique_identifier": payload["unique_identifier"],
            "weight_notional_exposure": payload.get("weight_notional_exposure"),
            "constant_notional_exposure": payload.get("constant_notional_exposure"),
            "single_asset_quantity": payload.get("single_asset_quantity"),
        }
        rows.append(row)

    if not rows:
        raise ValueError("At least one target position is required.")
    return validate_target_positions_frame(pd.DataFrame(rows))


def validate_target_positions_frame(data_frame: pd.DataFrame) -> pd.DataFrame:
    contract = POSITION_EXPOSURE_TABLE_CONTRACT
    frame = data_frame.copy()
    index_names = contract.dynamic_table_index_names
    if list(frame.index.names) != index_names:
        if all(index_name in frame.columns for index_name in index_names):
            frame = frame.set_index(index_names)
        else:
            raise ValueError(
                "Target positions frame must use index_names "
                f"{index_names} or include those columns before validation."
            )

    flat = frame.reset_index()
    missing_columns = [
        column_name
        for column_name in contract.column_dtypes_map
        if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            "Target positions frame is missing required columns: "
            f"{', '.join(missing_columns)}."
        )

    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    flat["position_set_uid"] = flat["position_set_uid"].map(lambda value: str(UUID(str(value))))
    flat["unique_identifier"] = flat["unique_identifier"].map(str)
    for field_name in TARGET_POSITION_EXPOSURE_FIELDS:
        flat[field_name] = flat[field_name].map(_normalize_optional_decimal)

    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            "Target positions frame contains duplicate rows for index contract "
            f"{index_names}."
        )
    frame.attrs[LOGICAL_COLUMN_DTYPES_ATTR] = dict(contract.column_dtypes_map)
    return frame


def target_positions_source_table_kwargs() -> dict[str, object]:
    return source_table_initialization_kwargs(POSITION_EXPOSURE_TABLE_CONTRACT)


def _normalize_optional_decimal(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal target-position value {value!r}.") from exc


__all__ = [
    "POSITION_EXPOSURE_TABLE_CONTRACT",
    "TARGET_POSITION_EXPOSURE_FIELDS",
    "build_target_positions_frame",
    "target_positions_source_table_kwargs",
    "validate_target_position_payload",
    "validate_target_positions_frame",
]
