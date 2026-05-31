from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from mainsequence.client import dtype_codec as dc
from mainsequence.meta_tables import DataNode
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
from msm.data_nodes.storage import (
    ExecutionErrorsStorage,
    OrderEventsStorage,
    OrdersStorage,
    TradesStorage,
)
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc

ORDERS_TIME_INDEX_NAME = "order_time"
ORDERS_INDEX_NAMES = [
    "order_time",
    "order_unique_identifier",
    "account_unique_identifier",
    "asset_unique_identifier",
]

ORDER_EVENTS_TIME_INDEX_NAME = "event_time"
ORDER_EVENTS_INDEX_NAMES = [
    "event_time",
    "order_unique_identifier",
]

TRADES_TIME_INDEX_NAME = "trade_time"
TRADES_INDEX_NAMES = [
    "trade_time",
    "trade_unique_identifier",
    "account_unique_identifier",
    "asset_unique_identifier",
]

EXECUTION_ERRORS_TIME_INDEX_NAME = "time_recorded"
EXECUTION_ERRORS_INDEX_NAMES = [
    "time_recorded",
    "error_unique_identifier",
]


class ExecutionDataNodeConfiguration(AssetIndexedDataNodeConfiguration):
    """Configuration base for SDK-owned execution DataNodes."""

    time_index_name: str
    index_names: list[str]


class ExecutionDataNode(AssetIndexedDataNode):
    """Base DataNode for timestamped execution facts."""

    def __init__(
        self,
        config: ExecutionDataNodeConfiguration | None = None,
        *args,
        **kwargs,
    ):
        resolved_config = self._validate_config(config or self.default_config())
        super().__init__(resolved_config, *args, **kwargs)

    def dependencies(self) -> dict[str, DataNode]:
        return {}

    @classmethod
    def default_config(cls) -> ExecutionDataNodeConfiguration:
        return cls._validate_config(
            ExecutionDataNodeConfiguration(
                time_index_name=cls._required_time_index_name(),
                index_names=cls._required_index_names(),
            )
        )

    @classmethod
    def _validate_config(
        cls,
        config: ExecutionDataNodeConfiguration,
    ) -> ExecutionDataNodeConfiguration:
        if not isinstance(config, ExecutionDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires an ExecutionDataNodeConfiguration.")
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

    def _execution_config(self) -> ExecutionDataNodeConfiguration:
        return self.__class__._validate_config(
            getattr(self, "config", None) or self.default_config()
        )

    def update(self) -> pd.DataFrame:
        return _validate_execution_frame(
            self.get_execution_frame(),
            config=self._execution_config(),
            column_dtypes_map=self._bound_column_dtypes_map(),
        )

    def set_frame(self, frame: pd.DataFrame) -> ExecutionDataNode:
        self._execution_data_frame = frame
        return self

    def get_execution_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_execution_data_frame", None)
        if frame is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a real execution frame. "
                "Call set_frame() before update()."
            )
        return frame

    @classmethod
    def validate_execution_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        config: ExecutionDataNodeConfiguration | None = None,
        storage_table: (
            type[OrdersStorage | OrderEventsStorage | TradesStorage | ExecutionErrorsStorage] | None
        ) = None,
    ) -> pd.DataFrame:
        config = cls._validate_config(config or cls.default_config())
        return _validate_execution_frame(
            data_frame,
            config=config,
            column_dtypes_map=cls._column_dtypes_map_for_storage(storage_table),
        )

    @classmethod
    def validate_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        config: ExecutionDataNodeConfiguration | None = None,
        storage_table: (
            type[OrdersStorage | OrderEventsStorage | TradesStorage | ExecutionErrorsStorage] | None
        ) = None,
    ) -> pd.DataFrame:
        return cls.validate_execution_frame(
            data_frame,
            config=config,
            storage_table=storage_table,
        )


