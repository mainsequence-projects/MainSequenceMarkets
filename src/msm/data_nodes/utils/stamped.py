from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field

from mainsequence.tdag.data_nodes import (
    DataNode,
    DataNodeConfiguration,
    DataNodeMetaData,
    RecordDefinition,
)
from msm.data_nodes.utils.namespaces import wrap_default_markets_hash_namespace
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm.settings import markets_data_node_identifier

STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER = "__schema_bootstrap__"


class StampedDataNodeConfiguration(DataNodeConfiguration):
    """Configuration for timestamped reference-keyed markets DataNodes."""

    reference_dimension: ClassVar[str] = "unique_identifier"
    frame_label: ClassVar[str] = "Stamped DataNode"

    time_index_name: str = Field(
        default="time_index",
        description="Timestamp column used as the DataNode time index.",
    )
    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", "unique_identifier"],
        description="Canonical DataFrame index columns for the stamped DataNode.",
    )
    records: list[RecordDefinition] = Field(
        ...,
        description="Output schema for the stamped DataNode.",
    )

    @property
    def column_dtypes_map(self) -> dict[str, str]:
        return {record.column_name: record.dtype for record in self.records}


class StampedFrameMixin:
    """Shared frame/config behavior for timestamped markets DataNodes."""

    configuration_class: ClassVar[type[StampedDataNodeConfiguration]] = (
        StampedDataNodeConfiguration
    )
    frame_label: ClassVar[str] = "Stamped DataNode"
    bootstrap_unique_identifier: ClassVar[str] = STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER
    bootstrap_time_index: ClassVar[dt.datetime] = STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX

    def __init__(
        self,
        config: StampedDataNodeConfiguration | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(config=config or self.default_config(), *args, **kwargs)

    @classmethod
    def default_config(
        cls,
        *,
        identifier: str | None = None,
        description: str | None = None,
        extra_records: list[RecordDefinition] | None = None,
    ) -> StampedDataNodeConfiguration:
        config_kwargs: dict[str, Any] = {
            "node_metadata": DataNodeMetaData(
                identifier=identifier or cls._default_identifier(),
                description=description or cls._default_description(),
            ),
        }
        if extra_records:
            config_kwargs["records"] = cls._records_with_extra(extra_records=extra_records)
        return cls.configuration_class(**config_kwargs)

    @classmethod
    def _records_with_extra(
        cls,
        *,
        extra_records: list[RecordDefinition] | None = None,
    ) -> list[RecordDefinition]:
        required_records = cls.configuration_class().records
        if not extra_records:
            return list(required_records)

        by_name = {record.column_name: record for record in required_records}
        for record in extra_records:
            by_name.setdefault(record.column_name, record)
        return list(by_name.values())

    @classmethod
    def _default_identifier(cls) -> str:
        identifier = getattr(cls, "__data_node_identifier__", None)
        if not identifier:
            raise NotImplementedError(
                f"{cls.__name__} must define __data_node_identifier__ or "
                "override _default_identifier()."
            )
        return markets_data_node_identifier(identifier)

    @classmethod
    def _default_description(cls) -> str:
        raise NotImplementedError

    def set_frame(self, frame: pd.DataFrame):
        self._stamped_data_frame = frame
        return self

    def get_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_stamped_data_frame", None)
        if frame is None:
            return self.build_schema_bootstrap_frame(config=self.config)
        return frame

    def update(self) -> pd.DataFrame:
        return validate_stamped_data_frame(
            self.get_frame(),
            config=self.config,
            frame_label=self.frame_label,
        )

    @classmethod
    def validate_frame(
        cls,
        frame: pd.DataFrame,
        *,
        config: StampedDataNodeConfiguration | None = None,
    ) -> pd.DataFrame:
        return validate_stamped_data_frame(
            frame,
            config=config or cls.default_config(),
            frame_label=cls.frame_label,
        )

    @classmethod
    def build_initialization_frame(
        cls,
        **kwargs: Any,
    ) -> pd.DataFrame:
        return cls.build_schema_bootstrap_frame(**kwargs)

    @classmethod
    def build_schema_bootstrap_frame(
        cls,
        *,
        config: StampedDataNodeConfiguration | None = None,
        unique_identifier: str | None = None,
        time_index: dt.datetime | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        resolved_config = config or cls.default_config()
        row = {
            resolved_config.time_index_name: time_index or cls.bootstrap_time_index,
            resolved_config.reference_dimension: (
                unique_identifier or cls.bootstrap_unique_identifier
            ),
        }
        for record in resolved_config.records:
            if record.column_name not in row:
                row[record.column_name] = schema_bootstrap_value(record.dtype)
        frame = pd.DataFrame([row])
        return validate_stamped_data_frame(
            frame,
            config=resolved_config,
            frame_label=cls.frame_label,
        )

    @classmethod
    def build_mock_frame(cls, **kwargs: Any) -> pd.DataFrame:
        return cls.build_schema_bootstrap_frame(**kwargs)


class StampedDataNode(StampedFrameMixin, DataNode):
    """Base DataNode for timestamped facts keyed by a reference unique identifier."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__init__ = wrap_default_markets_hash_namespace(cls, cls.__init__)

    def dependencies(self) -> dict:
        return {}


def validate_stamped_data_frame(
    frame: pd.DataFrame,
    *,
    config: StampedDataNodeConfiguration,
    frame_label: str | None = None,
) -> pd.DataFrame:
    if not isinstance(config, StampedDataNodeConfiguration):
        raise TypeError("Stamped DataNodes require StampedDataNodeConfiguration.")

    label = frame_label or config.frame_label
    normalized = reset_frame_index(frame.copy(), index_names=config.index_names)
    required_columns = {record.column_name for record in config.records}
    missing = sorted(required_columns.difference(normalized.columns))
    if missing:
        raise ValueError(f"{label} frame is missing columns: {missing!r}.")

    normalized[config.time_index_name] = normalize_datetime64_ns_utc(
        normalized[config.time_index_name]
    )
    normalized[config.reference_dimension] = normalized[config.reference_dimension].astype(
        "string"
    )
    normalized = normalized[[record.column_name for record in config.records]]
    normalized = normalized.set_index(config.index_names)

    if normalized.index.has_duplicates:
        raise ValueError(f"{label} frame contains duplicate rows for {config.index_names!r}.")
    return normalized.sort_index()


def reset_frame_index(
    frame: pd.DataFrame,
    *,
    index_names: list[str],
    frame_label: str = "Stamped DataNode",
) -> pd.DataFrame:
    missing_index_names = [
        index_name
        for index_name in index_names
        if index_name not in frame.columns and index_name not in (frame.index.names or [])
    ]
    if missing_index_names:
        raise ValueError(f"{frame_label} frame is missing index columns: {missing_index_names!r}.")
    has_required_index = any(name in index_names for name in frame.index.names)
    return frame.reset_index() if has_required_index else frame


def schema_bootstrap_value(dtype: str) -> Any:
    if dtype == "datetime64[ns, UTC]":
        return STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX
    if dtype in {"jsonb", "json"}:
        return {"_mainsequence_reserved": "schema_bootstrap", "semantic": False}
    if dtype in {"float64", "decimal"}:
        return "0"
    if dtype in {"int64", "Int64"}:
        return 0
    if dtype == "bool":
        return False
    return ""


__all__ = [
    "STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX",
    "STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER",
    "StampedDataNode",
    "StampedDataNodeConfiguration",
    "StampedFrameMixin",
    "reset_frame_index",
    "schema_bootstrap_value",
    "validate_stamped_data_frame",
]
