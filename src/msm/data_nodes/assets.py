from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field, model_validator

from msm.data_nodes._time import normalize_datetime64_ns_utc, normalize_timestamp_ns_utc
from msm.asset_indexed_data_node import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
    asset_indexed_foreign_keys,
)
from msm.settings import ASSET_UNIQUE_IDENTIFIER_DIMENSION, markets_data_node_identifier
from mainsequence.tdag.data_nodes import (
    DataNodeMetaData,
    RecordDefinition,
)

ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER = "__schema_bootstrap__"
ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
AssetSnapshotInput = Mapping[str, Any] | Any


def asset_time_index_record() -> RecordDefinition:
    return RecordDefinition(
        column_name="time_index",
        dtype="datetime64[ns, UTC]",
        label="Time Index",
        description="UTC timestamp for the asset fact row.",
    )


def asset_unique_identifier_record() -> RecordDefinition:
    return RecordDefinition(
        column_name=ASSET_UNIQUE_IDENTIFIER_DIMENSION,
        dtype="string",
        label="Unique Identifier",
        description="Asset unique identifier from the selected master-list table.",
    )


def asset_snapshot_records() -> list[RecordDefinition]:
    return [
        asset_time_index_record(),
        asset_unique_identifier_record(),
        RecordDefinition(
            column_name="name",
            dtype="string",
            label="Name",
            description="Security name as recorded by the asset data provider.",
        ),
        RecordDefinition(
            column_name="ticker",
            dtype="string",
            label="Ticker",
            description="Ticker or display symbol.",
        ),
        RecordDefinition(
            column_name="exchange_code",
            dtype="string",
            label="Exchange Code",
            description="Exchange or market code.",
        ),
        RecordDefinition(
            column_name="asset_ticker_group_id",
            dtype="string",
            label="Asset Ticker Group ID",
            description="Highest aggregation level for share-class grouping.",
        ),
    ]


def asset_pricing_detail_records() -> list[RecordDefinition]:
    return [
        asset_time_index_record(),
        asset_unique_identifier_record(),
        RecordDefinition(
            column_name="instrument_dump",
            dtype="jsonb",
            label="Instrument Dump",
            description="Provider-specific pricing instrument payload.",
        ),
    ]


class AssetDataNodeConfiguration(AssetIndexedDataNodeConfiguration):
    """Configuration for timestamped asset DataNodes."""

    time_index_name: str = Field(
        default="time_index",
        description="Timestamp column used as the DataNode time index.",
    )
    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", ASSET_UNIQUE_IDENTIFIER_DIMENSION],
        description="Canonical DataFrame index columns for the asset DataNode.",
    )
    records: list[RecordDefinition] = Field(
        ...,
        description="Output schema for the asset DataNode.",
    )

    @property
    def column_dtypes_map(self) -> dict[str, str]:
        return {record.column_name: record.dtype for record in self.records}

    @model_validator(mode="after")
    def _ensure_asset_foreign_key(self) -> AssetDataNodeConfiguration:
        self.foreign_keys = asset_indexed_foreign_keys(
            records=self.records,
            foreign_keys=self.foreign_keys,
        )
        return self


class AssetSnapshotConfiguration(AssetDataNodeConfiguration):
    """Configuration for the canonical AssetSnapshot DataNode."""

    records: list[RecordDefinition] = Field(
        default_factory=asset_snapshot_records,
        description="Output schema for the AssetSnapshot DataNode.",
    )


class AssetPricingDetailConfiguration(AssetDataNodeConfiguration):
    """Configuration for the canonical AssetPricingDetail DataNode."""

    records: list[RecordDefinition] = Field(
        default_factory=asset_pricing_detail_records,
        description="Output schema for the AssetPricingDetail DataNode.",
    )


