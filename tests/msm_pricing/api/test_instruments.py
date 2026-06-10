from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest

from msm.api.assets import Asset
from msm_pricing.api.instruments import (
    add_pricing_details,
    load_instrument_from_asset,
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


def _asset(*, asset_type: str = "example_asset") -> Asset:
    return Asset(
        uid=uuid.uuid4(),
        unique_identifier="example",
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


def test_instrument_attach_to_asset_is_primary_user_write_path(monkeypatch) -> None:
    asset = _asset()
    instrument = ApiExampleInstrument(notional=100)
    calls = []

    def fake_add_pricing_details(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(current_pricing_details=SimpleNamespace(asset_uid=kwargs["asset"].uid))

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
