from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import pytest
from pydantic import Field

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from mainsequence.tdag.data_nodes import RecordDefinition, SourceTableForeignKey

from msm.data_nodes.indices import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
    index_time_index_record,
    index_unique_identifier_foreign_key,
    index_unique_identifier_record,
)
from msm.data_nodes.utils.stamped import StampedDataNodeConfiguration
from msm.models import IndexTable
from msm.settings import (
    DEFAULT_MARKETS_NAMESPACE,
    INDEX_UNIQUE_IDENTIFIER_DIMENSION,
    markets_data_node_identifier,
)


def _index_fact_records() -> list[RecordDefinition]:
    return [
        index_time_index_record(),
        index_unique_identifier_record(),
        RecordDefinition(
            column_name="level",
            dtype="float64",
            label="Level",
            description="Observed index level.",
        ),
    ]


class ExampleIndexFactConfiguration(IndexDataNodeConfiguration):
    records: list[RecordDefinition] = Field(
        default_factory=_index_fact_records,
        description="Output schema for the example index fact node.",
    )


class ExampleIndexFact(IndexTimestampedDataNode):
    __data_node_identifier__ = "example_index_facts"
    configuration_class = ExampleIndexFactConfiguration

    @classmethod
    def _default_description(cls) -> str:
        return "Example timestamped index facts keyed by index unique_identifier."


@pytest.fixture
def offline_index_node(monkeypatch):
    monkeypatch.setattr(
        ExampleIndexFact,
        "set_data_source",
        lambda self, data_source=None: None,
    )
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "index-metatable-uid",
    )


def test_index_unique_identifier_foreign_key_targets_index_table() -> None:
    foreign_key = index_unique_identifier_foreign_key()

    assert foreign_key.target is IndexTable
    assert foreign_key.source_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.on_delete == "restrict"


def test_index_data_node_configuration_is_stamped_and_adds_index_fk() -> None:
    config = ExampleIndexFact.default_config()

    assert isinstance(config, StampedDataNodeConfiguration)
    assert isinstance(config, IndexDataNodeConfiguration)
    assert config.index_names == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert config.foreign_keys is not None
    [foreign_key] = config.foreign_keys
    assert foreign_key.target is IndexTable
    assert foreign_key.source_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == [INDEX_UNIQUE_IDENTIFIER_DIMENSION]


def test_index_data_node_configuration_rejects_missing_index_identity_record() -> None:
    with pytest.raises(ValueError, match="records entry"):
        IndexDataNodeConfiguration(
            records=[
                index_time_index_record(),
                RecordDefinition(column_name="level", dtype="float64"),
            ]
        )


def test_index_timestamped_node_uses_markets_identifier_and_hash_namespace(
    offline_index_node,
) -> None:
    node = ExampleIndexFact()

    assert node.config.node_metadata.identifier == markets_data_node_identifier(
        "example_index_facts"
    )
    assert node.hash_namespace == DEFAULT_MARKETS_NAMESPACE


def test_index_timestamped_node_uses_auto_register_namespace(
    offline_index_node,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    node = ExampleIndexFact()

    assert node.hash_namespace == "mainsequence.examples"
    assert node.config.node_metadata.identifier == "mainsequence.examples.example_index_facts"


def test_index_timestamped_node_validates_datetime64_ns_utc_frame() -> None:
    frame = ExampleIndexFact.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(
                        2026,
                        5,
                        26,
                        18,
                        50,
                        19,
                        240235,
                        tzinfo=dt.UTC,
                    ),
                    "unique_identifier": "SPX",
                    "level": 5340.26,
                }
            ]
        )
    )

    assert list(frame.index.names) == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"


def test_index_timestamped_node_rejects_duplicate_keys() -> None:
    time_index = "2026-05-26T00:00:00Z"

    with pytest.raises(ValueError, match="duplicate rows"):
        ExampleIndexFact.validate_frame(
            pd.DataFrame(
                [
                    {
                        "time_index": time_index,
                        "unique_identifier": "SPX",
                        "level": 5340.26,
                    },
                    {
                        "time_index": time_index,
                        "unique_identifier": "SPX",
                        "level": 5340.27,
                    },
                ]
            )
        )
