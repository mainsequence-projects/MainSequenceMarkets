from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field, model_validator

from mainsequence.tdag.data_nodes import RecordDefinition
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc, normalize_timestamp_ns_utc
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
    asset_indexed_foreign_keys,
)
from msm.data_nodes.utils.stamped import (
    STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX,
    STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER,
    StampedDataNodeConfiguration,
    StampedFrameMixin,
    reset_frame_index,
    schema_bootstrap_value,
    validate_stamped_data_frame,
)
from msm.settings import ASSET_UNIQUE_IDENTIFIER_DIMENSION, markets_data_node_identifier

ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER = STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER
ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX = STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX
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
        description="Asset unique identifier from the Asset MetaTable.",
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


class AssetDataNodeConfiguration(StampedDataNodeConfiguration, AssetIndexedDataNodeConfiguration):
    """Configuration for timestamped asset DataNodes."""

    reference_dimension: ClassVar[str] = ASSET_UNIQUE_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Asset DataNode"

    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", ASSET_UNIQUE_IDENTIFIER_DIMENSION],
        description="Canonical DataFrame index columns for the asset DataNode.",
    )

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


class AssetTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped asset DataNodes."""

    configuration_class: ClassVar[type[AssetDataNodeConfiguration]] = AssetDataNodeConfiguration
    frame_label: ClassVar[str] = "Asset DataNode"


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


def _validate_asset_data_frame(
    frame: pd.DataFrame,
    *,
    config: AssetDataNodeConfiguration,
) -> pd.DataFrame:
    if not isinstance(config, AssetDataNodeConfiguration):
        raise TypeError("Asset DataNodes require AssetDataNodeConfiguration.")

    return validate_stamped_data_frame(frame, config=config, frame_label="Asset DataNode")


def _asset_snapshot_index_keys(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    flat = reset_frame_index(
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

    flat = reset_frame_index(
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
    flat[ASSET_UNIQUE_IDENTIFIER_DIMENSION] = flat[ASSET_UNIQUE_IDENTIFIER_DIMENSION].astype(str)
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


_reset_frame_index = reset_frame_index
_schema_bootstrap_value = schema_bootstrap_value


__all__ = [
    "ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX",
    "ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER",
    "AssetDataNodeConfiguration",
    "AssetSnapshot",
    "AssetSnapshotConfiguration",
    "AssetSnapshotInput",
    "AssetTimestampedDataNode",
    "AssetTimestampedFrameMixin",
    "asset_snapshot_records",
    "asset_time_index_record",
    "asset_unique_identifier_record",
]