class AssetTimestampedFrameMixin:
    """Shared frame/config behavior for timestamped asset DataNodes."""

    configuration_class: ClassVar[type[AssetDataNodeConfiguration]] = AssetDataNodeConfiguration

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __init__(
        self,
        config: AssetDataNodeConfiguration | None = None,
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
    ) -> AssetDataNodeConfiguration:
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
        raise NotImplementedError

    @classmethod
    def _default_description(cls) -> str:
        raise NotImplementedError

    def set_frame(self, frame: pd.DataFrame) -> AssetTimestampedFrameMixin:
        self._asset_data_frame = frame
        return self

    def get_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_asset_data_frame", None)
        if frame is None:
            return self.build_schema_bootstrap_frame(config=self.config)
        return frame

    def update(self) -> pd.DataFrame:
        return _validate_asset_data_frame(self.get_frame(), config=self.config)

    @classmethod
    def validate_frame(
        cls,
        frame: pd.DataFrame,
        *,
        config: AssetDataNodeConfiguration | None = None,
    ) -> pd.DataFrame:
        return _validate_asset_data_frame(frame, config=config or cls.default_config())

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
        config: AssetDataNodeConfiguration | None = None,
        unique_identifier: str = ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER,
        time_index: dt.datetime | pd.Timestamp = ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX,
    ) -> pd.DataFrame:
        resolved_config = config or cls.default_config()
        row = {
            resolved_config.time_index_name: time_index,
            ASSET_UNIQUE_IDENTIFIER_DIMENSION: unique_identifier,
        }
        for record in resolved_config.records:
            if record.column_name not in row:
                row[record.column_name] = _schema_bootstrap_value(record.dtype)
        frame = pd.DataFrame([row])
        return _validate_asset_data_frame(frame, config=resolved_config)

    @classmethod
    def build_mock_frame(cls, **kwargs: Any) -> pd.DataFrame:
        return cls.build_schema_bootstrap_frame(**kwargs)


class AssetTimestampedDataNode(AssetTimestampedFrameMixin, AssetIndexedDataNode):
    """Base asset-indexed DataNode for timestamped facts keyed by unique_identifier."""

    def dependencies(self) -> dict:
        return {}


