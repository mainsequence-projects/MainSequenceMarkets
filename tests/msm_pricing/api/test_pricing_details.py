from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.models import AssetTable
from msm_pricing.api.pricing_details import (
    DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    AssetCurrentPricingDetails,
    AssetCurrentPricingDetailsUpsert,
)
from msm_pricing.models import AssetCurrentPricingDetailsTable


def test_asset_current_pricing_details_api_declares_table_contract() -> None:
    assert AssetCurrentPricingDetails.__table__ is AssetCurrentPricingDetailsTable
    assert AssetCurrentPricingDetails.__required_tables__ == [
        AssetTable,
        AssetCurrentPricingDetailsTable,
    ]
    assert AssetCurrentPricingDetails.__upsert_keys__ == ("asset_uid",)


def test_pricing_details_payload_requires_timezone_aware_date() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AssetCurrentPricingDetailsUpsert(
            asset_uid=uuid.uuid4(),
            instrument_type="ExampleInstrument",
            instrument_dump={"notional": 100},
            pricing_details_date=dt.datetime(2026, 5, 27),
        )


def test_pricing_details_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssetCurrentPricingDetailsUpsert(
            asset_uid=uuid.uuid4(),
            instrument_type="ExampleInstrument",
            instrument_dump={"notional": 100},
            pricing_details_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
            uid=uuid.uuid4(),
        )


def test_pricing_details_upsert_uses_pricing_runtime_and_asset_uid_conflict_key(
    monkeypatch,
) -> None:
    asset_uid = uuid.uuid4()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_pricing_runtime(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": values}

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr("msm_pricing.api.pricing_details.upsert_model", fake_upsert_model)

    row = AssetCurrentPricingDetails.upsert(
        asset_uid=asset_uid,
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        pricing_details_date=pricing_details_date,
        source="unit-test",
        metadata_json={"provider": "test"},
    )

    assert row == AssetCurrentPricingDetails(
        asset_uid=asset_uid,
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        pricing_details_date=pricing_details_date,
        serialization_format=DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
        source="unit-test",
        metadata_json={"provider": "test"},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [AssetTable, AssetCurrentPricingDetailsTable],
                "row_model_name": "AssetCurrentPricingDetails",
            },
        ),
        (
            "upsert",
            context,
            AssetCurrentPricingDetailsTable,
            {
                "asset_uid": asset_uid,
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "pricing_details_date": pricing_details_date,
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            },
            ("asset_uid",),
        ),
    ]


def test_pricing_details_get_by_asset_uid_uses_primary_key_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    context = object()

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    calls = []

    def fake_get_model_by_uid(active_context, *, model, uid):
        calls.append((active_context, model, uid))
        return {
            "row": {
                "asset_uid": asset_uid,
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "pricing_details_date": pricing_details_date,
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
            }
        }

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.get_model_by_uid",
        fake_get_model_by_uid,
    )

    row = AssetCurrentPricingDetails.get_by_asset_uid(asset_uid)

    assert row is not None
    assert row.asset_uid == asset_uid
    assert calls == [(context, AssetCurrentPricingDetailsTable, asset_uid)]
