from __future__ import annotations
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
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map, storage_index_names
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc


class ExecutionDataNodeConfiguration(AssetIndexedDataNodeConfiguration):
    """Update-scoped configuration base for SDK-owned execution DataNodes."""


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
        return cls._validate_config(ExecutionDataNodeConfiguration())

    @classmethod
    def _validate_config(
        cls,
        config: ExecutionDataNodeConfiguration,
    ) -> ExecutionDataNodeConfiguration:
        if not isinstance(config, ExecutionDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires an ExecutionDataNodeConfiguration.")
        return config

    def _execution_config(self) -> ExecutionDataNodeConfiguration:
        return self.__class__._validate_config(
            getattr(self, "config", None) or self.default_config()
        )

    def update(self) -> pd.DataFrame:
        return _validate_execution_frame(
            self.get_execution_frame(),
            storage_table=self.storage_table,
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
        storage_table: (
            type[OrdersStorage | OrderEventsStorage | TradesStorage | ExecutionErrorsStorage] | None
        ) = None,
    ) -> pd.DataFrame:
        resolved_storage_table = storage_table or cls._required_storage_table()
        return _validate_execution_frame(
            data_frame,
            storage_table=resolved_storage_table,
        )

    @classmethod
    def validate_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        storage_table: (
            type[OrdersStorage | OrderEventsStorage | TradesStorage | ExecutionErrorsStorage] | None
        ) = None,
    ) -> pd.DataFrame:
        return cls.validate_execution_frame(
            data_frame,
            storage_table=storage_table,
        )


class Orders(ExecutionDataNode):
    """Timestamped order records replacing Django Order, MarketOrder, and LimitOrder."""

    @classmethod
    def _required_storage_table(cls) -> type[OrdersStorage]:
        return OrdersStorage


class OrderEvents(ExecutionDataNode):
    """Timestamped order status events."""

    @classmethod
    def _required_storage_table(cls) -> type[OrderEventsStorage]:
        return OrderEventsStorage


class Trades(ExecutionDataNode):
    """Timestamped trade execution records."""

    @classmethod
    def _required_storage_table(cls) -> type[TradesStorage]:
        return TradesStorage


class ExecutionErrors(ExecutionDataNode):
    """Timestamped execution error records."""

    @classmethod
    def _required_storage_table(cls) -> type[ExecutionErrorsStorage]:
        return ExecutionErrorsStorage


def _validate_execution_frame(
    data_frame: pd.DataFrame,
    *,
    storage_table: type[
        OrdersStorage | OrderEventsStorage | TradesStorage | ExecutionErrorsStorage
    ],
) -> pd.DataFrame:
    index_names = storage_index_names(storage_table)
    column_dtypes_map = storage_column_dtypes_map(storage_table)
    frame = data_frame.copy()
    if list(frame.index.names) == index_names:
        flat = frame.reset_index()
    elif all(index_name in frame.columns for index_name in index_names):
        flat = frame
    else:
        raise ValueError(
            "Execution frame must use index_names "
            f"{index_names} or include those columns before validation."
        )

    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Execution frame is missing required columns: {', '.join(missing_columns)}."
        )

    flat = _normalize_execution_values(flat, column_dtypes_map=column_dtypes_map)
    frame = flat[list(column_dtypes_map)].set_index(index_names)
    if frame.index.has_duplicates:
        raise ValueError(
            f"Execution frame contains duplicate rows for index contract {index_names}."
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
    "ExecutionDataNode",
    "ExecutionDataNodeConfiguration",
    "ExecutionErrors",
    "OrderEvents",
    "Orders",
    "Trades",
]