class AssetSnapshot(AssetTimestampedDataNode):
    """Timestamped asset display snapshots keyed by asset unique_identifier."""

    __data_node_identifier__ = "asset_snapshots"
    configuration_class = AssetSnapshotConfiguration

    @classmethod
    def build_frame(
        cls,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
        *,
        config: AssetDataNodeConfiguration | None = None,
    ) -> pd.DataFrame:
        """Build a validated frame from row payloads with per-row `time_index`."""

        rows = []
        for snapshot in _snapshot_items(snapshots):
            payload = _snapshot_payload(snapshot)
            unique_identifier = _required_snapshot_string(payload, "unique_identifier")
            rows.append(
                {
                    "time_index": _required_snapshot_time(payload),
                    "unique_identifier": unique_identifier,
                    "name": _optional_snapshot_string(payload, "name"),
                    "ticker": _optional_snapshot_string(payload, "ticker"),
                    "exchange_code": _optional_snapshot_string(payload, "exchange_code"),
                    "asset_ticker_group_id": _optional_snapshot_string(
                        payload,
                        "asset_ticker_group_id",
                    ),
                }
            )

        if not rows:
            raise ValueError("At least one asset snapshot is required.")
        return cls.validate_frame(pd.DataFrame(rows), config=config)

    def set_snapshots(
        self,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    ) -> AssetSnapshot:
        """Validate snapshot row payloads and attach them to this DataNode."""

        return self.set_frame(self.build_frame(snapshots, config=self.config))

    def _execute_local_update(self, historical_update: Any):
        self._verify_backend_snapshot_index = True
        try:
            return super()._execute_local_update(historical_update=historical_update)
        finally:
            self._verify_backend_snapshot_index = False

    def update(self) -> pd.DataFrame:
        frame = super().update()
        if getattr(self, "_verify_backend_snapshot_index", False):
            self.verify_backend_index_available(frame)
        return frame

    def verify_backend_index_available(self, frame: pd.DataFrame) -> None:
        """Raise when any `(time_index, unique_identifier)` key already exists."""

        existing_keys = self.existing_backend_index_keys(frame)
        if existing_keys:
            formatted_keys = ", ".join(
                f"({time_index}, {unique_identifier})"
                for time_index, unique_identifier in existing_keys
            )
            raise ValueError(
                "AssetSnapshot rows already exist for "
                f"(time_index, unique_identifier): {formatted_keys}."
            )

    def existing_backend_index_keys(self, frame: pd.DataFrame) -> list[tuple[str, str]]:
        """Return existing backend keys that would collide with `frame`."""

        candidate_keys = _asset_snapshot_index_keys(
            self.validate_frame(frame, config=self.config)
        )
        existing_keys: list[tuple[str, str]] = []
        for time_index, unique_identifier in candidate_keys:
            existing_frame = self.get_df_between_dates(
                start_date=time_index.to_pydatetime(),
                end_date=time_index.to_pydatetime(),
                great_or_equal=True,
                less_or_equal=True,
                dimension_filters={
                    ASSET_UNIQUE_IDENTIFIER_DIMENSION: [unique_identifier],
                },
            )
            if _backend_frame_contains_asset_snapshot_key(
                existing_frame,
                time_index=time_index,
                unique_identifier=unique_identifier,
            ):
                self._log_existing_asset_snapshot_key(
                    time_index=time_index,
                    unique_identifier=unique_identifier,
                )
                existing_keys.append((time_index.isoformat(), unique_identifier))
        return existing_keys

    def _log_existing_asset_snapshot_key(
        self,
        *,
        time_index: pd.Timestamp,
        unique_identifier: str,
    ) -> None:
        try:
            logger = self.logger
        except Exception:
            return
        logger.info(
            "AssetSnapshot row already exists",
            time_index=time_index.isoformat(),
            unique_identifier=unique_identifier,
        )

    @classmethod
    def _default_identifier(cls) -> str:
        return markets_data_node_identifier(cls.__data_node_identifier__)

    @classmethod
    def _default_description(cls) -> str:
        return (
            "Historical asset representation snapshots keyed by time_index and "
            "unique_identifier. Use this DataNode to preserve how an asset's "
            "display attributes change over time, such as ticker, exchange code, "
            "name, or share-class grouping."
        )


class AssetPricingDetail(AssetTimestampedDataNode):
    """Timestamped provider pricing metadata keyed by asset unique_identifier."""

    __data_node_identifier__ = "asset_pricing_details"
    configuration_class = AssetPricingDetailConfiguration

    @classmethod
    def _default_identifier(cls) -> str:
        return markets_data_node_identifier(cls.__data_node_identifier__)

    @classmethod
    def _default_description(cls) -> str:
        return "Timestamped asset pricing metadata keyed by time_index and unique_identifier."


def _validate_asset_data_frame(
    frame: pd.DataFrame,
    *,
    config: AssetDataNodeConfiguration,
) -> pd.DataFrame:
    if not isinstance(config, AssetDataNodeConfiguration):
        raise TypeError("Asset DataNodes require AssetDataNodeConfiguration.")

    normalized = _reset_frame_index(frame.copy(), index_names=config.index_names)
    required_columns = {record.column_name for record in config.records}
    missing = sorted(required_columns.difference(normalized.columns))
    if missing:
        raise ValueError(f"Asset DataNode frame is missing columns: {missing!r}.")

    normalized[config.time_index_name] = normalize_datetime64_ns_utc(
        normalized[config.time_index_name]
    )
    normalized[ASSET_UNIQUE_IDENTIFIER_DIMENSION] = normalized[
        ASSET_UNIQUE_IDENTIFIER_DIMENSION
    ].astype("string")
    normalized = normalized[[record.column_name for record in config.records]]
    normalized = normalized.set_index(config.index_names)

    if normalized.index.has_duplicates:
        raise ValueError(
            f"Asset DataNode frame contains duplicate rows for {config.index_names!r}."
        )
    return normalized.sort_index()


