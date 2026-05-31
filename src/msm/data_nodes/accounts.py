from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd

from mainsequence.client import dtype_codec as dc
from mainsequence.meta_tables import DataNode
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
from msm.data_nodes.storage import AccountHoldingsStorage, FundHoldingsStorage
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm.services.holdings import (
    build_account_holdings_frame as build_account_holdings_service_frame,
)
from msm.services.holdings import (
    build_fund_holdings_frame as build_fund_holdings_service_frame,
)

ACCOUNT_HOLDINGS_TIME_INDEX_NAME = AccountHoldingsStorage.__time_index_name__
ACCOUNT_HOLDINGS_INDEX_NAMES = list(AccountHoldingsStorage.__index_names__)

VIRTUAL_FUND_HOLDINGS_TIME_INDEX_NAME = FundHoldingsStorage.__time_index_name__
VIRTUAL_FUND_HOLDINGS_INDEX_NAMES = list(FundHoldingsStorage.__index_names__)

NULLABLE_HOLDINGS_COLUMNS = {
    "target_trade_time",
    "target_weight",
}


class HoldingsDataNodeConfiguration(AssetIndexedDataNodeConfiguration):
    """Configuration base for SDK-created holdings data nodes."""

    time_index_name: str
    index_names: list[str]

    @property
    def owner_index_name(self) -> str:
        return self.index_names[1]

    @property
    def row_identifier_index_name(self) -> str:
        return self.index_names[-1]


class HoldingsDataNode(AssetIndexedDataNode):
    """Base class for holdings tables created through the standard DataNode path."""

    def __init__(
        self,
        config: HoldingsDataNodeConfiguration | None = None,
        *args,
        **kwargs,
    ):
        resolved_config = self._validate_config(config or self.default_config())
        super().__init__(resolved_config, *args, **kwargs)

    def dependencies(self) -> dict[str, DataNode]:
        return {}

    @classmethod
    def default_config(cls) -> HoldingsDataNodeConfiguration:
        return cls._validate_config(
            HoldingsDataNodeConfiguration(
                time_index_name=cls._required_time_index_name(),
                index_names=cls._required_index_names(),
            )
        )

    @classmethod
    def _validate_config(
        cls,
        config: HoldingsDataNodeConfiguration,
    ) -> HoldingsDataNodeConfiguration:
        if not isinstance(config, HoldingsDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires a HoldingsDataNodeConfiguration.")
        if config.time_index_name != cls._required_time_index_name():
            raise ValueError(
                f"{cls.__name__} requires time_index_name {cls._required_time_index_name()!r}."
            )
        if config.index_names != cls._required_index_names():
            raise ValueError(
                f"{cls.__name__} requires index_names {cls._required_index_names()!r}."
            )
        return config

    @classmethod
    def _required_time_index_name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def _required_index_names(cls) -> list[str]:
        raise NotImplementedError

    def _holdings_config(self) -> HoldingsDataNodeConfiguration:
        return self.__class__._validate_config(
            getattr(self, "config", None) or self.default_config()
        )

    def update(self) -> pd.DataFrame:
        return _validate_holdings_frame(
            self.get_holdings_frame(),
            config=self._holdings_config(),
            column_dtypes_map=self._bound_column_dtypes_map(),
        )

    def set_frame(self, frame: pd.DataFrame) -> HoldingsDataNode:
        self._holdings_data_frame = frame
        return self

    def get_holdings_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_holdings_data_frame", None)
        if frame is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a real holdings frame. "
                "Call set_frame(), set_account_holdings_frame(), or "
                "set_fund_holdings_frame() before update()."
            )
        return frame

    def get_holdings_history(
        self,
        *,
        owner_unique_identifier: str,
        start_date: dt.datetime | str | None = None,
        end_date: dt.datetime | str | None = None,
        great_or_equal: bool = True,
        less_or_equal: bool = True,
        dimension_filters: dict[str, list[Any]] | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        filters = _dimension_filters_with_identifier(
            dimension_filters,
            self._holdings_config().owner_index_name,
            owner_unique_identifier,
        )
        return self.get_df_between_dates(
            start_date=start_date,
            end_date=end_date,
            great_or_equal=great_or_equal,
            less_or_equal=less_or_equal,
            dimension_filters=filters,
            columns=columns,
        )

    def get_latest_holdings(
        self,
        *,
        owner_unique_identifier: str,
        dimension_filters: dict[str, list[Any]] | None = None,
    ) -> Any:
        filters = _dimension_filters_with_identifier(
            dimension_filters,
            self._holdings_config().owner_index_name,
            owner_unique_identifier,
        )
        return self.get_last_observation(dimension_filters=filters)

    @classmethod
    def validate_holdings_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        storage_table: type[AccountHoldingsStorage | FundHoldingsStorage] | None = None,
    ) -> pd.DataFrame:
        return _validate_holdings_frame(
            data_frame,
            config=cls.default_config(),
            column_dtypes_map=cls._column_dtypes_map_for_storage(storage_table),
        )

    def holdings_data_source_uid(self) -> str:
        return self.ensure_storage_ready()

    def ensure_storage_ready(self, *, force_update: bool = False) -> str:
        storage = None if force_update else self._ready_storage_or_none()
        if storage is None:
            self.run(debug_mode=True, update_tree=False, force_update=True)
            storage = self._ready_storage_or_none()

        if storage is None:
            raise RuntimeError(
                f"{self.__class__.__name__} did not create a ready holdings data node."
            )
        return _coerce_required_uid(storage, field_name="data_node_storage")

    def _ready_storage_or_none(self):
        storage = self.data_node_storage
        if _coerce_optional_uid(storage, field_name="data_node_storage") is None:
            return None

        source_config = _storage_source_config(storage)
        if source_config is None:
            return None

        self._validate_storage_contract(source_config)
        return storage

    def _validate_storage_contract(self, source_config: Any) -> None:
        config = self._holdings_config()
        errors: list[str] = []

        time_index_name = _get_mapping_or_attr(source_config, "time_index_name")
        if time_index_name != config.time_index_name:
            errors.append(
                f"time_index_name {time_index_name!r} does not match {config.time_index_name!r}"
            )

        index_names = list(_get_mapping_or_attr(source_config, "index_names") or [])
        if index_names != config.index_names:
            errors.append(f"index_names {index_names!r} do not match {config.index_names!r}")

        column_dtypes_map = dict(_get_mapping_or_attr(source_config, "column_dtypes_map") or {})
        for column_name, expected_dtype in self._bound_column_dtypes_map().items():
            actual_dtype = column_dtypes_map.get(column_name)
            if actual_dtype != expected_dtype:
                errors.append(
                    f"{column_name!r} dtype {actual_dtype!r} does not match {expected_dtype!r}"
                )

        if errors:
            raise ValueError(
                f"{self.__class__.__name__} is bound to an incompatible "
                "holdings data node: " + "; ".join(errors)
            )


