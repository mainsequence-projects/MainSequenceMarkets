from __future__ import annotations

import importlib
import os

import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from mainsequence.tdag.data_nodes import RecordDefinition, SourceTableForeignKey

from msm.asset_indexed_data_node import (
    ASSET_UNIQUE_IDENTIFIER_DIMENSION,
    AssetIndexedDataNodeConfiguration,
    asset_unique_identifier_foreign_key,
)
from msm.asset_scope import ASSET_UNIQUE_IDENTIFIER
from msm.accounts.data_nodes import AccountHoldings, VirtualFundHoldings
from msm.data_nodes.assets import (
    AssetDataNodeConfiguration,
    AssetPricingDetail,
    AssetSnapshot,
)
from msm.execution.data_nodes import ExecutionErrors, OrderEvents, Orders, Trades
from msm.models import AssetTable
from msm.portfolios.data_nodes.portfolio_weights import PortfolioWeights
from msm.portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm.portfolios.data_nodes.signal_weights import SignalWeights
from msm.settings import (
    ASSET_UNIQUE_IDENTIFIER_DIMENSION as SETTINGS_ASSET_DIMENSION,
    DEFAULT_MARKETS_NAMESPACE,
    markets_data_node_identifier,
)


def _record(column_name: str, dtype: str = "string") -> RecordDefinition:
    return RecordDefinition(column_name=column_name, dtype=dtype)


def _asset_records(*, include_unique_identifier: bool = True) -> list[RecordDefinition]:
    records = [_record("time_index", "datetime64[ns, UTC]")]
    if include_unique_identifier:
        records.append(_record(ASSET_UNIQUE_IDENTIFIER_DIMENSION))
    records.append(_record("ticker"))
    return records


def _asset_config(
    *,
    records: list[RecordDefinition] | None = None,
    foreign_keys: list[SourceTableForeignKey] | None = None,
) -> AssetDataNodeConfiguration:
    return AssetDataNodeConfiguration(
        time_index_name="time_index",
        index_names=["time_index", ASSET_UNIQUE_IDENTIFIER_DIMENSION],
        records=records or _asset_records(),
        foreign_keys=foreign_keys,
    )


def test_asset_identity_dimension_is_shared_with_settings() -> None:
    assert ASSET_UNIQUE_IDENTIFIER_DIMENSION == SETTINGS_ASSET_DIMENSION
    assert ASSET_UNIQUE_IDENTIFIER == SETTINGS_ASSET_DIMENSION


def test_market_data_node_compatibility_names_are_removed() -> None:
    asset_indexed_module = importlib.import_module("msm.asset_indexed_data_node")

    legacy_node_name = "Market" + "DataNode"
    legacy_config_name = legacy_node_name + "Configuration"
    legacy_module_name = "msm." + "markets_" + "data_node"

    assert not hasattr(asset_indexed_module, legacy_node_name)
    assert not hasattr(asset_indexed_module, legacy_config_name)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_module_name)


@pytest.mark.parametrize(
    ("node_cls", "logical_identifier"),
    [
        (AssetSnapshot, "asset_snapshots"),
        (AssetPricingDetail, "asset_pricing_details"),
        (AccountHoldings, "account_historical_holdings"),
        (VirtualFundHoldings, "virtual_fund_historical_holdings"),
        (Orders, "execution.orders"),
        (OrderEvents, "execution.order_events"),
        (Trades, "execution.trades"),
        (ExecutionErrors, "execution.errors"),
        (PortfolioWeights, "portfolio_weights"),
        (PortfoliosDataNode, "portfolios"),
        (SignalWeights, "signal_weights"),
    ],
)
def test_market_data_node_identifiers_use_default_namespace(
    node_cls,
    logical_identifier: str,
) -> None:
    assert node_cls.__data_node_identifier__ == logical_identifier
    assert node_cls.default_config().node_metadata.identifier == markets_data_node_identifier(
        logical_identifier
    )


def test_asset_indexed_nodes_default_to_markets_hash_namespace(monkeypatch) -> None:
    monkeypatch.setattr(AssetSnapshot, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "asset-metatable-uid",
    )

    node = AssetSnapshot()

    assert node.hash_namespace == DEFAULT_MARKETS_NAMESPACE


def test_auto_register_namespace_drives_data_node_defaults(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(AssetSnapshot, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "asset-metatable-uid",
    )

    node = AssetSnapshot()

    assert node.hash_namespace == "mainsequence.examples"
    assert node.config.node_metadata.identifier == "mainsequence.examples.asset_snapshots"


def test_asset_unique_identifier_foreign_key_targets_asset_table() -> None:
    foreign_key = asset_unique_identifier_foreign_key()

    assert foreign_key.target is AssetTable
    assert foreign_key.source_column_names() == [ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == [ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.on_delete == "restrict"


@pytest.mark.parametrize("node_cls", [AssetSnapshot, AssetPricingDetail])
def test_timestamped_asset_nodes_include_canonical_asset_foreign_key(node_cls) -> None:
    config = node_cls.default_config()

    assert config.foreign_keys is not None
    assert len(config.foreign_keys) == 1
    [foreign_key] = config.foreign_keys
    assert foreign_key.target is AssetTable
    assert foreign_key.source_column_names() == [ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == [ASSET_UNIQUE_IDENTIFIER_DIMENSION]
    assert ASSET_UNIQUE_IDENTIFIER_DIMENSION in {record.column_name for record in config.records}


def test_asset_data_node_config_preserves_explicit_foreign_keys() -> None:
    extra_foreign_key = SourceTableForeignKey(
        target="00000000-0000-0000-0000-000000000001",
        source_columns=["ticker"],
        target_columns=["ticker"],
        on_delete="cascade",
    )

    config = _asset_config(foreign_keys=[extra_foreign_key])

    assert config.foreign_keys is not None
    assert config.foreign_keys[0].target is AssetTable
    assert config.foreign_keys[1] is extra_foreign_key


def test_asset_data_node_config_rejects_missing_asset_identity_record() -> None:
    with pytest.raises(ValueError, match="records entry"):
        _asset_config(records=_asset_records(include_unique_identifier=False))


def test_asset_indexed_config_does_not_add_hidden_asset_foreign_key() -> None:
    assert AssetIndexedDataNodeConfiguration().foreign_keys is None
