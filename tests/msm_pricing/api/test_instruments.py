from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest

from msm.api.assets import Asset
from msm_pricing.api.instruments import (
    AssetInstrumentPricingDetailsAdd,
    add_many_pricing_details,
    add_pricing_details,
    load_instrument_from_asset,
    load_instruments_from_assets,
)
from msm_pricing.api.pricing_details import (
    AssetCurrentPricingDetails,
    AssetPricingDetails,
    AssetPricingDetailsAddResult,
)
from msm_pricing.instruments.base_instrument import InstrumentModel


class ApiExampleInstrument(InstrumentModel):
    expected_asset_type: ClassVar[str] = "example_asset"

    notional: float

    def price(self) -> float:
        return self.notional


class ApiOtherInstrument(InstrumentModel):
    expected_asset_type: ClassVar[str] = "example_asset"

    notional: float


def _asset(
    *,
    asset_type: str = "example_asset",
    unique_identifier: str = "example",
) -> Asset:
    return Asset(
        uid=uuid.uuid4(),
        unique_identifier=unique_identifier,
        asset_type=asset_type,
    )


def test_add_pricing_details_serializes_identity_free_terms(monkeypatch) -> None:
    asset = _asset()
    instrument = ApiExampleInstrument(notional=100)
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    def fake_add(**kwargs):
        calls.append(kwargs)
        pricing_details = AssetPricingDetails(
            time_index=kwargs["pricing_details_date"],
            asset_identifier=kwargs["asset_identifier"],
            instrument_type=kwargs["instrument_type"],
            instrument_dump=kwargs["instrument_dump"],
            serialization_format=kwargs["serialization_format"],
            pricing_package_version=kwargs["pricing_package_version"],
            source=kwargs["source"],
            metadata_json=kwargs["metadata_json"],
        )
        return AssetPricingDetailsAddResult(
            pricing_details=pricing_details,
            current_pricing_details=None,
            updated_current=False,
        )

    monkeypatch.setattr(AssetPricingDetails, "add", staticmethod(fake_add))

    result = add_pricing_details(
        asset=asset,
        instrument=instrument,
        pricing_details_date=pricing_details_date,
        source="unit-test",
        metadata_json={"source": "test"},
    )

    assert result.current_pricing_details is None
    assert result.updated_current is False
    assert instrument._asset_uid == asset.uid
    assert calls == [
        {
            "asset_uid": asset.uid,
            "asset_identifier": asset.unique_identifier,
            "instrument_type": "ApiExampleInstrument",
            "instrument_dump": {"notional": 100.0},
            "pricing_details_date": pricing_details_date,
            "serialization_format": "msm_pricing.instrument.v1",
            "pricing_package_version": None,
            "source": "unit-test",
            "metadata_json": {"source": "test"},
        }
    ]


def test_add_pricing_details_without_date_delegates_current_update(monkeypatch) -> None:
    asset = _asset()
    instrument = ApiExampleInstrument(notional=100)
    calls = []

    def fake_add(**kwargs):
        calls.append(kwargs)
        pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
        pricing_details = AssetPricingDetails(
            time_index=pricing_details_date,
            asset_identifier=kwargs["asset_identifier"],
            instrument_type=kwargs["instrument_type"],
            instrument_dump=kwargs["instrument_dump"],
            serialization_format=kwargs["serialization_format"],
            pricing_package_version=kwargs["pricing_package_version"],
            source=kwargs["source"],
            metadata_json=kwargs["metadata_json"],
        )
        return AssetPricingDetailsAddResult(
            pricing_details=pricing_details,
            current_pricing_details=AssetCurrentPricingDetails(
                asset_uid=kwargs["asset_uid"],
                instrument_type=kwargs["instrument_type"],
                instrument_dump=kwargs["instrument_dump"],
                pricing_details_date=pricing_details_date,
            ),
            updated_current=True,
        )

    monkeypatch.setattr(AssetPricingDetails, "add", staticmethod(fake_add))

    result = add_pricing_details(asset=asset, instrument=instrument)

    assert result.updated_current is True
    assert calls[0]["pricing_details_date"] is None


def test_add_many_pricing_details_serializes_instruments_in_one_batch(monkeypatch) -> None:
    first_asset = _asset(unique_identifier="asset-1")
    second_asset = _asset(unique_identifier="asset-2")
    first_instrument = ApiExampleInstrument(notional=100)
    second_instrument = ApiExampleInstrument(notional=200)
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    def fake_add_many(payloads, *, batch_size):
        calls.append((payloads, batch_size))
        pricing_details = [
            AssetPricingDetails(
                time_index=payload.pricing_details_date or pricing_details_date,
                asset_identifier=payload.asset_identifier,
                instrument_type=payload.instrument_type,
                instrument_dump=payload.instrument_dump,
                serialization_format=payload.serialization_format,
                pricing_package_version=payload.pricing_package_version,
                source=payload.source,
                metadata_json=payload.metadata_json,
            )
            for payload in payloads
        ]
        return SimpleNamespace(
            pricing_details=pricing_details,
            current_pricing_details=[],
            updated_current=False,
            updated_current_count=0,
        )

    monkeypatch.setattr(AssetPricingDetails, "add_many", staticmethod(fake_add_many))

    result = add_many_pricing_details(
        [
            AssetInstrumentPricingDetailsAdd(
                asset=first_asset,
                instrument=first_instrument,
                source="item-source",
            ),
            {
                "asset": second_asset,
                "instrument": second_instrument,
                "pricing_details_date": pricing_details_date,
            },
        ],
        source="batch-source",
        metadata_json={"batch": True},
        batch_size=500,
    )

    payloads, batch_size = calls[0]
    assert batch_size == 500
    assert [payload.asset_uid for payload in payloads] == [first_asset.uid, second_asset.uid]
    assert [payload.asset_identifier for payload in payloads] == ["asset-1", "asset-2"]
    assert [payload.instrument_dump for payload in payloads] == [
        {"notional": 100.0},
        {"notional": 200.0},
    ]
    assert payloads[0].pricing_details_date is None
    assert payloads[0].source == "item-source"
    assert payloads[1].pricing_details_date == pricing_details_date
    assert payloads[1].source == "batch-source"
    assert first_instrument._asset_uid == first_asset.uid
    assert second_instrument._asset_uid == second_asset.uid
    assert len(result.pricing_details) == 2


