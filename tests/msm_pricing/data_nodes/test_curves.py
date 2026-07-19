from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import pytest
from sqlalchemy import Text

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from mainsequence.meta_tables.sqlalchemy_contracts import (
    time_indexed_registration_request_from_sqlalchemy_model,
)
from msm.data_nodes.utils.stamped import StampedDataNodeConfiguration
from msm.models.registration import markets_foreign_key_target_identifiers
from msm_pricing.data_nodes.curve_codec import compress_curve_to_string
from msm_pricing.data_nodes.curves import (
    CURVE_IDENTIFIER,
    CurveConfig,
    CurveDataNodeConfiguration,
    CurveKeyNode,
    CurveKeyNodeSourceReference,
    DiscountCurvesNode,
)
from msm_pricing.data_nodes.curves.key_nodes import (
    KEY_NODES_CODEC_PREFIX,
    compress_key_nodes_to_string,
    decompress_key_nodes_from_string,
    normalize_curve_key_nodes,
)
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
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


def test_discount_curves_node_resolves_storage_and_curve_identity(monkeypatch) -> None:
    storage_table = DiscountCurvesNode._required_storage_table()
    registered_identifier = "registered.discount-curves"
    monkeypatch.setattr(
        storage_table,
        "get_identifier",
        classmethod(lambda _cls: registered_identifier),
    )

    assert storage_table is DiscountCurvesStorage
    assert storage_table.metatable_identifier() == "DiscountCurvesTS"
    assert storage_table.__index_names__ == ["time_index", CURVE_IDENTIFIER]
    assert storage_table.__time_index_name__ == "time_index"
    assert storage_table.__cadence__ == "1d"
    assert "__data_node_identifier__" not in DiscountCurvesNode.__dict__
    assert DiscountCurvesNode._default_identifier() == registered_identifier
    assert DiscountCurvesNode._default_description() == storage_table.__metatable_description__
    assert "curve_identifier" in DiscountCurvesNode._default_description()
    assert "Curve MetaTable" in DiscountCurvesNode._default_description()


def test_discount_curves_storage_has_curve_foreign_key() -> None:
    curve_identifier = CurveTable.__table__.name
    fk_column = DiscountCurvesStorage.__table__.columns[CURVE_IDENTIFIER]

    assert markets_foreign_key_target_identifiers(DiscountCurvesStorage) == [curve_identifier]
    assert any(
        foreign_key.column is CurveTable.__table__.c.unique_identifier
        and foreign_key.ondelete == "RESTRICT"
        for foreign_key in fk_column.foreign_keys
    )
    assert DiscountCurvesStorage in set(pricing_sqlalchemy_models())


def test_discount_curves_storage_declares_key_nodes_and_metadata_columns() -> None:
    columns = DiscountCurvesStorage.__table__.columns

    assert columns["curve"].nullable is False
    assert "key_nodes" in columns
    assert "metadata_json" in columns
    assert columns["key_nodes"].nullable is True
    assert columns["metadata_json"].nullable is True
    assert isinstance(columns["key_nodes"].type, Text)
    assert (
        columns["key_nodes"].info["description"]
        == "Compressed source-owned JSON construction provenance for this curve "
        "observation. Producers pass JSON object/list values and may use the "
        "recommended CurveKeyNode shape, including a typed asset or index "
        "source_reference, quote_type, quote_unit, quote_side, and optional yield "
        "fields, plus source-specific extensions validated by the producer DataNode."
    )
    assert (
        columns["metadata_json"].info["description"]
        == "Optional structured row metadata for curve-source diagnostics, "
        "quality flags, provider snapshots, workflow details, or other "
        "non-pricing provenance."
    )


