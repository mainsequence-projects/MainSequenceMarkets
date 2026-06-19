from __future__ import annotations

import datetime as dt
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.assets import (
    AssetSnapshot,
    AssetSnapshotConfiguration,
)
from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.services.assets.openfigi import build_asset_snapshot_frame_from_openfigi_result
from msm_pricing.data_nodes import AssetPricingDetail, AssetPricingDetailConfiguration
from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage


def test_asset_snapshot_build_frame_validates_storage_index() -> None:
    frame = AssetSnapshot.build_frame(
        [
            {
                "asset_identifier": "BBG000B9XRY4",
                "time_index": dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
                "name": "APPLE INC",
                "ticker": "AAPL",
                "exchange_code": "US",
                "asset_ticker_group_id": "BBG001S5N8V8",
            }
        ],
    )

    assert list(frame.index.names) == list(AssetSnapshotsStorage.__index_names__)
    row = frame.reset_index().iloc[0]
    assert row["asset_identifier"] == "BBG000B9XRY4"
    assert row["ticker"] == "AAPL"
    assert "venue_specific_properties" not in frame.reset_index().columns
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"


def test_asset_snapshot_resolves_storage_first_surface(monkeypatch) -> None:
    registered_identifier = "registered.asset-snapshots"
    monkeypatch.setattr(
        AssetSnapshotsStorage,
        "get_identifier",
        classmethod(lambda _cls: registered_identifier),
    )

    assert AssetSnapshot._required_storage_table() is AssetSnapshotsStorage
    assert "__data_node_identifier__" not in AssetSnapshot.__dict__
    assert AssetSnapshot._default_identifier() == registered_identifier
    assert AssetSnapshot._default_description() == AssetSnapshotsStorage.__metatable_description__
    assert issubclass(AssetSnapshot.configuration_class, AssetSnapshotConfiguration)
    # Storage class is the single source of the snapshot column contract.
    assert [column.name for column in AssetSnapshotsStorage.__table__.columns] == [
        "time_index",
        "asset_identifier",
        "name",
        "ticker",
        "exchange_code",
        "asset_ticker_group_id",
    ]


def test_asset_pricing_detail_resolves_storage_first_surface() -> None:
    assert AssetPricingDetail._required_storage_table() is AssetPricingDetailsStorage
    assert issubclass(
        AssetPricingDetail.configuration_class,
        AssetPricingDetailConfiguration,
    )
    assert [column.name for column in AssetPricingDetailsStorage.__table__.columns] == [
        "time_index",
        "asset_identifier",
        "instrument_dump",
        "instrument_type",
        "serialization_format",
        "pricing_package_version",
        "source",
        "metadata",
    ]


def test_asset_snapshot_build_frame_is_easy_entrypoint() -> None:
    frame = AssetSnapshot.build_frame(
        {
            "time_index": "2026-05-25T00:00:00Z",
            "asset_identifier": "example-asset-eth",
            "ticker": "ETH",
        },
    )

    assert frame.index.get_level_values("asset_identifier").tolist() == ["example-asset-eth"]


def test_asset_snapshot_set_snapshots_can_disable_backend_verify() -> None:
    node = object.__new__(AssetSnapshot)
    node.set_frame = Mock(return_value=node)

    result = AssetSnapshot.set_snapshots(
        node,
        {
            "time_index": "2026-05-25T00:00:00Z",
            "asset_identifier": "example-asset-eth",
        },
        verify_existing=False,
    )

    assert result is node
    assert node._verify_existing_snapshot_index is False
    frame = node.set_frame.call_args.args[0]
    assert frame.index.get_level_values("asset_identifier").tolist() == ["example-asset-eth"]


def test_asset_snapshot_frame_rejects_blank_identifier() -> None:
    with pytest.raises(ValueError, match="non-empty asset_identifier"):
        AssetSnapshot.build_frame(
            {
                "time_index": "2026-05-25T00:00:00Z",
                "asset_identifier": " ",
            }
        )


def test_asset_snapshot_frame_requires_row_time_index() -> None:
    with pytest.raises(ValueError, match="per-row time_index"):
        AssetSnapshot.build_frame({"asset_identifier": "BTC"})


def test_asset_snapshot_frame_rejects_duplicate_index_rows() -> None:
    time_index = pd.Timestamp("2026-05-25T00:00:00Z")

    with pytest.raises(ValueError, match="duplicate rows"):
        AssetSnapshot.build_frame(
            [
                {"time_index": time_index, "asset_identifier": "BTC"},
                {"time_index": time_index, "asset_identifier": "BTC"},
            ],
        )


def test_asset_snapshot_existing_backend_index_keys_uses_one_compiled_query(monkeypatch) -> None:
    first_time = pd.Timestamp("2026-05-25T00:00:00Z")
    second_time = pd.Timestamp("2026-05-26T00:00:00Z")
    frame = AssetSnapshot.build_frame(
        [
            {"time_index": first_time, "asset_identifier": "asset-a"},
            {"time_index": second_time, "asset_identifier": "asset-b"},
        ]
    )

    node = object.__new__(AssetSnapshot)
    node._storage_table = AssetSnapshotsStorage
    node._local_persist_manager = SimpleNamespace(storage_metadata=object())
    node._log_existing_asset_snapshot_key = Mock()
    node.get_df_between_dates = Mock(side_effect=AssertionError("per-key reads are too slow"))

    bind_meta_table = Mock()
    compile_statement = Mock(return_value=object())
    execute_operation = Mock(
        return_value={
            "rows": [
                {
                    "time_index": second_time,
                    "asset_identifier": "asset-b",
                }
            ]
        }
    )
    monkeypatch.setattr(AssetSnapshotsStorage, "_bind_meta_table", bind_meta_table)
    monkeypatch.setattr(
        "msm.data_nodes.assets.snapshots.compile_markets_statement",
        compile_statement,
    )
    monkeypatch.setattr(
        "msm.data_nodes.assets.snapshots.execute_markets_operation",
        execute_operation,
    )

    existing_keys = node.existing_backend_index_keys(frame)

    assert existing_keys == [(second_time.isoformat(), "asset-b")]
    bind_meta_table.assert_called_once_with(node.local_persist_manager.storage_metadata)
    compile_statement.assert_called_once()
    execute_operation.assert_called_once()
    node.get_df_between_dates.assert_not_called()


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
    assert row["asset_identifier"] == "BBG000B9XRY4"
    assert row["ticker"] == "AAPL"
    assert "venue_specific_properties" not in frame.reset_index().columns


@pytest.mark.skip(reason="requires platform backend (Stage 5 registration)")
def test_asset_snapshot_set_snapshots_and_update() -> None:
    """set_snapshots + update + backend duplicate checks need a registered node."""

    node = AssetSnapshot()
    node.set_snapshots(
        {
            "time_index": dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
            "asset_identifier": "example-asset-btc",
            "ticker": "BTC",
        },
    )
    assert list(node.update().index.names) == ["time_index", "asset_identifier"]
