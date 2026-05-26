from __future__ import annotations

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
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
    asset_unique_identifier_foreign_key,
)
from msm.asset_scope import ASSET_UNIQUE_IDENTIFIER
from msm.data_nodes.assets import (
    ASSET_DATA_NODE_TIME_INDEX_NAME,
    AssetDataNodeConfiguration,
    AssetPricingDetail,
    AssetSnapshot,
)
from msm.markets_data_node import (
    MarketDataNode,
    MarketDataNodeConfiguration,
)
from msm.models import AssetTable
from msm.settings import ASSET_UNIQUE_IDENTIFIER_DIMENSION as SETTINGS_ASSET_DIMENSION


def _record(column_name: str, dtype: str = "string") -> RecordDefinition:
    return RecordDefinition(column_name=column_name, dtype=dtype)


def _asset_records(*, include_unique_identifier: bool = True) -> list[RecordDefinition]:
    records = [_record(ASSET_DATA_NODE_TIME_INDEX_NAME, "datetime64[ns, UTC]")]
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
        time_index_name=ASSET_DATA_NODE_TIME_INDEX_NAME,
        index_names=[ASSET_DATA_NODE_TIME_INDEX_NAME, ASSET_UNIQUE_IDENTIFIER_DIMENSION],
        records=records or _asset_records(),
        foreign_keys=foreign_keys,
    )


def test_asset_identity_dimension_is_shared_with_compatibility_module() -> None:
    assert ASSET_UNIQUE_IDENTIFIER_DIMENSION == SETTINGS_ASSET_DIMENSION
    assert ASSET_UNIQUE_IDENTIFIER == SETTINGS_ASSET_DIMENSION
    assert MarketDataNodeConfiguration is AssetIndexedDataNodeConfiguration
    assert MarketDataNode is AssetIndexedDataNode


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


def test_compatibility_market_config_does_not_add_hidden_asset_foreign_key() -> None:
    assert MarketDataNodeConfiguration().foreign_keys is None