def test_discount_curves_storage_registration_request_declares_daily_cadence() -> None:
    request = time_indexed_registration_request_from_sqlalchemy_model(
        DiscountCurvesStorage,
        identifier=DiscountCurvesStorage.__table__.name,
        data_source_uid="00000000-0000-0000-0000-000000000000",
    )
    payload = request.model_dump(mode="json")

    assert payload["cadence"] == "1d"
    assert payload["table_contract"]["authoring"]["time_indexed"]["cadence"] == "1d"


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
                    "key_nodes": compress_key_nodes_to_string(
                        [
                            {
                                "maturity_date": "2026-06-24",
                                "source_reference": {
                                    "type": "index",
                                    "identifier": "MXN_TIIE_SWAP_28D",
                                },
                                "quote": 0.11,
                            }
                        ]
                    ),
                    "metadata_json": None,
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
                "key_nodes": [
                    {
                        "maturity_date": dt.date(2026, 6, 24),
                        "source_reference": {
                            "type": "index",
                            "identifier": "MXN_TIIE_SWAP_28D",
                        },
                        "quote": "0.11",
                        "quote_type": "yield",
                        "quote_unit": "decimal",
                        "vendor_extra": {"curve_bucket": "front_end"},
                    }
                ],
                "metadata_json": {"source_snapshot": "mock"},
            }
        ]
    ).set_index(["time_index", "curve_identifier"])

    normalized = DiscountCurvesNode._normalize_builder_frame(
        frame,
        curve_identifier="mxn_tiie_discount",
    )

    assert normalized[CURVE_IDENTIFIER].tolist() == ["mxn_tiie_discount"]
    assert normalized["key_nodes"].tolist() == [
        [
            {
                "maturity_date": "2026-06-24",
                "source_reference": {
                    "type": "index",
                    "identifier": "MXN_TIIE_SWAP_28D",
                },
                "quote": "0.11",
                "quote_type": "yield",
                "quote_unit": "decimal",
                "vendor_extra": {"curve_bucket": "front_end"},
            }
        ]
    ]
    assert normalized["metadata_json"].tolist() == [{"source_snapshot": "mock"}]


def test_discount_curves_node_requires_key_nodes() -> None:
    with pytest.raises(ValueError, match="key_nodes"):
        DiscountCurvesNode._normalize_builder_frame(
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": {28: 0.11, 91: 0.105},
                    }
                ]
            ),
            curve_identifier="mxn_tiie_discount",
        )


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "key_nodes": [{"maturity_date": "2026-06-24", "quote": 0.11}],
                    }
                ]
            ),
            "curve",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": None,
                        "key_nodes": [{"maturity_date": "2026-06-24", "quote": 0.11}],
                    }
                ]
            ),
            "non-empty curve",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": {},
                        "key_nodes": [{"maturity_date": "2026-06-24", "quote": 0.11}],
                    }
                ]
            ),
            "non-empty curve",
        ),
    ],
)
def test_discount_curves_node_requires_curve_payload(frame, message) -> None:
    with pytest.raises(ValueError, match=message):
        DiscountCurvesNode._normalize_builder_frame(
            frame,
            curve_identifier="mxn_tiie_discount",
        )


def test_curve_codec_rejects_null_curve_payload() -> None:
    with pytest.raises(ValueError, match="non-empty mapping"):
        compress_curve_to_string(None)


def test_curve_key_nodes_codec_round_trips_source_owned_json() -> None:
    key_nodes = [
        {
            "maturity_date": "2031-05-27",
            "custom_source_key": "mxn-bono-bucket",
            "quote": 99.25,
            "nested_vendor_payload": {"source_fields": ["bucket", 1, True]},
        }
    ]

    compressed = compress_key_nodes_to_string(key_nodes)

    assert compressed.startswith(KEY_NODES_CODEC_PREFIX)
    assert decompress_key_nodes_from_string(compressed) == key_nodes


def test_curve_key_nodes_codec_rejects_invalid_compressed_payload() -> None:
    with pytest.raises(ValueError, match="compressed payload is invalid"):
        decompress_key_nodes_from_string(f"{KEY_NODES_CODEC_PREFIX}not-base64")