def _asset_snapshot_index_keys(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    flat = _reset_frame_index(
        frame.copy(),
        index_names=[
            "time_index",
            ASSET_UNIQUE_IDENTIFIER_DIMENSION,
        ],
    )
    flat["time_index"] = normalize_datetime64_ns_utc(flat["time_index"])
    keys = flat[
        [
            "time_index",
            ASSET_UNIQUE_IDENTIFIER_DIMENSION,
        ]
    ].drop_duplicates()
    return [
        (
            normalize_timestamp_ns_utc(row["time_index"]),
            str(row[ASSET_UNIQUE_IDENTIFIER_DIMENSION]),
        )
        for _, row in keys.iterrows()
    ]


def _backend_frame_contains_asset_snapshot_key(
    frame: pd.DataFrame,
    *,
    time_index: pd.Timestamp,
    unique_identifier: str,
) -> bool:
    if frame is None or frame.empty:
        return False

    flat = _reset_frame_index(
        frame.copy(),
        index_names=[
            "time_index",
            ASSET_UNIQUE_IDENTIFIER_DIMENSION,
        ],
    )
    if "time_index" not in flat.columns:
        return True
    if ASSET_UNIQUE_IDENTIFIER_DIMENSION not in flat.columns:
        return True

    flat["time_index"] = normalize_datetime64_ns_utc(flat["time_index"])
    flat[ASSET_UNIQUE_IDENTIFIER_DIMENSION] = flat[
        ASSET_UNIQUE_IDENTIFIER_DIMENSION
    ].astype(str)
    return (
        (flat["time_index"] == time_index)
        & (flat[ASSET_UNIQUE_IDENTIFIER_DIMENSION] == unique_identifier)
    ).any()


def _snapshot_items(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
) -> list[AssetSnapshotInput]:
    if isinstance(snapshots, Mapping) or not isinstance(snapshots, Sequence):
        return [snapshots]
    if isinstance(snapshots, (str, bytes)):
        return [snapshots]
    return list(snapshots)


def _snapshot_payload(snapshot: AssetSnapshotInput) -> dict[str, Any]:
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    return {
        field_name: getattr(snapshot, field_name)
        for field_name in (
            "time_index",
            "unique_identifier",
            "name",
            "ticker",
            "exchange_code",
            "asset_ticker_group_id",
        )
        if hasattr(snapshot, field_name)
    }


def _required_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Asset snapshots require a non-empty {field_name}.")
    return value.strip()


def _required_snapshot_time(payload: Mapping[str, Any]) -> Any:
    value = payload.get("time_index")
    if value is None:
        raise ValueError("Asset snapshots require a per-row time_index.")
    try:
        return normalize_timestamp_ns_utc(value)
    except Exception as exc:
        raise ValueError(f"Invalid AssetSnapshot time_index: {value!r}.") from exc


def _optional_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if value is None:
        return ""
    return str(value)


def _reset_frame_index(
    frame: pd.DataFrame,
    *,
    index_names: list[str],
) -> pd.DataFrame:
    missing_index_names = [
        index_name
        for index_name in index_names
        if index_name not in frame.columns and index_name not in (frame.index.names or [])
    ]
    if missing_index_names:
        raise ValueError(f"Asset DataNode frame is missing index columns: {missing_index_names!r}.")
    has_required_index = any(name in index_names for name in frame.index.names)
    return frame.reset_index() if has_required_index else frame


def _schema_bootstrap_value(dtype: str) -> Any:
    if dtype == "datetime64[ns, UTC]":
        return ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX
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
    "ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX",
    "ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER",
    "AssetDataNodeConfiguration",
    "AssetPricingDetail",
    "AssetPricingDetailConfiguration",
    "AssetSnapshot",
    "AssetSnapshotConfiguration",
    "AssetSnapshotInput",
    "AssetTimestampedDataNode",
    "AssetTimestampedFrameMixin",
    "asset_pricing_detail_records",
    "asset_snapshot_records",
    "asset_time_index_record",
    "asset_unique_identifier_record",
]
