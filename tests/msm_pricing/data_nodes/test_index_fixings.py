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

from mainsequence.client.utils import DataFrequency

from msm.data_nodes.indices import IndexDataNodeConfiguration, IndexTimestampedDataNode
from msm.models import IndexTable
from msm.models.registration import markets_foreign_key_target_identifiers
from msm.settings import INDEX_IDENTIFIER_DIMENSION
from msm_pricing.data_nodes.index_fixings import (
    FixingRatesNode,
    IndexFixingConfiguration,
)
from msm_pricing.data_nodes.storage import IndexFixingsStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models


def test_index_fixing_configuration_is_index_stamped_with_hashable_frequency() -> None:
    config = IndexFixingConfiguration(frequency=DataFrequency.one_d.value)

    assert isinstance(config, IndexDataNodeConfiguration)
    assert config.frequency == "1d"
    assert IndexFixingConfiguration.model_fields["frequency"].json_schema_extra is None
    # Storage-first: schema/identity/FK fields no longer live on the config.
    assert "records" not in IndexFixingConfiguration.model_fields
    assert "node_metadata" not in IndexFixingConfiguration.model_fields
    assert "foreign_keys" not in IndexFixingConfiguration.model_fields


def test_index_fixing_configuration_rejects_unsupported_frequency() -> None:
    with pytest.raises(ValueError, match="Unsupported index fixing frequency"):
        IndexFixingConfiguration(frequency="2d")


def test_fixing_rates_node_resolves_index_storage_first_surface() -> None:
    storage_table = FixingRatesNode._required_storage_table()

    assert issubclass(FixingRatesNode, IndexTimestampedDataNode)
    assert storage_table is IndexFixingsStorage
    assert storage_table.metatable_identifier() == "IndexFixingsTS"
    assert storage_table.__index_names__ == ["time_index", INDEX_IDENTIFIER_DIMENSION]
    assert "__data_node_identifier__" not in FixingRatesNode.__dict__
    assert FixingRatesNode._default_identifier() == storage_table.metatable_identifier()
    assert FixingRatesNode._default_description() == storage_table.__metatable_description__
    assert {column.name for column in storage_table.__table__.columns} == {
        "time_index",
        INDEX_IDENTIFIER_DIMENSION,
        "rate",
    }


def test_index_fixings_storage_has_index_foreign_key() -> None:
    index_identifier = IndexTable.__metatable_identifier__
    fk_column = IndexFixingsStorage.__table__.columns[INDEX_IDENTIFIER_DIMENSION]

    assert markets_foreign_key_target_identifiers(IndexFixingsStorage) == [index_identifier]
    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"] is IndexTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"]
        == "unique_identifier"
        for foreign_key in fk_column.foreign_keys
    )
    assert IndexFixingsStorage in set(pricing_sqlalchemy_models())


def test_fixing_rates_node_does_not_expose_bootstrap_frame_api() -> None:
    assert not hasattr(FixingRatesNode, "build_schema_bootstrap_frame")
    assert not hasattr(FixingRatesNode, "build_initialization_frame")


def test_fixing_rates_node_validate_frame_uses_index_unique_identifier() -> None:
    frame = FixingRatesNode.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "index_identifier": "SOFR",
                    "rate": 0.0525,
                }
            ]
        )
    )

    assert list(frame.index.names) == ["time_index", INDEX_IDENTIFIER_DIMENSION]
    assert frame.reset_index()[INDEX_IDENTIFIER_DIMENSION].tolist() == ["SOFR"]
    assert frame.reset_index()["rate"].tolist() == [0.0525]


def test_fixing_rates_node_normalizes_index_identifier_builder_frame() -> None:
    normalized = FixingRatesNode._normalize_builder_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "index_identifier": "SOFR",
                    "rate": 0.0525,
                }
            ]
        ).set_index(["time_index", "index_identifier"])
    )

    assert normalized[INDEX_IDENTIFIER_DIMENSION].tolist() == ["SOFR"]


def test_fixing_rates_node_rejects_stale_builder_identity_names() -> None:
    with pytest.raises(ValueError, match="index_identifier"):
        FixingRatesNode._normalize_builder_frame(
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "unique_identifier": "SOFR",
                        "rate": 0.0525,
                    }
                ]
            )
        )


@pytest.mark.skip(reason="requires platform backend (Stage 5 registration)")
def test_fixing_rates_node_update_uses_index_unique_identifiers() -> None:
    """A full update() run needs a registered/bound storage table."""

    node = FixingRatesNode(IndexFixingConfiguration(index_unique_identifiers=["SOFR"]))
    assert node.index_unique_identifiers() == ["SOFR"]