@pytest.mark.parametrize(
    ("key_nodes", "message"),
    [
        ([{"maturity_date": "2026-06-24", "quote": float("nan")}], "finite"),
        ("not-json-container", "object or list"),
        ([{"maturity_date": "2026-06-24", "quote": object()}], "JSON serializable"),
    ],
)
def test_discount_curve_key_nodes_reject_invalid_payloads(key_nodes, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_curve_key_nodes(key_nodes)


def test_discount_curve_key_nodes_accept_source_owned_schema() -> None:
    key_nodes = normalize_curve_key_nodes(
        [
            {
                "maturity_date": dt.date(2026, 6, 24),
                "source_reference": {
                    "type": "asset",
                    "identifier": "MXN_BONO_2031",
                },
                "instrument_type": "fixed_rate_bond",
                "quote": 99.25,
                "quote_type": "clean_price",
                "quote_unit": "price_per_100",
                "quote_side": "mid",
                "vendor_bucket": "long_end",
            },
            {
                "maturity_date": "2027-05-27",
                "instrument_type": "direct_zero_rate",
                "yield": 0.105,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            },
        ]
    )

    assert key_nodes == [
        {
            "maturity_date": "2026-06-24",
            "source_reference": {
                "type": "asset",
                "identifier": "MXN_BONO_2031",
            },
            "instrument_type": "fixed_rate_bond",
            "quote": 99.25,
            "quote_type": "clean_price",
            "quote_unit": "price_per_100",
            "quote_side": "mid",
            "vendor_bucket": "long_end",
        },
        {
            "maturity_date": "2027-05-27",
            "instrument_type": "direct_zero_rate",
            "yield": 0.105,
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
        },
    ]


def test_curve_key_node_helper_serializes_recommended_yield_shape() -> None:
    node = CurveKeyNode(
        source_reference=CurveKeyNodeSourceReference(
            type="asset",
            identifier=" EXAMPLE_BOND_2031 ",
        ),
        maturity_date=dt.date(2027, 5, 27),
        instrument_type="direct_zero_rate",
        quote=0.105,
        quote_type="zero_rate",
        quote_unit="decimal",
        yield_value=0.105,
        source="unit-test",
    )

    assert node.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "source_reference": {
            "type": "asset",
            "identifier": "EXAMPLE_BOND_2031",
        },
        "maturity_date": "2027-05-27",
        "instrument_type": "direct_zero_rate",
        "quote": 0.105,
        "quote_type": "zero_rate",
        "quote_unit": "decimal",
        "quote_side": "mid",
        "yield": 0.105,
        "source": "unit-test",
    }


def test_curve_key_node_helper_accepts_yield_alias() -> None:
    node = CurveKeyNode.model_validate(
        {
            "maturity_date": "2027-05-27",
            "instrument_type": "direct_zero_rate",
            "yield": 0.105,
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
        }
    )

    assert node.yield_value == 0.105
    assert node.model_dump(mode="json", by_alias=True, exclude_none=True)["yield"] == 0.105


def test_curve_key_node_helper_accepts_index_source_reference() -> None:
    node = CurveKeyNode.model_validate(
        {
            "source_reference": {
                "type": "index",
                "identifier": "MXN-TIIE-SWAP-28D",
            },
            "instrument_type": "ois_swap",
            "quote": 0.1095,
            "quote_type": "par_swap_rate",
            "quote_unit": "decimal",
        }
    )

    assert node.source_reference == CurveKeyNodeSourceReference(
        type="index",
        identifier="MXN-TIIE-SWAP-28D",
    )


def test_curve_key_nodes_normalize_typed_source_reference() -> None:
    key_nodes = normalize_curve_key_nodes(
        [
            {
                "source_reference": {
                    "type": "index",
                    "identifier": " MXN-TIIE-SWAP-28D ",
                },
                "quote": 0.1095,
            }
        ]
    )

    assert key_nodes[0]["source_reference"] == {
        "type": "index",
        "identifier": "MXN-TIIE-SWAP-28D",
    }


def test_curve_key_nodes_reject_unsupported_source_reference_type() -> None:
    with pytest.raises(ValueError, match="asset.*index"):
        normalize_curve_key_nodes(
            [
                {
                    "source_reference": {
                        "type": "curve",
                        "identifier": "NOT-A-SOURCE",
                    },
                    "quote": 0.1095,
                }
            ]
        )


@pytest.mark.parametrize("legacy_field", ["asset_identifier", "index_identifier"])
def test_curve_key_nodes_reject_legacy_scalar_source_fields(legacy_field: str) -> None:
    payload = {
        legacy_field: "LEGACY-SOURCE",
        "quote": 0.1095,
        "quote_type": "par_swap_rate",
        "quote_unit": "decimal",
    }

    with pytest.raises(ValueError, match="use source_reference"):
        CurveKeyNode.model_validate(payload)
    with pytest.raises(ValueError, match="use source_reference"):
        normalize_curve_key_nodes([payload])


