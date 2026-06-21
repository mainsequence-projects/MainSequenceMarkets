from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pandas as pd
from sqlalchemy import select

from msm.data_nodes.utils.time import normalize_datetime64_ns_utc, normalize_timestamp_ns_utc
from msm.data_nodes.assets.asset_indexed import (
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.data_nodes.utils.stamped import (
    StampedDataNodeConfiguration,
    StampedFrameMixin,
    reset_frame_index,
)
from msm.settings import ASSET_IDENTIFIER_DIMENSION

AssetSnapshotInput = Mapping[str, Any] | Any


class AssetDataNodeConfiguration(StampedDataNodeConfiguration, AssetIndexedDataNodeConfiguration):
    """Configuration for timestamped asset DataNodes.

    Storage-first: the column schema, index names, and the canonical
    ``Asset.unique_identifier`` foreign key live on the ``storage_table``
    (an ``AssetSnapshotsStorage``-style ``PlatformTimeIndexMetaTable`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = ASSET_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Asset DataNode"


class AssetSnapshotConfiguration(AssetDataNodeConfiguration):
    """Configuration for the canonical AssetSnapshot DataNode."""


class AssetTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped asset DataNodes."""

    configuration_class: ClassVar[type[AssetDataNodeConfiguration]] = AssetDataNodeConfiguration
    frame_label: ClassVar[str] = "Asset DataNode"


class AssetTimestampedDataNode(AssetTimestampedFrameMixin, AssetIndexedDataNode):
    """Base asset-indexed DataNode for timestamped facts keyed by asset_identifier."""

    def dependencies(self) -> dict:
        return {}


class AssetSnapshot(AssetTimestampedDataNode):
    """Timestamped asset display snapshots keyed by asset_identifier."""

    configuration_class = AssetSnapshotConfiguration

    @classmethod
    def build_frame(
        cls,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    ) -> pd.DataFrame:
        """Build a validated frame from row payloads with per-row `time_index`."""

        rows = []
        for snapshot in _snapshot_items(snapshots):
            payload = _snapshot_payload(snapshot)
            asset_identifier = _required_snapshot_string(payload, ASSET_IDENTIFIER_DIMENSION)
            rows.append(
                {
                    "time_index": _required_snapshot_time(payload),
                    ASSET_IDENTIFIER_DIMENSION: asset_identifier,
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
        return cls.validate_frame(pd.DataFrame(rows))

    def set_snapshots(
        self,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
        *,
        verify_existing: bool = True,
    ) -> AssetSnapshot:
        """Validate snapshot row payloads and attach them to this DataNode."""

        self._verify_existing_snapshot_index = verify_existing
        return self.set_frame(self.build_frame(snapshots))

    def _execute_local_update(self, historical_update: Any):
        self._verify_backend_snapshot_index = True
        try:
            return super()._execute_local_update(historical_update=historical_update)
        finally:
            self._verify_backend_snapshot_index = False

    def update(self) -> pd.DataFrame:
        frame = super().update()
        if getattr(self, "_verify_backend_snapshot_index", False) and getattr(
            self,
            "_verify_existing_snapshot_index",
            True,
        ):
            self.verify_backend_index_available(frame)
        return frame

    def verify_backend_index_available(self, frame: pd.DataFrame) -> None:
        """Raise when any `(time_index, asset_identifier)` key already exists."""

        existing_keys = self.existing_backend_index_keys(frame)
        if existing_keys:
            formatted_keys = ", ".join(
                f"({time_index}, {unique_identifier})"
                for time_index, unique_identifier in existing_keys
            )
            raise ValueError(
                "AssetSnapshot rows already exist for "
                f"(time_index, asset_identifier): {formatted_keys}."
            )

    def existing_backend_index_keys(self, frame: pd.DataFrame) -> list[tuple[str, str]]:
        """Return existing backend keys that would collide with `frame`."""

        from msm.repositories.base import (
            MarketsRepositoryContext,
            compile_markets_statement,
            execute_markets_operation,
        )

        candidate_keys = _asset_snapshot_index_keys(
            self.validate_frame(frame, storage_table=self.storage_table)
        )
        if not candidate_keys:
            return []

        candidate_key_set = set(candidate_keys)
        times = sorted({time_index for time_index, _ in candidate_key_set})
        asset_identifiers = sorted({asset_identifier for _, asset_identifier in candidate_key_set})

        AssetSnapshotsStorage._bind_meta_table(self.local_persist_manager.storage_metadata)
        context = MarketsRepositoryContext()
        statement = (
            select(
                AssetSnapshotsStorage.time_index.label("time_index"),
                AssetSnapshotsStorage.asset_identifier.label(ASSET_IDENTIFIER_DIMENSION),
            )
            .where(
                AssetSnapshotsStorage.time_index >= times[0].to_pydatetime(),
                AssetSnapshotsStorage.time_index <= times[-1].to_pydatetime(),
                AssetSnapshotsStorage.asset_identifier.in_(asset_identifiers),
            )
        )
        operation = compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[AssetSnapshotsStorage],
            access="read",
        )
        result = execute_markets_operation(operation, context=context)
        existing_key_set = {
            (
                normalize_timestamp_ns_utc(row["time_index"]),
                str(row[ASSET_IDENTIFIER_DIMENSION]),
            )
            for row in _operation_result_rows(result)
            if row.get("time_index") is not None
            and row.get(ASSET_IDENTIFIER_DIMENSION) is not None
        }
        existing_keys = sorted(candidate_key_set & existing_key_set)
        for time_index, unique_identifier in existing_keys:
            self._log_existing_asset_snapshot_key(
                time_index=time_index,
                unique_identifier=unique_identifier,
            )
        return [
            (time_index.isoformat(), unique_identifier)
            for time_index, unique_identifier in existing_keys
        ]

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
    def _required_storage_table(cls) -> type[AssetSnapshotsStorage]:
        return AssetSnapshotsStorage


def _asset_snapshot_index_keys(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    flat = reset_frame_index(
        frame.copy(),
        index_names=[
            "time_index",
            ASSET_IDENTIFIER_DIMENSION,
        ],
    )
    flat["time_index"] = normalize_datetime64_ns_utc(flat["time_index"])
    keys = flat[
        [
            "time_index",
            ASSET_IDENTIFIER_DIMENSION,
        ]
    ].drop_duplicates()
    return [
        (
            normalize_timestamp_ns_utc(row["time_index"]),
            str(row[ASSET_IDENTIFIER_DIMENSION]),
        )
        for _, row in keys.iterrows()
    ]


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if key == "row":
                return [dict(value)]
            if "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    if "uid" in result:
        return [dict(result)]
    return []


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
            ASSET_IDENTIFIER_DIMENSION,
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


__all__ = [
    "AssetDataNodeConfiguration",
    "AssetSnapshot",
    "AssetSnapshotConfiguration",
    "AssetSnapshotInput",
    "AssetTimestampedDataNode",
    "AssetTimestampedFrameMixin",
]
