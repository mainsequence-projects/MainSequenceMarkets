from __future__ import annotations

import pandas as pd
import pytest

from msm.data_nodes.indices import configured_index_values_storage, normalize_index_values_frame


VALUES = configured_index_values_storage(cadence="1h")


def test_custom_index_values_allow_null_definition() -> None:
    frame = pd.DataFrame(
        {
            "time_index": [pd.Timestamp("2026-01-01", tz="UTC")],
            "index_identifier": ["CUSTOM"],
            "value": [42.0],
            "observation_status": ["ready"],
        }
    )

    result = normalize_index_values_frame(frame, storage_table=VALUES)

    assert pd.isna(result.iloc[0]["definition_uid"])
    assert "unit" not in result.columns


def test_index_value_frame_rejects_duplicate_identity_times() -> None:
    frame = pd.DataFrame(
        {
            "time_index": [
                pd.Timestamp("2026-01-01", tz="UTC"),
                pd.Timestamp("2026-01-01", tz="UTC"),
            ],
            "index_identifier": ["CUSTOM", "CUSTOM"],
            "value": [1.0, 2.0],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        normalize_index_values_frame(frame, storage_table=VALUES)


def test_custom_index_value_frame_rejects_formula_definition_uid() -> None:
    frame = pd.DataFrame(
        {
            "time_index": [pd.Timestamp("2026-01-01", tz="UTC")],
            "index_identifier": ["CUSTOM"],
            "value": [1.0],
            "definition_uid": ["11111111-1111-1111-1111-111111111111"],
        }
    )

    with pytest.raises(ValueError, match="must not provide definition_uid"):
        normalize_index_values_frame(frame, storage_table=VALUES)