def test_discount_curves_node_supports_runtime_key_nodes_validator() -> None:
    def validate_valmer_key_nodes(value, *, row, curve_identifier):
        assert curve_identifier == "mxn_tiie_discount"
        assert row["metadata_json"] == {"source_snapshot": "mock"}
        validated = []
        for node in value:
            if node.get("quote_type") != "clean_price":
                raise ValueError("Valmer key nodes must use clean_price quotes.")
            validated.append({**node, "validated_by": "valmer"})
        return validated

    node = object.__new__(DiscountCurvesNode)
    node.set_key_nodes_validator(validate_valmer_key_nodes)

    normalized = node._normalize_builder_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "curve_identifier": "mxn_tiie_discount",
                    "curve": {28: 0.11, 91: 0.105},
                    "key_nodes": [
                        {
                            "maturity_date": "2031-05-27",
                            "source_reference": {
                                "type": "asset",
                                "identifier": "MXN_BONO_2031",
                            },
                            "instrument_type": "fixed_rate_bond",
                            "quote": 99.25,
                            "quote_type": "clean_price",
                            "quote_unit": "price_per_100",
                        }
                    ],
                    "metadata_json": {"source_snapshot": "mock"},
                }
            ]
        ),
        curve_identifier="mxn_tiie_discount",
    )

    assert normalized["key_nodes"].tolist() == [
        [
            {
                "maturity_date": "2031-05-27",
                "source_reference": {
                    "type": "asset",
                    "identifier": "MXN_BONO_2031",
                },
                "instrument_type": "fixed_rate_bond",
                "quote": 99.25,
                "quote_type": "clean_price",
                "quote_unit": "price_per_100",
                "validated_by": "valmer",
            }
        ]
    ]


def test_discount_curves_node_subclass_can_override_key_nodes_validation() -> None:
    class StrictDiscountCurvesNode(DiscountCurvesNode):
        def normalize_key_nodes(self, value, *, row, curve_identifier):
            normalized = super().normalize_key_nodes(
                value,
                row=row,
                curve_identifier=curve_identifier,
            )
            return [
                CurveKeyNode.model_validate(node).model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                for node in normalized
            ]

    node = object.__new__(StrictDiscountCurvesNode)
    node.key_nodes_validator = None

    normalized = node._normalize_builder_frame(
        pd.DataFrame(
            [
                {
                    "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                    "curve_identifier": "mxn_tiie_discount",
                    "curve": {28: 0.11, 91: 0.105},
                    "key_nodes": [
                        {
                            "maturity_date": "2027-05-27",
                            "instrument_type": "direct_zero_rate",
                            "yield": 0.105,
                            "quote_type": "zero_rate",
                            "quote_unit": "decimal",
                        }
                    ],
                }
            ]
        ),
        curve_identifier="mxn_tiie_discount",
    )

    assert normalized["key_nodes"].tolist() == [
        [
            {
                "maturity_date": "2027-05-27",
                "instrument_type": "direct_zero_rate",
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
                "quote_side": "mid",
                "yield": 0.105,
            }
        ]
    ]


def test_discount_curves_node_rejects_stale_builder_identity_name() -> None:
    with pytest.raises(ValueError, match="curve_identifier"):
        DiscountCurvesNode._normalize_builder_frame(
            pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_unique_identifier": "mxn_tiie_discount",
                        "curve": {28: 0.11, 91: 0.105},
                        "key_nodes": [{"maturity_date": "2026-06-24", "quote": 0.11}],
                    }
                ]
            ),
            curve_identifier="mxn_tiie_discount",
        )


@pytest.mark.skip(reason="requires platform backend (Stage 5 registration)")
def test_discount_curves_node_update_returns_stamped_curve_frame() -> None:
    """A full update() run needs a registered/bound storage table."""

    DiscountCurvesNode(CurveConfig(curve_unique_identifier="mxn_tiie_discount")).update()
