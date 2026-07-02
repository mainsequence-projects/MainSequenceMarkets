from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import json
import uuid

import pytest
from pydantic import ValidationError

ql = pytest.importorskip("QuantLib")

from msm.api.assets import Asset
from msm_pricing.api.pricing_details import (
    AssetCurrentPricingDetails,
    AssetPricingDetails,
    AssetPricingDetailsAddResult,
)
from msm_pricing.instruments import FloatingRateBond, InterestRateSwap


def _asset() -> Asset:
    return Asset(
        uid=uuid.uuid4(),
        unique_identifier="example-bond",
        asset_type="bond",
    )


def _floating_bond(index_uid: uuid.UUID) -> FloatingRateBond:
    return FloatingRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 1, 1),
        maturity_date=dt.date(2031, 1, 1),
        day_count=ql.Actual360(),
        calendar=ql.TARGET(),
        business_day_convention=ql.Following,
        settlement_days=2,
        coupon_frequency=ql.Period("3M"),
        floating_rate_index_uid=index_uid,
        spread=0.0,
    )


def _swap(index_uid: uuid.UUID) -> InterestRateSwap:
    return InterestRateSwap(
        notional=1_000_000.0,
        start_date=dt.date(2026, 1, 1),
        maturity_date=dt.date(2031, 1, 1),
        fixed_rate=0.05,
        fixed_leg_tenor=ql.Period("1Y"),
        fixed_leg_convention=ql.Following,
        fixed_leg_daycount=ql.Actual360(),
        float_leg_tenor=ql.Period("3M"),
        float_leg_spread=0.0,
        float_leg_index_uid=index_uid,
    )


def test_bond_serialized_payload_stores_backend_index_uid() -> None:
    index_uid = uuid.uuid4()
    payload = json.loads(_floating_bond(index_uid).serialize_for_backend())

    instrument = payload["instrument"]
    assert instrument["floating_rate_index_uid"] == str(index_uid)
    assert "floating_rate_index_name" not in instrument


def test_swap_serialized_payload_stores_backend_index_uid() -> None:
    index_uid = uuid.uuid4()
    payload = json.loads(_swap(index_uid).serialize_for_backend())

    instrument = payload["instrument"]
    assert instrument["float_leg_index_uid"] == str(index_uid)
    assert "float_leg_index_name" not in instrument


def test_bond_payload_rejects_stale_index_name_field() -> None:
    with pytest.raises(ValidationError, match="floating_rate_index_name"):
        FloatingRateBond.model_validate(
            {
                "face_value": 100.0,
                "issue_date": "2026-01-01",
                "maturity_date": "2031-01-01",
                "day_count": "Actual360",
                "calendar": {"name": "TARGET"},
                "business_day_convention": "Following",
                "settlement_days": 2,
                "coupon_frequency": "3M",
                "floating_rate_index_name": "USD-SOFR",
                "spread": 0.0,
            }
        )


def test_swap_payload_rejects_stale_index_name_field() -> None:
    with pytest.raises(ValidationError, match="float_leg_index_name"):
        InterestRateSwap.model_validate(
            {
                "notional": 1_000_000.0,
                "start_date": "2026-01-01",
                "maturity_date": "2031-01-01",
                "fixed_rate": 0.05,
                "fixed_leg_tenor": "1Y",
                "fixed_leg_convention": "Following",
                "fixed_leg_daycount": "Actual360",
                "float_leg_tenor": "3M",
                "float_leg_spread": 0.0,
                "float_leg_index_name": "USD-SOFR",
            }
        )


