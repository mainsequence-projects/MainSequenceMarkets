from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from msm.data_nodes.assets import AssetDataNodeConfiguration, AssetSnapshot


AssetSnapshotInput = Mapping[str, Any] | Any


def build_asset_snapshot_frame(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    *,
    time_index: dt.datetime | pd.Timestamp | str | None = None,
    config: AssetDataNodeConfiguration | None = None,
) -> pd.DataFrame:
    """Build a validated `AssetSnapshot` frame from row-like inputs."""

    rows = []
    effective_time = time_index or dt.datetime.now(dt.UTC)
    for snapshot in _snapshot_items(snapshots):
        payload = _snapshot_payload(snapshot)
        unique_identifier = _required_snapshot_string(payload, "unique_identifier")
        rows.append(
            {
                "time_index": payload.get("time_index", effective_time),
                "unique_identifier": unique_identifier,
                "name": _optional_snapshot_string(payload, "name"),
                "ticker": _optional_snapshot_string(payload, "ticker"),
                "exchange_code": _optional_snapshot_string(payload, "exchange_code"),
                "asset_ticker_group_id": _optional_snapshot_string(
                    payload,
                    "asset_ticker_group_id",
                ),
                "venue_specific_properties": _snapshot_json_value(
                    payload.get("venue_specific_properties")
                ),
            }
        )

    if not rows:
        raise ValueError("At least one asset snapshot is required.")
    return AssetSnapshot.validate_frame(pd.DataFrame(rows), config=config)


def build_asset_snapshot_node(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    *,
    time_index: dt.datetime | pd.Timestamp | str | None = None,
    config: AssetDataNodeConfiguration | None = None,
    identifier: str | None = None,
    description: str | None = None,
    hash_namespace: str | None = None,
    test_node: bool = False,
) -> AssetSnapshot:
    """Build an `AssetSnapshot` DataNode instance with a validated frame."""

    if config is not None and (identifier is not None or description is not None):
        raise ValueError("Pass either config or identifier/description, not both.")

    resolved_config = config or AssetSnapshot.default_config(
        identifier=identifier,
        description=description,
    )
    frame = build_asset_snapshot_frame(
        snapshots,
        time_index=time_index,
        config=resolved_config,
    )
    return AssetSnapshot(
        config=resolved_config,
        hash_namespace=hash_namespace,
        test_node=test_node,
    ).set_frame(frame)


def update_asset_snapshot_frame(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    *,
    time_index: dt.datetime | pd.Timestamp | str | None = None,
    config: AssetDataNodeConfiguration | None = None,
    identifier: str | None = None,
    description: str | None = None,
    hash_namespace: str | None = None,
    test_node: bool = False,
) -> pd.DataFrame:
    """Return the frame produced by the configured `AssetSnapshot.update()` call."""

    node = build_asset_snapshot_node(
        snapshots,
        time_index=time_index,
        config=config,
        identifier=identifier,
        description=description,
        hash_namespace=hash_namespace,
        test_node=test_node,
    )
    return node.update()


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
            "venue_specific_properties",
        )
        if hasattr(snapshot, field_name)
    }


def _required_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Asset snapshots require a non-empty {field_name}.")
    return value.strip()


def _optional_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if value is None:
        return ""
    return str(value)


def _snapshot_json_value(value: Any) -> dict[str, Any] | list[Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    raise ValueError("venue_specific_properties must be a mapping, list, or null.")


__all__ = [
    "AssetSnapshotInput",
    "build_asset_snapshot_frame",
    "build_asset_snapshot_node",
    "update_asset_snapshot_frame",
]
