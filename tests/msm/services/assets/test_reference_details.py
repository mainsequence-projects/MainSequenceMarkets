from __future__ import annotations

import os
from typing import Any

import pytest

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.models import AssetTable
from msm.services import asset_reference_details


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_asset_reference_details_builds_latest_snapshot_join() -> None:
    calls: list[dict[str, Any]] = []

    def executor(statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        calls.append(
            {
                "sql": _compiled_sql(statement),
                "models": models,
            }
        )
        return {
            "rows": [
                {
                    "asset_uid": "asset-a-uid",
                    "asset_identifier": "asset-a",
                    "asset_type": "equity",
                    "snapshot_time": "2026-01-02T00:00:00Z",
                    "ticker": "AAA",
                },
                {
                    "asset_uid": "asset-b-uid",
                    "asset_identifier": "asset-b",
                    "asset_type": "bond",
                    "snapshot_time": "2026-01-03T00:00:00Z",
                    "ticker": "BBB",
                },
            ]
        }

    rows = asset_reference_details(
        ["asset-b", "asset-a", "asset-b"],
        executor=executor,
    )

    assert [row["asset_identifier"] for row in rows] == ["asset-b", "asset-a"]
    assert rows[0]["ticker"] == "BBB"
    assert calls[0]["models"] == (AssetTable, AssetSnapshotsStorage)
    sql = calls[0]["sql"].lower()
    assert "max(" in sql
    assert "outer join" in sql
    assert "asset-a" in calls[0]["sql"]
    assert "asset-b" in calls[0]["sql"]


def test_asset_reference_details_can_read_identity_without_snapshots() -> None:
    calls: list[dict[str, Any]] = []

    def executor(statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        calls.append(
            {
                "sql": _compiled_sql(statement),
                "models": models,
            }
        )
        return {
            "rows": [
                {
                    "asset_uid": "asset-uid",
                    "asset_identifier": "asset-a",
                    "asset_type": "equity",
                    "snapshot_time": None,
                }
            ]
        }

    rows = asset_reference_details("asset-a", latest_snapshot=False, executor=executor)

    assert rows[0]["asset_identifier"] == "asset-a"
    assert calls[0]["models"] == (AssetTable,)
    assert "max(" not in calls[0]["sql"].lower()


def test_asset_reference_details_require_explicit_execution_boundary() -> None:
    with pytest.raises(ValueError, match="repository_context"):
        asset_reference_details("asset-a")


def test_asset_reference_details_validate_identifiers() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        asset_reference_details(["asset-a", ""], executor=lambda _statement, _models: [])

    assert asset_reference_details([], executor=lambda _statement, _models: []) == []
