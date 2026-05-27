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

from mainsequence.tdag.data_nodes import SourceTableForeignKey

from msm.data_nodes.assets import (
    AssetSnapshot,
    AssetSnapshotConfiguration,
)
from msm.services.assets.openfigi import build_asset_snapshot_frame_from_openfigi_result
from msm.settings import DEFAULT_MARKETS_NAMESPACE, markets_data_node_identifier
from msm_pricing.data_nodes import AssetPricingDetail, AssetPricingDetailConfiguration


@pytest.fixture
def offline_asset_snapshot_node(monkeypatch):
    monkeypatch.setattr(AssetSnapshot, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "asset-metatable-uid",
    )


def test_asset_snapshot_build_frame_validates_datanode_index() -> None:
    frame = AssetSnapshot.build_frame(
        [
            {
                "unique_identifier": "BBG000B9XRY4",
                "time_index": dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
                "name": "APPLE INC",
                "ticker": "AAPL",
                "exchange_code": "US",
                "asset_ticker_group_id": "BBG001S5N8V8",
            }
        ],
    )

    assert list(frame.index.names) == AssetSnapshot.default_config().index_names
    row = frame.reset_index().iloc[0]
    assert row["unique_identifier"] == "BBG000B9XRY4"
    assert "venue_specific_properties" not in frame.reset_index().columns


def test_asset_snapshot_uses_custom_identifier(offline_asset_snapshot_node) -> None:
    node = AssetSnapshot(
        config=AssetSnapshot.default_config(identifier="examples.asset_snapshots"),
        hash_namespace="examples",
    )
    node.set_snapshots(
        {
            "time_index": dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
            "unique_identifier": "example-asset-btc",
            "ticker": "BTC",
        },
    )

    assert node.config.node_metadata.identifier == "examples.asset_snapshots"
    assert node.hash_namespace == "examples"
    assert list(node.update().index.names) == ["time_index", "unique_identifier"]


def test_asset_snapshot_uses_default_markets_namespace(
    offline_asset_snapshot_node,
) -> None:
    node = AssetSnapshot()

    assert node.config.node_metadata.identifier == markets_data_node_identifier(
        AssetSnapshot.__data_node_identifier__
    )
    assert node.hash_namespace == DEFAULT_MARKETS_NAMESPACE
    assert isinstance(node.config, AssetSnapshotConfiguration)
    assert [record.column_name for record in node.config.records] == [
        "time_index",
        "unique_identifier",
        "name",
        "ticker",
        "exchange_code",
        "asset_ticker_group_id",
    ]


def test_asset_pricing_detail_uses_record_definition_configuration() -> None:
    config = AssetPricingDetail.default_config()

    assert isinstance(config, AssetPricingDetailConfiguration)
    assert [record.column_name for record in config.records] == [
        "time_index",
        "unique_identifier",
        "instrument_dump",
    ]


def test_asset_snapshot_build_frame_is_easy_entrypoint(offline_asset_snapshot_node) -> None:
    frame = AssetSnapshot.build_frame(
        {
            "time_index": "2026-05-25T00:00:00Z",
            "unique_identifier": "example-asset-eth",
            "ticker": "ETH",
        },
    )

    assert frame.index.get_level_values("unique_identifier").tolist() == [
        "example-asset-eth"
    ]


def test_asset_snapshot_frame_rejects_blank_identifier() -> None:
    with pytest.raises(ValueError, match="non-empty unique_identifier"):
        AssetSnapshot.build_frame(
            {
                "time_index": "2026-05-25T00:00:00Z",
                "unique_identifier": " ",
            }
        )


def test_asset_snapshot_frame_requires_row_time_index() -> None:
    with pytest.raises(ValueError, match="per-row time_index"):
        AssetSnapshot.build_frame({"unique_identifier": "BTC"})


def test_asset_snapshot_frame_rejects_duplicate_index_rows() -> None:
    time_index = pd.Timestamp("2026-05-25T00:00:00Z")

    with pytest.raises(ValueError, match="duplicate rows"):
        AssetSnapshot.build_frame(
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
    assert row["ticker"] == "AAPL"
    assert "venue_specific_properties" not in frame.reset_index().columns


def test_asset_snapshot_rejects_backend_duplicate_index(
    offline_asset_snapshot_node,
    monkeypatch,
) -> None:
    node = AssetSnapshot()
    frame = AssetSnapshot.build_frame(
        {
            "time_index": "2026-05-25T00:00:00Z",
            "unique_identifier": "example-asset-btc",
            "ticker": "BTC",
        },
        config=node.config,
    )
    monkeypatch.setattr(node, "get_df_between_dates", lambda **kwargs: frame)

    with pytest.raises(ValueError, match="already exist"):
        node.verify_backend_index_available(frame)


def test_asset_snapshot_logs_backend_duplicate_index(
    offline_asset_snapshot_node,
    monkeypatch,
) -> None:
    class StubLogger:
        def __init__(self) -> None:
            self.messages = []

        def info(self, message, **kwargs) -> None:
            self.messages.append((message, kwargs))

    node = AssetSnapshot()
    frame = AssetSnapshot.build_frame(
        {
            "time_index": "2026-05-25T00:00:00Z",
            "unique_identifier": "example-asset-btc",
            "ticker": "BTC",
        },
        config=node.config,
    )
    logger = StubLogger()
    node._logger = logger
    monkeypatch.setattr(node, "get_df_between_dates", lambda **kwargs: frame)

    existing_keys = node.existing_backend_index_keys(frame)

    assert existing_keys == [
        ("2026-05-25T00:00:00+00:00", "example-asset-btc"),
    ]
    assert logger.messages == [
        (
            "AssetSnapshot row already exists",
            {
                "time_index": "2026-05-25T00:00:00+00:00",
                "unique_identifier": "example-asset-btc",
            },
        )
    ]
