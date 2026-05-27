from __future__ import annotations

import datetime as dt
import os
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import Field

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from mainsequence.tdag.data_nodes import RecordDefinition, SourceTableForeignKey
from msm.data_nodes.utils.stamped import StampedDataNodeConfiguration
from msm.models import AssetTable
from msm_pricing.data_nodes.curves import (
    CURVE_UNIQUE_IDENTIFIER_DIMENSION,
    CurveConfig,
    CurveDataNodeConfiguration,
    DiscountCurvesNode,
    curve_time_index_record,
    curve_unique_identifier_foreign_key,
    curve_unique_identifier_record,
)
from msm_pricing.models import CurveTable


def _curve_fact_records() -> list[RecordDefinition]:
    return [
        curve_time_index_record(),
        curve_unique_identifier_record(),
        RecordDefinition(
            column_name="curve",
            dtype="str",
            label="Curve",
            description="Compressed curve payload.",
        ),
    ]


class ExampleCurveConfiguration(CurveDataNodeConfiguration):
    records: list[RecordDefinition] = Field(
        default_factory=_curve_fact_records,
        description="Output schema for the example curve fact node.",
    )


def test_curve_unique_identifier_foreign_key_targets_curve_table() -> None:
    foreign_key = curve_unique_identifier_foreign_key()

    assert foreign_key.target is CurveTable
    assert foreign_key.source_column_names() == [CURVE_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == ["unique_identifier"]
    assert foreign_key.on_delete == "restrict"


def test_curve_data_node_configuration_is_stamped_and_adds_curve_fk() -> None:
    config = ExampleCurveConfiguration()

    assert isinstance(config, StampedDataNodeConfiguration)
    assert isinstance(config, CurveDataNodeConfiguration)
    assert config.index_names == ["time_index", CURVE_UNIQUE_IDENTIFIER_DIMENSION]
    assert config.foreign_keys is not None
    [foreign_key] = config.foreign_keys
    assert foreign_key.target is CurveTable
    assert foreign_key.source_column_names() == [CURVE_UNIQUE_IDENTIFIER_DIMENSION]
    assert foreign_key.target_column_names() == ["unique_identifier"]
    assert foreign_key.target is not AssetTable


def test_curve_data_node_configuration_rejects_missing_curve_identity_record() -> None:
    with pytest.raises(ValueError, match="records entry"):
        CurveDataNodeConfiguration(
            records=[
                curve_time_index_record(),
                RecordDefinition(column_name="curve", dtype="str"),
            ]
        )


def test_curve_config_uses_curve_identity_not_asset_identity() -> None:
    config = CurveConfig(curve_unique_identifier="mxn_tiie_discount")

    assert config.index_names == ["time_index", CURVE_UNIQUE_IDENTIFIER_DIMENSION]
    assert config.curve_unique_identifier == "mxn_tiie_discount"
    assert "curve_const" not in CurveConfig.model_fields
    assert CURVE_UNIQUE_IDENTIFIER_DIMENSION in {
        record.column_name for record in config.records
    }
    assert "unique_identifier" not in {record.column_name for record in config.records}
    assert config.foreign_keys is not None
    [foreign_key] = config.foreign_keys
    assert foreign_key.target is CurveTable


def test_curve_config_defines_rich_node_metadata_description() -> None:
    config = CurveConfig(curve_unique_identifier="mxn_tiie_discount")

    assert config.node_metadata.identifier.endswith("discount_curves")
    assert "Daily compressed discount curves" in config.node_metadata.description
    assert "curve_unique_identifier" in config.node_metadata.description
    assert "Curve MetaTable" in config.node_metadata.description
    assert "pricing bonds" in config.node_metadata.description


def test_discount_curves_node_normalizes_legacy_builder_identity_name() -> None:
    time_index = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    frame = pd.DataFrame(
        [
            {
                "time_index": time_index,
                "unique_identifier": "mxn_tiie_discount",
                "curve": {28: 0.11, 91: 0.105},
            }
        ]
    ).set_index(["time_index", "unique_identifier"])

    normalized = DiscountCurvesNode._normalize_builder_frame(
        frame,
        curve_unique_identifier="mxn_tiie_discount",
    )

    assert "unique_identifier" not in normalized.columns
    assert normalized[CURVE_UNIQUE_IDENTIFIER_DIMENSION].tolist() == [
        "mxn_tiie_discount"
    ]


def test_discount_curves_node_update_returns_stamped_curve_frame(monkeypatch) -> None:
    curve_uid = "mxn_tiie_discount"

    def builder(**kwargs):
        assert kwargs["curve_unique_identifier"] == curve_uid
        return pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "unique_identifier": curve_uid,
                    "curve": {28: 0.11, 91: 0.105},
                }
            ]
        ).set_index(["time_index", "unique_identifier"])

    monkeypatch.setattr(DiscountCurvesNode, "set_data_source", lambda self, data_source=None: None)
    monkeypatch.setattr(
        SourceTableForeignKey,
        "target_meta_table_uid",
        lambda self, **kwargs: "curve-metatable-uid",
    )
    node = DiscountCurvesNode(
        CurveConfig(curve_unique_identifier=curve_uid),
    ).set_curve_builder(builder)
    node.update_statistics = SimpleNamespace(
        get_last_update_for_identity=lambda identity: None,
    )

    updated = node.update()

    assert list(updated.index.names) == ["time_index", CURVE_UNIQUE_IDENTIFIER_DIMENSION]
    assert str(updated.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"
    assert updated.reset_index()[CURVE_UNIQUE_IDENTIFIER_DIMENSION].tolist() == [
        curve_uid
    ]
    assert isinstance(updated.reset_index()["curve"].iloc[0], str)