class Orders(ExecutionDataNode):
    """Timestamped order records replacing Django Order, MarketOrder, and LimitOrder."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return ORDERS_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(ORDERS_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[OrdersStorage]:
        return OrdersStorage


class OrderEvents(ExecutionDataNode):
    """Timestamped order status events."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return ORDER_EVENTS_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(ORDER_EVENTS_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[OrderEventsStorage]:
        return OrderEventsStorage


class Trades(ExecutionDataNode):
    """Timestamped trade execution records."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return TRADES_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(TRADES_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[TradesStorage]:
        return TradesStorage


class ExecutionErrors(ExecutionDataNode):
    """Timestamped execution error records."""

    @classmethod
    def _required_time_index_name(cls) -> str:
        return EXECUTION_ERRORS_TIME_INDEX_NAME

    @classmethod
    def _required_index_names(cls) -> list[str]:
        return list(EXECUTION_ERRORS_INDEX_NAMES)

    @classmethod
    def _required_storage_table(cls) -> type[ExecutionErrorsStorage]:
        return ExecutionErrorsStorage


def _validate_execution_frame(
    data_frame: pd.DataFrame,
    *,
    config: ExecutionDataNodeConfiguration,
    column_dtypes_map: dict[str, str],
) -> pd.DataFrame:
    frame = data_frame.copy()
    if list(frame.index.names) == config.index_names:
        flat = frame.reset_index()
    elif all(index_name in frame.columns for index_name in config.index_names):
        flat = frame
    else:
        raise ValueError(
            "Execution frame must use index_names "
            f"{config.index_names} or include those columns before validation."
        )

    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Execution frame is missing required columns: {', '.join(missing_columns)}."
        )

    flat = _normalize_execution_values(flat, column_dtypes_map=column_dtypes_map)
    frame = flat[list(column_dtypes_map)].set_index(config.index_names)
    if frame.index.has_duplicates:
        raise ValueError(
            f"Execution frame contains duplicate rows for index contract {config.index_names}."
        )
    return frame.sort_index()


def _normalize_execution_values(
    frame: pd.DataFrame,
    *,
    column_dtypes_map: dict[str, str],
) -> pd.DataFrame:
    normalized = frame.copy()
    for column_name, dtype in column_dtypes_map.items():
        values = normalized[column_name]
        if dtype == dc.TIMESTAMP_TZ:
            normalized[column_name] = normalize_datetime64_ns_utc(values)
        elif dtype == dc.STRING:
            normalized[column_name] = values.fillna("").map(str)
        elif dtype == dc.FLOAT64:
            normalized[column_name] = pd.to_numeric(values, errors="coerce").fillna(0.0)
        elif dtype == dc.INT64:
            normalized[column_name] = (
                pd.to_numeric(values, errors="coerce").fillna(0).astype("int64")
            )
        elif dtype == dc.BOOL:
            normalized[column_name] = values.map(bool)
        elif dtype == dc.JSONB:
            normalized[column_name] = values.map(_normalize_jsonb)
        else:
            raise ValueError(f"Unsupported execution dtype {dtype!r}.")
    return normalized


def _normalize_jsonb(value: Any) -> dict[str, Any] | list[Any]:
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return {}
    if isinstance(value, (dict, list)):
        return value
    raise ValueError(f"Invalid jsonb execution value {value!r}.")


__all__ = [
    "EXECUTION_ERRORS_INDEX_NAMES",
    "EXECUTION_ERRORS_TIME_INDEX_NAME",
    "ORDER_EVENTS_INDEX_NAMES",
    "ORDER_EVENTS_TIME_INDEX_NAME",
    "ORDERS_INDEX_NAMES",
    "ORDERS_TIME_INDEX_NAME",
    "TRADES_INDEX_NAMES",
    "TRADES_TIME_INDEX_NAME",
    "ExecutionDataNode",
    "ExecutionDataNodeConfiguration",
    "ExecutionErrors",
    "OrderEvents",
    "Orders",
    "Trades",
]
