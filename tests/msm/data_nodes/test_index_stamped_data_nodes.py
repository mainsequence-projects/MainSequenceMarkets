from __future__ import annotations

import datetime as dt
import os
from typing import ClassVar

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.data_nodes.indices import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
)
from msm.data_nodes.utils.stamped import StampedDataNodeConfiguration
from msm.models import IndexTable
from msm.models.registration import markets_foreign_key_target_fullnames
from msm.settings import INDEX_UNIQUE_IDENTIFIER_DIMENSION
from msm_pricing.data_nodes.index_fixings import FixingRatesNode
from msm_pricing.data_nodes.storage import IndexFixingsStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models


class ExampleIndexFact(IndexTimestampedDataNode):
    """Example index-stamped node bound to the IndexFixingsStorage contract."""

    configuration_class: ClassVar[type[IndexDataNodeConfiguration]] = IndexDataNodeConfiguration

    @classmethod
    def _required_storage_table(cls) -> type[IndexFixingsStorage]:
        return IndexFixingsStorage


def test_index_data_node_configuration_is_stamped() -> None:
    config = ExampleIndexFact.default_config()

    assert isinstance(config, StampedDataNodeConfiguration)
    assert isinstance(config, IndexDataNodeConfiguration)
    assert config.reference_dimension == INDEX_UNIQUE_IDENTIFIER_DIMENSION
    # Storage-first: schema/identity/FK fields no longer live on the config.
    assert "records" not in IndexDataNodeConfiguration.model_fields
    assert "node_metadata" not in IndexDataNodeConfiguration.model_fields
    assert "foreign_keys" not in IndexDataNodeConfiguration.model_fields


def test_index_node_resolves_storage_table_and_index_contract() -> None:
    storage_table = ExampleIndexFact._required_storage_table()

    assert storage_table is IndexFixingsStorage
    assert storage_table.__index_names__ == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert storage_table.__time_index_name__ == "time_index"


def test_index_node_storage_has_index_foreign_key() -> None:
    index_fullname = str(IndexTable.__table__.fullname)
    fk_column = IndexFixingsStorage.__table__.columns[INDEX_UNIQUE_IDENTIFIER_DIMENSION]

    assert markets_foreign_key_target_fullnames(IndexFixingsStorage) == [index_fullname]
    assert any(
        foreign_key.column.table.fullname == index_fullname
        for foreign_key in fk_column.foreign_keys
    )
    assert IndexFixingsStorage in set(pricing_sqlalchemy_models())


def test_index_node_does_not_expose_bootstrap_frame_api() -> None:
    assert not hasattr(ExampleIndexFact, "build_schema_bootstrap_frame")
    assert not hasattr(ExampleIndexFact, "build_initialization_frame")


def test_index_node_validate_frame_normalizes_datetime64_ns_utc() -> None:
    frame = ExampleIndexFact.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 26, 18, 50, 19, 240235, tzinfo=dt.UTC),
                    "unique_identifier": "SPX",
                    "rate": 5340.26,
                }
            ]
        )
    )

    assert list(frame.index.names) == ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION]
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"
    assert frame.reset_index()["unique_identifier"].iloc[0] == "SPX"


def test_index_node_validate_frame_rejects_duplicate_keys() -> None:
    time_index = "2026-05-26T00:00:00Z"

    with pytest.raises(ValueError, match="duplicate rows"):
        ExampleIndexFact.validate_frame(
            pd.DataFrame(
                [
                    {"time_index": time_index, "unique_identifier": "SPX", "rate": 5340.26},
                    {"time_index": time_index, "unique_identifier": "SPX", "rate": 5340.27},
                ]
            )
        )


def test_fixing_rates_node_is_index_timestamped() -> None:
    assert issubclass(FixingRatesNode, IndexTimestampedDataNode)
    assert FixingRatesNode._required_storage_table() is IndexFixingsStorage
    assert "__data_node_identifier__" not in FixingRatesNode.__dict__
    assert FixingRatesNode._default_identifier() == IndexFixingsStorage.metatable_identifier()
    assert "SOFR" in FixingRatesNode._default_description()
