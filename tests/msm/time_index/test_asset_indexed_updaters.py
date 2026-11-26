from __future__ import annotations

import datetime
import importlib
import logging
import os
from types import SimpleNamespace

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from metatables import UpdateStatistics
from metatables.updaters.runner import UpdateRunner

from msm.time_index.accounts import AccountHoldings
import msm.time_index.execution as execution_module
from msm.time_index.assets import (
    AssetSnapshot,
)
from msm.time_index.assets.asset_indexed import (
    ASSET_IDENTIFIER_DIMENSION,
    AssetIndexedUpdater,
    AssetIndexedUpdaterConfiguration,
)
from msm.time_index.execution import (
    ExecutionUpdaterConfiguration,
)
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.time_index.execution.storage import (
    OrderEventsStorage,
    OrdersStorage,
    TradesStorage,
)
from msm.models import AccountTable, AssetTable, OrderManagerTable, OrderTable
from msm.settings import (
    ASSET_IDENTIFIER_DIMENSION as SETTINGS_ASSET_DIMENSION,
)


def test_asset_identity_dimension_is_shared_with_settings() -> None:
    assert ASSET_IDENTIFIER_DIMENSION == SETTINGS_ASSET_DIMENSION
    assert AssetIndexedUpdater.asset_identity_dimension == SETTINGS_ASSET_DIMENSION


def test_market_data_node_compatibility_names_are_removed() -> None:
    asset_indexed_module = importlib.import_module("msm.time_index.assets.asset_indexed")
    asset_updaters_module = importlib.import_module("msm.time_index.assets")

    legacy_node_name = "Market" + "TimeIndexTableUpdater"
    legacy_config_name = legacy_node_name + "Configuration"
    legacy_module_name = "msm." + "markets_" + "data_node"

    assert not hasattr(asset_indexed_module, legacy_node_name)
    assert not hasattr(asset_indexed_module, legacy_config_name)
    assert not hasattr(asset_updaters_module, "AssetPricingDetail")
    assert not hasattr(asset_updaters_module, "AssetPricingDetailConfiguration")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.time_index.asset_indexed")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.asset_indexed_data_node")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_module_name)


def test_removed_foreign_key_helpers_are_gone() -> None:
    """ADR 0017 superseded the SourceTableForeignKey helpers (Decision §4)."""

    asset_indexed_module = importlib.import_module("msm.time_index.assets.asset_indexed")

    assert not hasattr(asset_indexed_module, "asset_unique_identifier_foreign_key")
    assert not hasattr(asset_indexed_module, "asset_indexed_foreign_keys")


def test_root_asset_scope_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.asset_scope")


def test_holdings_mock_frame_aliases_are_not_public_api() -> None:
    assert not hasattr(AccountHoldings, "build_mock_account_frame")


def test_execution_schema_constants_and_config_fields_are_removed() -> None:
    for name in (
        "ORDERS_INDEX_NAMES",
        "ORDERS_TIME_INDEX_NAME",
        "ORDER_EVENTS_INDEX_NAMES",
        "ORDER_EVENTS_TIME_INDEX_NAME",
        "TRADES_INDEX_NAMES",
        "TRADES_TIME_INDEX_NAME",
        "EXECUTION_ERRORS_INDEX_NAMES",
        "EXECUTION_ERRORS_TIME_INDEX_NAME",
    ):
        assert not hasattr(execution_module, name)

    assert "index_names" not in ExecutionUpdaterConfiguration.model_fields
    assert "time_index_name" not in ExecutionUpdaterConfiguration.model_fields


def test_execution_error_data_node_is_removed() -> None:
    assert not hasattr(execution_module, "ExecutionErrors")
    assert not hasattr(importlib.import_module("msm.time_index"), "ExecutionErrors")


