from __future__ import annotations

import importlib
import os

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.accounts import AccountHoldings
import msm.data_nodes.execution as execution_module
from msm.data_nodes.assets import (
    AssetSnapshot,
)
from msm.data_nodes.assets.asset_indexed import (
    ASSET_UNIQUE_IDENTIFIER_DIMENSION,
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
from msm.data_nodes.execution import (
    ExecutionDataNodeConfiguration,
    OrderEvents,
    Orders,
    Trades,
)
from msm.data_nodes.storage import (
    AccountHoldingsStorage,
    AssetSnapshotsStorage,
    OrderEventsStorage,
    OrdersStorage,
    TargetPositionsStorage,
    TradesStorage,
)
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, markets_sqlalchemy_models
from msm.models.registration import markets_foreign_key_target_identifiers
from msm.settings import (
    ASSET_UNIQUE_IDENTIFIER_DIMENSION as SETTINGS_ASSET_DIMENSION,
)
from msm_pricing.data_nodes import AssetPricingDetail
from msm_pricing.data_nodes.storage import AssetPricingDetailsStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models


def test_asset_identity_dimension_is_shared_with_settings() -> None:
    assert ASSET_UNIQUE_IDENTIFIER_DIMENSION == SETTINGS_ASSET_DIMENSION
    assert AssetIndexedDataNode.asset_identity_dimension == SETTINGS_ASSET_DIMENSION


def test_market_data_node_compatibility_names_are_removed() -> None:
    asset_indexed_module = importlib.import_module("msm.data_nodes.assets.asset_indexed")
    asset_data_nodes_module = importlib.import_module("msm.data_nodes.assets")

    legacy_node_name = "Market" + "DataNode"
    legacy_config_name = legacy_node_name + "Configuration"
    legacy_module_name = "msm." + "markets_" + "data_node"

    assert not hasattr(asset_indexed_module, legacy_node_name)
    assert not hasattr(asset_indexed_module, legacy_config_name)
    assert not hasattr(asset_data_nodes_module, "AssetPricingDetail")
    assert not hasattr(asset_data_nodes_module, "AssetPricingDetailConfiguration")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.data_nodes.asset_indexed")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.asset_indexed_data_node")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_module_name)


def test_removed_foreign_key_helpers_are_gone() -> None:
    """ADR 0017 superseded the SourceTableForeignKey helpers (Decision §4)."""

    asset_indexed_module = importlib.import_module("msm.data_nodes.assets.asset_indexed")

    assert not hasattr(asset_indexed_module, "asset_unique_identifier_foreign_key")
    assert not hasattr(asset_indexed_module, "asset_indexed_foreign_keys")


def test_root_asset_scope_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.asset_scope")


@pytest.mark.parametrize(
    "node_cls",
    [
        AssetSnapshot,
        AssetPricingDetail,
        AccountHoldings,
        Orders,
        OrderEvents,
        Trades,
    ],
)
def test_asset_indexed_nodes_expose_storage_first_surface(
    node_cls,
) -> None:
    assert "__data_node_identifier__" not in node_cls.__dict__
    assert "_default_identifier" not in node_cls.__dict__
    assert "_default_description" not in node_cls.__dict__
    storage_table = node_cls._required_storage_table()
    assert node_cls._default_identifier() == storage_table.metatable_identifier()
    assert node_cls._default_description() == storage_table.__metatable_description__

    # msm storage registers through markets; pricing storage through pricing.
    registered = set(markets_sqlalchemy_models()) | set(pricing_sqlalchemy_models())
    assert storage_table in registered

    assert not hasattr(node_cls, "_required_column_dtypes_map")
    assert not hasattr(node_cls, "_required_index_names")
    assert not hasattr(node_cls, "_required_time_index_name")
    assert node_cls._column_dtypes_map_for_storage(storage_table) == storage_column_dtypes_map(
        storage_table
    )
    assert not hasattr(node_cls, "build_mock_frame")
    assert not hasattr(node_cls, "build_schema_bootstrap_frame")
    assert not hasattr(node_cls, "build_initialization_frame")


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

    assert "index_names" not in ExecutionDataNodeConfiguration.model_fields
    assert "time_index_name" not in ExecutionDataNodeConfiguration.model_fields


