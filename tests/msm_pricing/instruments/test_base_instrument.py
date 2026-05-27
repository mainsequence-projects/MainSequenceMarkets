from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from msm_pricing.instruments.base_instrument import InstrumentModel


class ExampleInstrument(InstrumentModel):
    notional: float


def test_instrument_model_has_no_persistence_identity_fields() -> None:
    assert "main_sequence_asset_id" not in InstrumentModel.model_fields
    assert "asset_uid" not in InstrumentModel.model_fields
    assert "uid" not in InstrumentModel.model_fields


def test_instrument_serialization_is_identity_free() -> None:
    payload = json.loads(ExampleInstrument(notional=100).serialize_for_backend())

    assert payload["instrument_type"] == "ExampleInstrument"
    assert payload["instrument"] == {"notional": 100.0}
    assert "main_sequence_asset_id" not in payload["instrument"]
    assert "asset_uid" not in payload["instrument"]
    assert "uid" not in payload["instrument"]


def test_instrument_model_rejects_legacy_main_sequence_asset_id() -> None:
    with pytest.raises(ValidationError, match="main_sequence_asset_id"):
        ExampleInstrument.model_validate(
            {
                "notional": 100,
                "main_sequence_asset_id": 123,
            }
        )


def test_instrument_model_rejects_legacy_index_name_relationship_fields() -> None:
    with pytest.raises(ValidationError, match="float_leg_index_name"):
        ExampleInstrument.model_validate(
            {
                "notional": 100,
                "float_leg_index_name": "USD-SOFR",
            }
        )


def test_rebuild_rejects_legacy_main_sequence_asset_id_inside_instrument_payload() -> None:
    with pytest.raises(ValidationError, match="main_sequence_asset_id"):
        InstrumentModel.rebuild(
            {
                "instrument_type": "ExampleInstrument",
                "instrument": {
                    "notional": 100,
                    "main_sequence_asset_id": 123,
                },
            },
            registry={"ExampleInstrument": ExampleInstrument},
        )


def test_rebuild_keeps_supported_identity_free_payloads() -> None:
    rebuilt = InstrumentModel.rebuild(
        {
            "instrument_type": "ExampleInstrument",
            "instrument": {
                "notional": 100,
            },
        },
        registry={"ExampleInstrument": ExampleInstrument},
    )

    assert rebuilt == ExampleInstrument(notional=100)
