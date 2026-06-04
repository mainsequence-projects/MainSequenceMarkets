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

from msm.data_nodes.utils.stamped import StampedDataNodeConfiguration
from msm.models.registration import markets_foreign_key_target_identifiers
from msm_pricing.data_nodes.curves import (
    CURVE_IDENTIFIER,
    CurveConfig,
    CurveDataNodeConfiguration,
    DiscountCurvesNode,
)
from msm_pricing.data_nodes.storage import DiscountCurvesStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models
from msm_pricing.models import CurveTable


def test_curve_data_node_configuration_is_stamped() -> None:
    config = CurveConfig(curve_unique_identifier="mxn_tiie_discount")

    assert isinstance(config, StampedDataNodeConfiguration)
    assert isinstance(config, CurveDataNodeConfiguration)
    assert config.reference_dimension == CURVE_IDENTIFIER
    # Storage-first: schema/identity/FK fields no longer live on the config.
    assert "records" not in CurveDataNodeConfiguration.model_fields
    assert "node_metadata" not in CurveDataNodeConfiguration.model_fields
    assert "foreign_keys" not in CurveDataNodeConfiguration.model_fields


def test_curve_config_uses_curve_identity_not_asset_identity() -> None:
    config = CurveConfig(curve_unique_identifier="mxn_tiie_discount")

    assert config.curve_unique_identifier == "mxn_tiie_discount"
    assert "curve_const" not in CurveConfig.model_fields


def test_discount_curves_node_resolves_storage_and_curve_identity() -> None:
    storage_table = DiscountCurvesNode._required_storage_table()

    assert storage_table is DiscountCurvesStorage
    assert storage_table.metatable_identifier() == "DiscountCurvesTS"
    assert storage_table.__index_names__ == ["time_index", CURVE_IDENTIFIER]
    assert storage_table.__time_index_name__ == "time_index"
    assert "__data_node_identifier__" not in DiscountCurvesNode.__dict__
    assert DiscountCurvesNode._default_identifier() == storage_table.metatable_identifier()
    assert DiscountCurvesNode._default_description() == storage_table.__metatable_description__
    assert "curve_identifier" in DiscountCurvesNode._default_description()
    assert "Curve MetaTable" in DiscountCurvesNode._default_description()


def test_discount_curves_storage_has_curve_foreign_key() -> None:
    curve_identifier = CurveTable.__metatable_identifier__
    fk_column = DiscountCurvesStorage.__table__.columns[CURVE_IDENTIFIER]

    assert markets_foreign_key_target_identifiers(DiscountCurvesStorage) == [curve_identifier]
    assert any(
        foreign_key.column is CurveTable.__table__.c.unique_identifier
        and foreign_key.ondelete == "RESTRICT"
        for foreign_key in fk_column.foreign_keys
    )
    assert DiscountCurvesStorage in set(pricing_sqlalchemy_models())


def test_discount_curves_node_does_not_expose_bootstrap_frame_api() -> None:
    assert not hasattr(DiscountCurvesNode, "build_schema_bootstrap_frame")
    assert not hasattr(DiscountCurvesNode, "build_initialization_frame")


def test_discount_curves_node_validate_frame_normalizes_curve_frame() -> None:
    frame = DiscountCurvesNode.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "curve_identifier": "mxn_tiie_discount",
                    "curve": "compressed-payload",
                }
            ]
        )
    )

    assert list(frame.index.names) == ["time_index", CURVE_IDENTIFIER]
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"
    assert frame.reset_index()[CURVE_IDENTIFIER].tolist() == ["mxn_tiie_discount"]


def test_discount_curves_node_normalizes_curve_identifier_builder_name() -> None:
    time_index = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    frame = pd.DataFrame(
        [
            {
                "time_index": time_index,
                "curve_identifier": "mxn_tiie_discount",
                "curve": {28: 0.11, 91: 0.105},
            }
        ]
    ).set_index(["time_index", "curve_identifier"])

    normalized = DiscountCurvesNode._normalize_builder_frame(
        frame,
        curve_identifier="mxn_tiie_discount",
    )

    assert normalized[CURVE_IDENTIFIER].tolist() == ["mxn_tiie_discount"]


def test_discount_curves_node_rejects_stale_builder_identity_name() -> None:
    with pytest.raises(ValueError, match="curve_identifier"):
        DiscountCurvesNode._normalize_builder_frame(
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_unique_identifier": "mxn_tiie_discount",
                        "curve": {28: 0.11, 91: 0.105},
                    }
                ]
            ),
            curve_identifier="mxn_tiie_discount",
        )


@pytest.mark.skip(reason="requires platform backend (Stage 5 registration)")
def test_discount_curves_node_update_returns_stamped_curve_frame() -> None:
    """A full update() run needs a registered/bound storage table."""

    DiscountCurvesNode(CurveConfig(curve_unique_identifier="mxn_tiie_discount")).update()