def test_bond_resolver_receives_backend_index_uid(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    bond = _floating_bond(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )
    monkeypatch.setattr(
        FloatingRateBond,
        "_register_index_observer",
        lambda self: None,
    )

    bond.set_valuation_date(valuation_date)
    bond._ensure_index()

    assert calls == [
        (
            index_uid,
            {
                "valuation_date": valuation_date,
                "forwarding_curve": None,
                "hydrate_fixings": True,
                "market_data_set": None,
                "role_key": "projection",
                "quote_side": None,
            },
        )
    ]


def test_bond_resolver_receives_explicit_market_data_set_uid(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    bond = _floating_bond(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: market_data_set_uid if selector == "eod" else None),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )
    monkeypatch.setattr(
        FloatingRateBond,
        "_register_index_observer",
        lambda self: None,
    )

    bond._apply_market_data_set("eod")
    bond.set_valuation_date(valuation_date)
    bond._ensure_index()

    assert calls[0][0] == index_uid
    assert calls[0][1]["market_data_set"] == market_data_set_uid


def test_bond_resolver_receives_curve_quote_side(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    bond = _floating_bond(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )
    monkeypatch.setattr(
        FloatingRateBond,
        "_register_index_observer",
        lambda self: None,
    )

    bond._apply_curve_quote_side(" MID ")
    bond.set_valuation_date(valuation_date)
    bond._ensure_index()

    assert calls[0][0] == index_uid
    assert calls[0][1]["quote_side"] == "mid"


def test_swap_resolver_receives_backend_index_uid(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    swap = _swap(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.interest_rate_swap.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )

    swap.set_valuation_date(valuation_date)
    swap._ensure_index()

    assert calls == [
        (
            index_uid,
            {
                "valuation_date": valuation_date,
                "hydrate_fixings": True,
                "market_data_set": None,
                "role_key": "projection",
                "quote_side": None,
            },
        )
    ]


def test_swap_resolver_receives_explicit_market_data_set_uid(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    swap = _swap(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.interest_rate_swap.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: market_data_set_uid if selector == "live" else None),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.interest_rate_swap.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )

    swap._apply_market_data_set("live")
    swap.set_valuation_date(valuation_date)
    swap._ensure_index()

    assert calls[0][0] == index_uid
    assert calls[0][1]["market_data_set"] == market_data_set_uid


def test_swap_resolver_receives_curve_quote_side(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    swap = _swap(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.interest_rate_swap.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )

    swap._apply_curve_quote_side(" OFFER ")
    swap.set_valuation_date(valuation_date)
    swap._ensure_index()

    assert calls[0][0] == index_uid
    assert calls[0][1]["quote_side"] == "offer"


def test_swap_reset_curve_accepts_yield_term_structure_handle(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    swap = _swap(index_uid)
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    handle = ql.YieldTermStructureHandle(
        ql.FlatForward(ql.Date(27, 5, 2026), 0.05, ql.Actual360())
    )
    calls = []

    class FakeIndex:
        pass

    monkeypatch.setattr(
        "msm_pricing.instruments.interest_rate_swap.resolve_quantlib_index",
        lambda backend_index_uid, **kwargs: (
            calls.append((backend_index_uid, kwargs)) or FakeIndex()
        ),
    )

    swap.set_valuation_date(valuation_date)
    swap.reset_curve(handle)

    assert calls == [
        (
            index_uid,
            {
                "valuation_date": valuation_date,
                "market_data_set": None,
                "forwarding_curve": handle,
                "hydrate_fixings": True,
            },
        )
    ]


def test_attach_load_round_trip_preserves_bond_index_uid(monkeypatch) -> None:
    asset = _asset()
    index_uid = uuid.uuid4()
    bond = _floating_bond(index_uid)
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    stored: dict[str, object] = {}

    def fake_add(**kwargs):
        stored.update(kwargs)
        current = AssetCurrentPricingDetails(
            asset_uid=kwargs["asset_uid"],
            instrument_type=kwargs["instrument_type"],
            instrument_dump=kwargs["instrument_dump"],
            pricing_details_date=kwargs["pricing_details_date"],
            serialization_format=kwargs["serialization_format"],
            pricing_package_version=kwargs["pricing_package_version"],
            source=kwargs["source"],
            metadata_json=kwargs["metadata_json"],
        )
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
            current_pricing_details=current,
            updated_current=True,
        )

    monkeypatch.setattr(AssetPricingDetails, "add", staticmethod(fake_add))

    bond.attach_to_asset(
        asset,
        pricing_details_date=pricing_details_date,
        source="unit-test",
    )

    assert stored["instrument_dump"]["floating_rate_index_uid"] == str(index_uid)

    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_by_asset_uid",
        staticmethod(
            lambda asset_uid: AssetCurrentPricingDetails(
                asset_uid=asset_uid,
                instrument_type=stored["instrument_type"],
                instrument_dump=stored["instrument_dump"],
                pricing_details_date=pricing_details_date,
            )
        ),
    )

    loaded = FloatingRateBond.load_from_asset(asset)

    assert loaded.floating_rate_index_uid == index_uid
    assert loaded._asset_uid == asset.uid
