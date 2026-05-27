from __future__ import annotations

import datetime as dt
import os
from types import SimpleNamespace

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from mainsequence.client.utils import DataFrequency
from mainsequence.tdag.data_nodes import SourceTableForeignKey
from msm.data_nodes.indices import IndexDataNodeConfiguration, IndexTimestampedDataNode
from msm.models import AssetTable, IndexTable
from msm.settings import INDEX_UNIQUE_IDENTIFIER_DIMENSION
from msm_pricing.data_nodes.index_fixings import (
    FixingRatesNode,
    IndexFixingConfiguration,
)


def test_index_fixing_configuration_is_index_stamped_with_hashable_frequency() -> None:
    config = IndexFixingConfiguration(frequency=DataFrequency.one_d.value)

    assert isinstance(config, IndexDataNodeConfiguration)
    assert config.frequency == "1d"
    assert IndexFixingConfiguration.model_fields["frequency"].json_schema_extra is None
    assert config.index_names == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert config.foreign_keys is not None
    [foreign_key] = config.foreign_keys
    assert foreign_key.target is IndexTable
    assert foreign_key.target is not AssetTable
    assert foreign_key.source_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert {record.column_name for record in config.records} == {
        "time_index",
        INDEX_UNIQUE_IDENTIFIER_DIMENSION,
        "rate",
    }


def test_index_fixing_configuration_rejects_unsupported_frequency() -> None:
    with pytest.raises(ValueError, match="Unsupported index fixing frequency"):
        IndexFixingConfiguration(frequency="2d")


def test_fixing_rates_node_is_index_timestamped_not_asset_indexed(monkeypatch) -> None:
    monkeypatch.setattr(FixingRatesNode, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "index-metatable-uid",
    )

    node = FixingRatesNode(IndexFixingConfiguration(index_unique_identifiers=["SOFR"]))

    assert isinstance(node, IndexTimestampedDataNode)
    assert not hasattr(node, "get_asset_list")
    assert node.index_unique_identifiers() == ["SOFR"]


def test_fixing_rates_node_update_uses_index_unique_identifiers(monkeypatch) -> None:
    index_uid = "SOFR"

    def builder(**kwargs):
        assert kwargs["unique_identifier"] == index_uid
        return pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "unique_identifier": index_uid,
                    "rate": 0.0525,
                }
            ]
        ).set_index(["time_index", "unique_identifier"])

    monkeypatch.setattr(FixingRatesNode, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "index-metatable-uid",
    )

    node = FixingRatesNode(
        IndexFixingConfiguration(index_unique_identifiers=[index_uid])
    ).set_fixing_builders({index_uid: builder})
    node.update_statistics = SimpleNamespace(
        get_last_update_for_identity=lambda identity: None,
    )

    updated = node.update()

    assert list(updated.index.names) == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert updated.reset_index()[INDEX_UNIQUE_IDENTIFIER_DIMENSION].tolist() == [index_uid]
    assert updated.reset_index()["rate"].tolist() == [0.0525]