class AccountHoldings(HoldingsDataNode):
    """DataNode users can subclass to import account holdings."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return ACCOUNT_HOLDINGS_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(ACCOUNT_HOLDINGS_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[AccountHoldingsStorage]:
        return AccountHoldingsStorage

    def build_account_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        account_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> pd.DataFrame:
        return build_account_holdings_service_frame(
            holdings_date=holdings_date,
            account_uid=account_uid,
            positions=positions,
            holdings_set_uid=holdings_set_uid,
            is_trade_snapshot=is_trade_snapshot,
            target_trade_time=target_trade_time,
        )

    def set_account_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        account_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> AccountHoldings:
        return self.set_frame(
            self.build_account_holdings_frame(
                holdings_date=holdings_date,
                account_uid=account_uid,
                positions=positions,
                holdings_set_uid=holdings_set_uid,
                is_trade_snapshot=is_trade_snapshot,
                target_trade_time=target_trade_time,
            )
        )


class VirtualFundHoldings(HoldingsDataNode):
    """DataNode users can subclass to import virtual-fund holdings."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return VIRTUAL_FUND_HOLDINGS_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(VIRTUAL_FUND_HOLDINGS_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[FundHoldingsStorage]:
        return FundHoldingsStorage

    def build_fund_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        fund_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> pd.DataFrame:
        return build_fund_holdings_service_frame(
            holdings_date=holdings_date,
            fund_uid=fund_uid,
            positions=positions,
            holdings_set_uid=holdings_set_uid,
            is_trade_snapshot=is_trade_snapshot,
            target_trade_time=target_trade_time,
        )

    def set_fund_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        fund_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> VirtualFundHoldings:
        return self.set_frame(
            self.build_fund_holdings_frame(
                holdings_date=holdings_date,
                fund_uid=fund_uid,
                positions=positions,
                holdings_set_uid=holdings_set_uid,
                is_trade_snapshot=is_trade_snapshot,
                target_trade_time=target_trade_time,
            )
        )

def _dimension_filters_with_identifier(
    dimension_filters: dict[str, list[Any]] | None,
    key: str,
    value: Any,
) -> dict[str, list[Any]]:
    resolved: dict[str, list[Any]] = {
        filter_key: list(filter_values)
        for filter_key, filter_values in (dimension_filters or {}).items()
    }
    identifier = str(value)
    values = resolved.get(key)
    if values is None:
        resolved[key] = [identifier]
        return resolved
    if identifier not in [str(item) for item in values]:
        raise ValueError(f"dimension_filters[{key!r}] conflicts with identifier {identifier!r}.")
    return resolved


