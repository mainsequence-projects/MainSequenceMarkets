from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.assets import AssetSnapshot
from msm.services.asset_snapshots import (
    build_asset_snapshot_frame,
    build_asset_snapshot_node,
    update_asset_snapshot_frame,
)
from msm.services.assets.openfigi import build_asset_snapshot_frame_from_openfigi_result


@pytest.fixture
def offline_asset_snapshot_node(monkeypatch):
    monkeypatch.setattr(AssetSnapshot, "set_data_source", lambda self, data_source=None: None)


def test_build_asset_snapshot_frame_validates_datanode_index() -> None:
    frame = build_asset_snapshot_frame(
        [
            {
                "unique_identifier": "BBG000B9XRY4",
                "name": "APPLE INC",
                "ticker": "AAPL",
                "exchange_code": "US",
                "asset_ticker_group_id": "BBG001S5N8V8",
                "venue_specific_properties": {"source": "unit-test"},
            }
        ],
        time_index=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
    )

    assert list(frame.index.names) == AssetSnapshot.default_config().index_names
    row = frame.reset_index().iloc[0]
    assert row["unique_identifier"] == "BBG000B9XRY4"
    assert row["venue_specific_properties"] == {"source": "unit-test"}


def test_build_asset_snapshot_node_uses_custom_identifier(offline_asset_snapshot_node) -> None:
    node = build_asset_snapshot_node(
        {"unique_identifier": "example-asset-btc", "ticker": "BTC"},
        identifier="examples.mainsequence.markets.asset_snapshots",
        hash_namespace="examples",
    )

    assert (
        node.config.node_metadata.identifier
        == "examples.mainsequence.markets.asset_snapshots"
    )
    assert node.hash_namespace == "examples"
    assert list(node.update().index.names) == ["time_index", "unique_identifier"]


def test_update_asset_snapshot_frame_is_easy_entrypoint(offline_asset_snapshot_node) -> None:
    frame = update_asset_snapshot_frame(
        {"unique_identifier": "example-asset-eth", "ticker": "ETH"},
        time_index="2026-05-25T00:00:00Z",
    )

    assert frame.index.get_level_values("unique_identifier").tolist() == [
        "example-asset-eth"
    ]


def test_asset_snapshot_frame_rejects_blank_identifier() -> None:
    with pytest.raises(ValueError, match="non-empty unique_identifier"):
        build_asset_snapshot_frame({"unique_identifier": " "})


def test_asset_snapshot_frame_rejects_duplicate_index_rows() -> None:
    time_index = pd.Timestamp("2026-05-25T00:00:00Z")

    with pytest.raises(ValueError, match="duplicate rows"):
        build_asset_snapshot_frame(
            [
                {"time_index": time_index, "unique_identifier": "BTC"},
                {"time_index": time_index, "unique_identifier": "BTC"},
            ],
        )


def test_openfigi_snapshot_builder_uses_generic_entrypoint() -> None:
    frame = build_asset_snapshot_frame_from_openfigi_result(
        {
            "figi": "BBG000B9XRY4",
            "shareClassFIGI": "BBG001S5N8V8",
            "ticker": "AAPL",
            "name": "APPLE INC",
            "exchCode": "US",
        },
        time_index=dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
    )

    row = frame.reset_index().iloc[0]
    assert row["unique_identifier"] == "BBG000B9XRY4"
    assert row["venue_specific_properties"]["openfigi"]["ticker"] == "AAPL"
