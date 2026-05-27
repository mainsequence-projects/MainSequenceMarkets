from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import pandas as pd

from mainsequence.client.models_tdag import LOGICAL_COLUMN_DTYPES_ATTR
from msm.data_nodes import (
    ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
    DataNodeTableContract,
    FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
    source_table_initialization_kwargs,
)


NULLABLE_HOLDINGS_COLUMNS = {
    "target_trade_time",
    "target_weight",
}


def initialize_data_node_source_table(
    *,
    storage: Any,
    config: Any,
    storage_layout: dict[str, Any] | None = None,
    open_for_everyone: bool | None = None,
    timeout: int | None = None,
) -> dict[str, Any] | None:
    """Initialize a holdings DataNode through the generic platform source-table API."""

    initializer = getattr(storage, "initialize_source_table", None)
    if not callable(initializer):
        raise AttributeError(
            "DataNode storage object must expose initialize_source_table(...). "
            "Legacy domain-specific initialize_*_holdings_source_table helpers "
            "are not used."
        )
    payload = {
        "time_index_name": config.time_index_name,
        "index_names": config.index_names,
        "column_dtypes_map": config.column_dtypes_map,
    }
    if storage_layout is not None:
        payload["storage_layout"] = storage_layout
    if open_for_everyone is not None:
        payload["open_for_everyone"] = open_for_everyone
    if timeout is not None:
        payload["timeout"] = timeout
    return initializer(**payload)


def holdings_source_table_kwargs(
    contract: DataNodeTableContract,
) -> dict[str, object]:
    return source_table_initialization_kwargs(contract)


def build_account_holdings_frame(
    *,
    holdings_date: dt.datetime | str,
    account_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str | None = None,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    return build_holdings_frame(
        contract=ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
        holdings_date=holdings_date,
        owner_uid=account_uid,
        positions=positions,
        holdings_set_uid=holdings_set_uid,
        is_trade_snapshot=is_trade_snapshot,
        target_trade_time=target_trade_time,
    )


def build_fund_holdings_frame(
    *,
    holdings_date: dt.datetime | str,
    fund_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str | None = None,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    return build_holdings_frame(
        contract=FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
        holdings_date=holdings_date,
        owner_uid=fund_uid,
        positions=positions,
        holdings_set_uid=holdings_set_uid,
        is_trade_snapshot=is_trade_snapshot,
        target_trade_time=target_trade_time,
    )


def build_holdings_frame(
    *,
    contract: DataNodeTableContract,
    holdings_date: dt.datetime | str,
    owner_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str | None = None,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    if not positions:
        raise ValueError("At least one holdings position is required.")

    resolved_holdings_set_uid = holdings_set_uid or uuid4()
    owner_index_name = _owner_index_name(contract)
    rows: list[dict[str, Any]] = []
    seen_identifiers: set[str] = set()
    duplicate_identifiers: set[str] = set()

    for raw_position in positions:
        position = _position_payload(raw_position)
        unique_identifier = _required_position_string(position, "unique_identifier")
        if unique_identifier in seen_identifiers:
            duplicate_identifiers.add(unique_identifier)
        seen_identifiers.add(unique_identifier)

        row: dict[str, Any] = {
            contract.time_index_name: holdings_date,
            owner_index_name: owner_uid,
            "unique_identifier": unique_identifier,
            "holdings_set_uid": resolved_holdings_set_uid,
            "is_trade_snapshot": bool(position.get("is_trade_snapshot", is_trade_snapshot)),
            "quantity": position.get("quantity", "0"),
            "target_trade_time": position.get("target_trade_time", target_trade_time),
            "extra_details": position.get("extra_details") or {},
        }
        if "target_weight" in contract.column_dtypes_map:
            row["target_weight"] = position.get("target_weight")
        rows.append(row)

    if duplicate_identifiers:
        raise ValueError(
            "Each holdings position must use a unique unique_identifier. "
            "Duplicate values: " + ", ".join(sorted(duplicate_identifiers)) + "."
        )

    return validate_holdings_frame(pd.DataFrame(rows), contract=contract)


def validate_holdings_frame(
    data_frame: pd.DataFrame,
    *,
    contract: DataNodeTableContract,
) -> pd.DataFrame:
    frame = data_frame.copy()
    index_names = contract.dynamic_table_index_names
    if list(frame.index.names) != index_names:
        if all(index_name in frame.columns for index_name in index_names):
            frame = frame.set_index(index_names)
        else:
            raise ValueError(
                "Holdings frame must use index_names "
                f"{index_names} or include those columns before validation."
            )

    flat = frame.reset_index()
    missing_columns = [
        column_name for column_name in contract.column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Holdings frame is missing required columns: {', '.join(missing_columns)}."
        )

    for column_name, dtype in contract.column_dtypes_map.items():
        values = flat[column_name]
        if column_name == contract.time_index_name or dtype == "datetime64[ns, UTC]":
            flat[column_name] = values.map(_normalize_optional_datetime)
            if column_name == contract.time_index_name:
                if flat[column_name].isna().any():
                    raise ValueError("Holdings time_index cannot contain null values.")
                flat[column_name] = pd.to_datetime(flat[column_name], utc=True).astype(
                    "datetime64[ns, UTC]"
                )
        elif dtype == "uuid":
            flat[column_name] = values.map(lambda value: str(UUID(str(value))))
        elif dtype == "decimal":
            flat[column_name] = values.map(
                lambda value: _normalize_optional_decimal(
                    value,
                    nullable=column_name in NULLABLE_HOLDINGS_COLUMNS,
                )
            )
        elif dtype == "bool":
            flat[column_name] = values.map(_normalize_bool)
        elif dtype == "jsonb":
            flat[column_name] = values.map(_normalize_jsonb)
        elif dtype in {"string", "object"}:
            flat[column_name] = values.map(_normalize_required_string)
        else:
            raise ValueError(f"Unsupported holdings dtype {dtype!r} for {column_name!r}.")

    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"Holdings frame contains duplicate rows for index contract {index_names}."
        )
    frame.attrs[LOGICAL_COLUMN_DTYPES_ATTR] = dict(contract.column_dtypes_map)
    return frame


def _owner_index_name(contract: DataNodeTableContract) -> str:
    try:
        return contract.dynamic_table_index_names[1]
    except IndexError as exc:
        raise ValueError("Holdings contracts require an owner index.") from exc


def _position_payload(position: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(position, Mapping):
        return dict(position)
    model_dump = getattr(position, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    return {
        key: getattr(position, key)
        for key in (
            "unique_identifier",
            "quantity",
            "target_trade_time",
            "target_weight",
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


def _normalize_optional_decimal(value: Any, *, nullable: bool) -> str | None:
    if value is None or pd.isna(value):
        return None if nullable else "0"
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal holdings value {value!r}.") from exc


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"Invalid boolean holdings value {value!r}.")


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
    "ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT",
    "FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT",
    "build_account_holdings_frame",
    "build_fund_holdings_frame",
    "build_holdings_frame",
    "holdings_source_table_kwargs",
    "initialize_data_node_source_table",
    "validate_holdings_frame",
]