def test_instrument_attach_to_asset_is_primary_user_write_path(monkeypatch) -> None:
    asset = _asset()
    instrument = ApiExampleInstrument(notional=100)
    calls = []

    def fake_add_pricing_details(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            current_pricing_details=SimpleNamespace(asset_uid=kwargs["asset"].uid)
        )

    monkeypatch.setattr(
        "msm_pricing.api.instruments.add_pricing_details",
        fake_add_pricing_details,
    )

    attached = instrument.attach_to_asset(asset, source="unit-test")

    assert attached is instrument
    assert instrument._asset_uid == asset.uid
    assert calls == [
        {
            "asset": asset,
            "instrument": instrument,
            "source": "unit-test",
        }
    ]


def test_instrument_attach_to_asset_validates_asset_type() -> None:
    with pytest.raises(ValueError, match="asset_type='example_asset'"):
        ApiExampleInstrument(notional=100).attach_to_asset(_asset(asset_type="wrong"))


def test_load_instrument_from_asset_rebuilds_concrete_instrument(monkeypatch) -> None:
    asset = _asset()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_by_asset_uid",
        staticmethod(
            lambda asset_uid: AssetCurrentPricingDetails(
                asset_uid=asset_uid,
                instrument_type="ApiExampleInstrument",
                instrument_dump={"notional": 100},
                pricing_details_date=pricing_details_date,
            )
        ),
    )

    instrument = load_instrument_from_asset(asset)

    assert isinstance(instrument, ApiExampleInstrument)
    assert instrument.notional == 100
    assert instrument._asset_uid == asset.uid


def test_load_instruments_from_assets_rebuilds_current_instruments_in_bulk(monkeypatch) -> None:
    first_asset = _asset(unique_identifier="asset-1")
    second_asset = _asset(unique_identifier="asset-2")
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    def fake_get_many_by_asset_uid(asset_uids, *, batch_size):
        calls.append((asset_uids, batch_size))
        return {
            first_asset.uid: AssetCurrentPricingDetails(
                asset_uid=first_asset.uid,
                instrument_type="ApiExampleInstrument",
                instrument_dump={"notional": 100},
                pricing_details_date=pricing_details_date,
            ),
            second_asset.uid: AssetCurrentPricingDetails(
                asset_uid=second_asset.uid,
                instrument_type="ApiExampleInstrument",
                instrument_dump={"notional": 200},
                pricing_details_date=pricing_details_date,
            ),
        }

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_many_by_asset_uid",
        staticmethod(fake_get_many_by_asset_uid),
    )

    instruments = load_instruments_from_assets(
        [first_asset, second_asset, first_asset],
        batch_size=250,
    )

    assert calls == [([first_asset.uid, second_asset.uid], 250)]
    assert list(instruments) == [first_asset.uid, second_asset.uid]
    assert isinstance(instruments[first_asset.uid], ApiExampleInstrument)
    assert instruments[first_asset.uid].notional == 100
    assert instruments[first_asset.uid]._asset_uid == first_asset.uid
    assert instruments[second_asset.uid].notional == 200
    assert instruments[second_asset.uid]._asset_uid == second_asset.uid


def test_load_instruments_from_assets_raises_for_missing_current_rows(monkeypatch) -> None:
    asset = _asset()

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_many_by_asset_uid",
        staticmethod(lambda _asset_uids, *, batch_size: {}),
    )

    with pytest.raises(LookupError, match=str(asset.uid)):
        load_instruments_from_assets([asset])


def test_load_instruments_from_assets_can_allow_missing_current_rows(monkeypatch) -> None:
    asset = _asset()

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_many_by_asset_uid",
        staticmethod(lambda _asset_uids, *, batch_size: {}),
    )

    assert load_instruments_from_assets([asset], allow_missing=True) == {}


def test_load_instruments_from_assets_empty_input_skips_current_lookup(monkeypatch) -> None:
    def fail_get_many_by_asset_uid(_asset_uids, *, batch_size):
        raise AssertionError("current pricing details should not be loaded")

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_many_by_asset_uid",
        staticmethod(fail_get_many_by_asset_uid),
    )

    assert load_instruments_from_assets([]) == {}


def test_generic_instrument_load_from_asset_dispatches_to_concrete_type(monkeypatch) -> None:
    asset = _asset()
    loaded = ApiExampleInstrument(notional=100)

    monkeypatch.setattr(
        "msm_pricing.api.instruments.load_instrument_from_asset",
        lambda asset, **_kwargs: loaded,
    )

    instrument = InstrumentModel.load_from_asset(asset)

    assert instrument is loaded
    assert isinstance(instrument, ApiExampleInstrument)
    assert instrument._asset_uid == asset.uid


def test_typed_instrument_load_from_asset_rejects_mismatched_type(monkeypatch) -> None:
    asset = _asset()

    monkeypatch.setattr(
        "msm_pricing.api.instruments.load_instrument_from_asset",
        lambda asset, **_kwargs: ApiOtherInstrument(notional=100),
    )

    with pytest.raises(TypeError, match="not ApiExampleInstrument"):
        ApiExampleInstrument.load_from_asset(asset)