def test_execution_storage_keys_to_the_order_account_and_asset() -> None:
    """ADR 0064: an order is its Order row; its state rows, events and trades reference it."""

    expected_foreign_keys = [
        (OrderTable.__table__.c.account_identifier, AccountTable.__table__.c.unique_identifier),
        (OrderTable.__table__.c.asset_identifier, AssetTable.__table__.c.unique_identifier),
        (
            OrderTable.__table__.c.order_manager_identifier,
            OrderManagerTable.__table__.c.unique_identifier,
        ),
        (OrdersStorage.__table__.c.order_uid, OrderTable.__table__.c.uid),
        (OrderEventsStorage.__table__.c.order_uid, OrderTable.__table__.c.uid),
        (TradesStorage.__table__.c.account_identifier, AccountTable.__table__.c.unique_identifier),
        (TradesStorage.__table__.c.asset_identifier, AssetTable.__table__.c.unique_identifier),
        (
            TradesStorage.__table__.c.commission_asset_identifier,
            AssetTable.__table__.c.unique_identifier,
        ),
        (
            TradesStorage.__table__.c.settlement_asset_identifier,
            AssetTable.__table__.c.unique_identifier,
        ),
    ]

    for storage_column, target_column in expected_foreign_keys:
        assert any(
            foreign_key.column is target_column and foreign_key.ondelete == "RESTRICT"
            for foreign_key in storage_column.foreign_keys
        )
    (trade_order_key,) = [
        key
        for key in TradesStorage.__table__.foreign_key_constraints
        if "order_uid" in key.column_keys
    ]
    assert trade_order_key.column_keys == ["order_uid", "account_identifier", "asset_identifier"]
    assert [element.column for element in trade_order_key.elements] == [
        OrderTable.__table__.c.uid,
        OrderTable.__table__.c.account_identifier,
        OrderTable.__table__.c.asset_identifier,
    ]
    assert trade_order_key.ondelete == "RESTRICT"
    assert OrdersStorage.__index_names__ == ["order_time", "order_uid"]
    assert OrderEventsStorage.__index_names__ == ["event_time", "order_uid"]
    assert TradesStorage.__index_names__ == ["trade_time", "trade_identifier"]


def test_core_execution_storage_does_not_carry_fund_identifier() -> None:
    assert "fund_identifier" not in OrdersStorage.__table__.c
    assert "fund_identifier" not in TradesStorage.__table__.c


def test_asset_indexed_node_normalizes_asset_scope_helpers() -> None:
    assets = [
        "BTC",
        {"asset_identifier": "ETH"},
        SimpleNamespace(asset_identifier="SOL"),
        {"metadata": {"asset_identifier": "ADA"}},
    ]

    assert AssetSnapshot.validate_asset_list(assets) == assets
    assert AssetSnapshot.asset_unique_identifiers(assets) == [
        "BTC",
        "ETH",
        "SOL",
        "ADA",
    ]
    assert AssetSnapshot.asset_dimension_filters(assets) == {
        ASSET_IDENTIFIER_DIMENSION: ["BTC", "ETH", "SOL", "ADA"]
    }
    assert AssetSnapshot.asset_dimension_filters(None) is None


@pytest.mark.parametrize(
    "asset",
    [
        {"unique_identifier": "SOL"},
        {"asset_identifier": "SOL", "unique_identifier": "legacy-sol"},
    ],
)
def test_asset_indexed_node_rejects_unique_identifier_mapping_key(asset: dict) -> None:
    with pytest.raises(
        TypeError,
        match="must use 'asset_identifier'.*must not contain 'unique_identifier'",
    ):
        AssetSnapshot.validate_asset_list([asset])


def test_asset_indexed_node_rejects_unique_identifier_object_attribute() -> None:
    with pytest.raises(TypeError, match="objects with 'asset_identifier'"):
        AssetSnapshot.validate_asset_list([SimpleNamespace(unique_identifier="SOL")])