def test_execution_error_data_node_is_removed() -> None:
    assert not hasattr(execution_module, "ExecutionErrors")
    assert not hasattr(importlib.import_module("msm.data_nodes"), "ExecutionErrors")


def test_timestamped_storage_identifiers_use_camel_case_ts_suffix() -> None:
    assert AssetSnapshotsStorage.metatable_identifier() == "AssetSnapshotsTS"
    assert AccountHoldingsStorage.metatable_identifier() == "AccountHoldingsTS"
    assert TargetPositionsStorage.metatable_identifier() == "TargetPositionsTS"
    assert OrdersStorage.metatable_identifier() == "OrdersTS"
    assert OrderEventsStorage.metatable_identifier() == "OrderEventsTS"
    assert TradesStorage.metatable_identifier() == "TradesTS"
    assert AssetPricingDetailsStorage.metatable_identifier() == "AssetPricingDetailsTS"


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (AssetSnapshot, AssetSnapshotsStorage),
        (AssetPricingDetail, AssetPricingDetailsStorage),
    ],
)
def test_timestamped_asset_nodes_bind_their_storage_class(node_cls, storage_cls) -> None:
    assert node_cls._required_storage_table() is storage_cls
    assert storage_cls.__index_names__ == ["time_index", ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    assert ASSET_UNIQUE_IDENTIFIER_DIMENSION in {
        column.name for column in storage_cls.__table__.columns
    }


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (AssetSnapshot, AssetSnapshotsStorage),
        (AssetPricingDetail, AssetPricingDetailsStorage),
    ],
)
def test_timestamped_asset_nodes_validate_real_frames_as_datetime64_ns_utc(
    node_cls,
    storage_cls,
) -> None:
    frame = node_cls.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": "2026-05-26T00:00:00Z",
                    ASSET_UNIQUE_IDENTIFIER_DIMENSION: "asset-1",
                    **{
                        column.name: ""
                        for column in storage_cls.__table__.columns
                        if column.name
                        not in {
                            "time_index",
                            ASSET_UNIQUE_IDENTIFIER_DIMENSION,
                            "instrument_dump",
                            "metadata",
                        }
                    },
                    **{
                        column.name: {}
                        for column in storage_cls.__table__.columns
                        if column.name in {"instrument_dump", "metadata"}
                    },
                }
            ]
        )
    )

    assert list(frame.index.names) == list(storage_cls.__index_names__)
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"


@pytest.mark.parametrize("storage_cls", [AssetSnapshotsStorage, AssetPricingDetailsStorage])
def test_timestamped_asset_storage_has_asset_foreign_key(storage_cls) -> None:
    asset_identifier = AssetTable.__metatable_identifier__
    fk_column = storage_cls.__table__.columns[ASSET_UNIQUE_IDENTIFIER_DIMENSION]

    assert markets_foreign_key_target_identifiers(storage_cls) == [asset_identifier]
    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"] is AssetTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"]
        == "unique_identifier"
        for foreign_key in fk_column.foreign_keys
    )


def test_asset_indexed_node_normalizes_asset_scope_helpers() -> None:
    assert AssetSnapshot.validate_asset_list(["BTC", "ETH"]) == ["BTC", "ETH"]
    assert AssetSnapshot.asset_dimension_filters(["BTC", "ETH"]) == {
        ASSET_UNIQUE_IDENTIFIER_DIMENSION: ["BTC", "ETH"]
    }
    assert AssetSnapshot.asset_dimension_filters(None) is None


def test_asset_indexed_node_rejects_duplicate_or_empty_asset_scope() -> None:
    with pytest.raises(ValueError):
        AssetSnapshot.validate_asset_list(["BTC", "BTC"])
    with pytest.raises(ValueError):
        AssetSnapshot.validate_asset_list([])


def test_asset_indexed_configuration_only_carries_update_scope() -> None:
    config = AssetIndexedDataNodeConfiguration()

    assert config.asset_list is None
    assert "asset_list" in AssetIndexedDataNodeConfiguration.model_fields
    # Storage-first: schema/FK fields no longer live on the configuration.
    assert "records" not in AssetIndexedDataNodeConfiguration.model_fields
    assert "node_metadata" not in AssetIndexedDataNodeConfiguration.model_fields
    assert "foreign_keys" not in AssetIndexedDataNodeConfiguration.model_fields
