from __future__ import annotations

import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.data_nodes.indices import (
    FormulaIndexDataNodeConfiguration,
    configured_index_values_storage,
    normalize_index_values_frame,
)


DAILY_VALUES = configured_index_values_storage(cadence="1d")


def test_formula_data_node_configuration_uses_definition_uids_and_storage_classes() -> None:
    definition_uid = uuid.uuid4()
    config = FormulaIndexDataNodeConfiguration(
        formula_definition_uids=(definition_uid,),
        source_storage_tables=(DAILY_VALUES,),
    )

    assert config.formula_definition_uids == (definition_uid,)
    assert config.source_storage_tables == (DAILY_VALUES,)
    assert not hasattr(config, "source_bindings")
    assert not hasattr(config, "requires_resolved_legs")


def test_formula_data_node_configuration_rejects_duplicates() -> None:
    definition_uid = uuid.uuid4()
    with pytest.raises(ValidationError, match="formula_definition_uids must be unique"):
        FormulaIndexDataNodeConfiguration(
            formula_definition_uids=(definition_uid, definition_uid),
            source_storage_tables=(DAILY_VALUES,),
        )


def test_index_value_normalization_requires_no_unit() -> None:
    frame = pd.DataFrame(
        {
            "time_index": [pd.Timestamp("2026-01-01", tz="UTC")],
            "index_identifier": ["FORMULA-INDEX"],
            "value": [1.25],
        }
    )

    normalized = normalize_index_values_frame(frame, storage_table=DAILY_VALUES)

    assert normalized.index.names == ["time_index", "index_identifier"]
    assert "unit" not in normalized.columns
    assert normalized.iloc[0]["value"] == pytest.approx(1.25)