def test_asset_indexed_last_observation_preserves_sdk_dimension_query_contract() -> None:
    calls: list[dict] = []

    class Manager:
        def get_last_observation(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame()

    class TestAssetNode(AssetIndexedUpdater):
        @classmethod
        def _required_output_table(cls):
            return AssetSnapshotsStorage

        def dependencies(self):
            return {}

        def update(self):
            return pd.DataFrame()

    node = object.__new__(TestAssetNode)
    node._update_manager = Manager()
    node.asset_list = ["BTC", "ETH"]
    index_coordinates = [
        {"signal_uid": "signal-a", ASSET_IDENTIFIER_DIMENSION: "BTC"},
    ]
    dimension_range_map = [
        {
            "coordinate": {
                "signal_uid": "signal-a",
                ASSET_IDENTIFIER_DIMENSION: "BTC",
            },
            "end_date": "2026-01-03T00:00:00Z",
        },
    ]

    result = node.get_last_observation(
        dimension_filters={"signal_uid": ["signal-a"]},
        index_coordinates=index_coordinates,
        dimension_range_map=dimension_range_map,
    )

    assert result.empty
    assert calls == [
        {
            "dimension_filters": {
                "signal_uid": ["signal-a"],
                ASSET_IDENTIFIER_DIMENSION: ["BTC", "ETH"],
            },
            "index_coordinates": index_coordinates,
            "dimension_range_map": dimension_range_map,
        }
    ]

    calls.clear()
    node.get_last_observation(asset_list=["ETH"])
    assert calls == [
        {
            "dimension_filters": {ASSET_IDENTIFIER_DIMENSION: ["ETH"]},
            "index_coordinates": None,
            "dimension_range_map": None,
        }
    ]


def test_asset_indexed_node_rejects_duplicate_or_empty_asset_scope() -> None:
    with pytest.raises(ValueError):
        AssetSnapshot.validate_asset_list(["BTC", "BTC"])
    with pytest.raises(ValueError):
        AssetSnapshot.validate_asset_list([])


def test_asset_indexed_configuration_only_carries_update_scope() -> None:
    config = AssetIndexedUpdaterConfiguration()

    assert config.asset_list is None
    assert "asset_list" in AssetIndexedUpdaterConfiguration.model_fields
    # Storage-first: schema/FK fields no longer live on the configuration.
    assert "records" not in AssetIndexedUpdaterConfiguration.model_fields
    assert "node_metadata" not in AssetIndexedUpdaterConfiguration.model_fields
    assert "foreign_keys" not in AssetIndexedUpdaterConfiguration.model_fields


_TABLE_PROGRESS = datetime.datetime(2026, 11, 20, tzinfo=datetime.UTC)
_OFFSET_START = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class _ScopedAssetNode(AssetIndexedUpdater):
    OFFSET_START = _OFFSET_START

    @classmethod
    def _required_output_table(cls):
        return AssetSnapshotsStorage

    def dependencies(self):
        return {}

    def update(self):
        return pd.DataFrame()


def _scoped_node(asset_list: list[str]) -> _ScopedAssetNode:
    node = object.__new__(_ScopedAssetNode)
    node.asset_list = asset_list
    node._output_table = AssetSnapshotsStorage
    node._logger = logging.getLogger(__name__)
    node.update_statistics = None
    return node


def _shared_table_statistics() -> UpdateStatistics:
    """A table two nodes write: one wrote A, another wrote B."""

    progress = {"A": _TABLE_PROGRESS, "B": _TABLE_PROGRESS}
    return UpdateStatistics(
        global_index_progress={"max": _TABLE_PROGRESS},
        index_progress=dict(progress),
        index_min=dict(progress),
    )


def _statistics_seen_by_update(node: _ScopedAssetNode) -> UpdateStatistics:
    """Start ``node`` the way every run without an override does, and return what
    ``update()`` sees: MetaTables' runner hands it the table's statistics (#144)."""

    seen: list[UpdateStatistics] = []
    runner = UpdateRunner([node], update_tree=False)
    runner._update_local = lambda table_update_run: seen.append(node.update_statistics)
    runner._execute_started_update(
        SimpleNamespace(update_statistics=_shared_table_statistics()),
        override_update_stats=None,
    )
    return seen[0]


def test_a_run_gives_an_asset_indexed_node_only_its_own_assets_progress() -> None:
    statistics = _statistics_seen_by_update(_scoped_node(["A", "C"]))

    starts = {
        asset: date_info["start_date"]
        for asset, date_info in statistics.get_identity_range_map_great_or_equal().items()
    }
    # B belongs to another node; C is not in the table yet.
    assert starts == {"A": _TABLE_PROGRESS, "C": _OFFSET_START}
    assert statistics.index_min == {"A": _TABLE_PROGRESS, "C": _OFFSET_START}
    assert not statistics.are_all_identities_on_fallback_date


def test_a_node_whose_assets_the_shared_table_lacks_starts_them_all_at_offset_start() -> None:
    statistics = _statistics_seen_by_update(_scoped_node(["C", "D"]))

    assert statistics.index_progress == {"C": _OFFSET_START, "D": _OFFSET_START}
    assert statistics.are_all_identities_on_fallback_date