def _validate_holdings_frame(
    data_frame: pd.DataFrame,
    *,
    config: HoldingsDataNodeConfiguration,
    column_dtypes_map: dict[str, str],
) -> pd.DataFrame:
    frame = _ensure_config_index(data_frame, config=config)
    flat = frame.reset_index()
    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Holdings frame is missing required columns: {', '.join(missing_columns)}."
        )

    flat = _normalize_config_values(flat, config=config, column_dtypes_map=column_dtypes_map)
    frame = flat.set_index(config.index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"Holdings frame contains duplicate rows for index contract {config.index_names}."
        )
    return frame


def _ensure_config_index(
    data_frame: pd.DataFrame,
    *,
    config: HoldingsDataNodeConfiguration,
) -> pd.DataFrame:
    expected_index_names = list(config.index_names)
    frame = data_frame.copy()
    if list(frame.index.names) == expected_index_names:
        return frame
    if all(index_name in frame.columns for index_name in expected_index_names):
        return frame.set_index(expected_index_names)
    raise ValueError(
        "Holdings frame must use index_names "
        f"{expected_index_names} or include those columns before validation."
    )


def _normalize_config_values(
    frame: pd.DataFrame,
    *,
    config: HoldingsDataNodeConfiguration,
    column_dtypes_map: dict[str, str],
) -> pd.DataFrame:
    normalized = frame.copy()
    for column_name, dtype in column_dtypes_map.items():
        values = normalized[column_name]
        if column_name == config.time_index_name:
            normalized[column_name] = _normalize_time_index(values)
        elif dtype == dc.UUID_TOKEN:
            normalized[column_name] = values.map(_normalize_uuid)
        elif dtype == dc.FLOAT64:
            normalized[column_name] = _normalize_float64_column(
                values,
                nullable=column_name in NULLABLE_HOLDINGS_COLUMNS,
            )
        elif dtype == dc.BOOL:
            normalized[column_name] = values.map(_normalize_bool)
        elif dtype == dc.JSONB:
            normalized[column_name] = values.map(_normalize_jsonb)
        elif dtype == dc.TIMESTAMP_TZ:
            normalized[column_name] = _normalize_time_index(values)
        elif dtype == dc.STRING:
            normalized[column_name] = values.fillna("").map(str)
        else:
            raise ValueError(f"Unsupported holdings dtype {dtype!r} for {column_name!r}.")
    return normalized


def _normalize_uuid(value: Any) -> str:
    if pd.isna(value):
        raise ValueError("UUID holdings columns cannot contain null values.")
    return str(UUID(str(value)))


def _normalize_float64_column(values: pd.Series, *, nullable: bool) -> pd.Series:
    normalized = values.map(lambda value: _normalize_optional_float64(value, nullable=nullable))
    return pd.to_numeric(normalized, errors="raise").astype("float64")


def _normalize_optional_float64(value: Any, *, nullable: bool) -> float | None:
    if pd.isna(value):
        return None if nullable else 0.0
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric holdings value {value!r}.") from exc


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"Invalid boolean holdings value {value!r}.")


def _normalize_jsonb(value: Any) -> dict[str, Any] | list[Any]:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    raise ValueError(f"Invalid jsonb holdings value {value!r}.")


def _normalize_time_index(values: Any) -> pd.Series:
    return normalize_datetime64_ns_utc(values)


def _storage_source_config(storage: Any) -> Any | None:
    return (
        _get_mapping_or_attr(storage, "sourcetableconfiguration")
        or _get_mapping_or_attr(storage, "source_table_configuration")
        or _get_mapping_or_attr(storage, "source_table_config")
    )


def _get_mapping_or_attr(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _coerce_required_uid(value: Any, *, field_name: str) -> str:
    value_uid = _coerce_optional_uid(value, field_name=field_name)
    if value_uid is None:
        raise ValueError(f"{field_name} must expose a uid.")
    return value_uid


def _coerce_optional_uid(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, UUID)):
        return str(value)
    value_uid = getattr(value, "uid", None)
    if value_uid is not None:
        return str(value_uid)
    if isinstance(value, dict) and value.get("uid") is not None:
        return str(value["uid"])
    raise TypeError(f"{field_name} must be a uid or an object with .uid.")


__all__ = [
    "ACCOUNT_HOLDINGS_INDEX_NAMES",
    "ACCOUNT_HOLDINGS_TIME_INDEX_NAME",
    "AccountHoldings",
    "HoldingsDataNode",
    "HoldingsDataNodeConfiguration",
    "VIRTUAL_FUND_HOLDINGS_INDEX_NAMES",
    "VIRTUAL_FUND_HOLDINGS_TIME_INDEX_NAME",
    "VirtualFundHoldings",
]
