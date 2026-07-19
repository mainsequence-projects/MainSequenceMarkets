from __future__ import annotations

import datetime
import uuid

import pandas as pd
import pytest
from msm.analytics.indices import IndexCalculationError
from msm.data_nodes.indices import (
    IndexTimestampedDataNode,
    IndexValuesDataNode,
    IndexValuesStorage,
    configured_index_values_storage,
    index_values_storage_table_name,
)
from msm.data_nodes.indices import derived as derived_nodes

ONE_MINUTE_STORAGE = configured_index_values_storage(cadence="1m")
DAILY_STORAGE = configured_index_values_storage(cadence="1d")


def test_plain_index_values_require_no_calculation_definition() -> None:
    values = IndexValuesDataNode.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": "2026-07-19T10:01:00Z",
                    "index_identifier": "USD_SWAP_10Y",
                    "value": 0.04217,
                    "unit": "decimal",
                },
            ]
        ),
        storage_table=ONE_MINUTE_STORAGE,
    )

    assert values.index.names == ["time_index", "index_identifier"]
    assert str(values.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"
    assert values.reset_index()["definition_uid"].isna().all()
    assert values.reset_index()["observation_status"].isna().all()


def test_plain_index_values_preserve_optional_observation_provenance() -> None:
    source_as_of = datetime.datetime(2026, 7, 19, 10, 0, tzinfo=datetime.UTC)
    values = IndexValuesDataNode.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": source_as_of,
                    "index_identifier": "USD_SWAP_10Y",
                    "value": 0.04217,
                    "unit": "decimal",
                    "observation_status": "preliminary",
                    "source_as_of": source_as_of,
                    "metadata_json": {"source_kind": "extension"},
                }
            ]
        ),
        storage_table=ONE_MINUTE_STORAGE,
    ).reset_index()

    assert values.loc[0, "observation_status"] == "preliminary"
    assert values.loc[0, "source_as_of"] == source_as_of
    assert values.loc[0, "metadata_json"] == {"source_kind": "extension"}


def test_index_values_storage_identity_is_driven_by_frequency() -> None:
    import msm.data_nodes as public_data_nodes

    assert issubclass(IndexValuesDataNode, IndexTimestampedDataNode)
    assert ONE_MINUTE_STORAGE is configured_index_values_storage(cadence="1m")
    assert ONE_MINUTE_STORAGE is configured_index_values_storage(cadence=" 1M ")
    assert ONE_MINUTE_STORAGE is not DAILY_STORAGE
    assert ONE_MINUTE_STORAGE.__cadence__ == "1m"
    assert DAILY_STORAGE.__cadence__ == "1d"
    assert ONE_MINUTE_STORAGE.__table__.name == index_values_storage_table_name(cadence="1m")
    assert DAILY_STORAGE.__table__.name == index_values_storage_table_name(cadence="1d")
    assert ONE_MINUTE_STORAGE.__table__.name != DAILY_STORAGE.__table__.name
    assert ONE_MINUTE_STORAGE.metatable_identifier() != DAILY_STORAGE.metatable_identifier()
    assert ONE_MINUTE_STORAGE.__metatable_extra_hash_components__["cadence"] == "1m"
    assert DAILY_STORAGE.__metatable_extra_hash_components__["cadence"] == "1d"
    with pytest.raises(NotImplementedError, match="cadence-specific storage"):
        IndexValuesDataNode._required_storage_table()
    with pytest.raises(ValueError, match="cadence-specific storage"):
        IndexValuesDataNode.validate_frame(pd.DataFrame(), storage_table=IndexValuesStorage)
    derived_config = derived_nodes.DerivedIndexDataNodeConfiguration(
        index_identifiers=("DERIVED",),
        source_bindings={"source": IndexValuesStorage},
    )
    with pytest.raises(ValueError, match="cadence-specific storage"):
        derived_nodes.DerivedIndexDataNode(
            config=derived_config,
            storage_table=IndexValuesStorage,
        )
    assert public_data_nodes.IndexValuesDataNode is IndexValuesDataNode
    assert public_data_nodes.IndexValuesStorage is IndexValuesStorage
    assert public_data_nodes.configured_index_values_storage is configured_index_values_storage


@pytest.mark.parametrize("cadence", ["", "daily", "1 min", "m1", "-1d", "0m"])
def test_index_value_storage_rejects_noncanonical_frequency(cadence: str) -> None:
    with pytest.raises(ValueError, match="canonical interval|non-empty"):
        configured_index_values_storage(cadence=cadence)


def test_derived_publication_rejects_missing_definition_or_status() -> None:
    missing_definition = IndexValuesDataNode.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": "2025-01-01T00:00:00Z",
                    "index_identifier": "DERIVED",
                    "value": 1.0,
                    "unit": "ratio",
                    "observation_status": "ready",
                }
            ]
        ),
        storage_table=DAILY_STORAGE,
    )
    with pytest.raises(IndexCalculationError, match="definition_uid"):
        derived_nodes._validate_derived_values_frame(missing_definition)

    missing_status = missing_definition.reset_index()
    missing_status["definition_uid"] = uuid.UUID("11111111-1111-1111-1111-111111111111")
    missing_status["observation_status"] = None
    missing_status = IndexValuesDataNode.validate_frame(
        missing_status,
        storage_table=DAILY_STORAGE,
    )
    with pytest.raises(IndexCalculationError, match="observation_status"):
        derived_nodes._validate_derived_values_frame(missing_status)
