from __future__ import annotations

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")


def test_floating_bond_attach_load_round_trip_prices(monkeypatch) -> None:
    from msm.api.assets import Asset
    from msm_pricing.api.pricing_details import AssetCurrentPricingDetails
    from msm_pricing.instruments import FloatingRateBond, Instrument
    from msm_pricing.utils import to_ql_date

    asset_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    row_store: dict[uuid.UUID, AssetCurrentPricingDetails] = {}

    asset = Asset(
        uid=asset_uid,
        unique_identifier="TEST-FRN-2031",
        asset_type="bond",
    )

    def fake_upsert(**kwargs):
        row = AssetCurrentPricingDetails.model_validate(kwargs)
        row_store[row.asset_uid] = row
        return row

    def fake_get_by_asset_uid(target_asset_uid):
        return row_store.get(uuid.UUID(str(target_asset_uid)))

    def fake_resolve_quantlib_index(
        target_index_uid,
        *,
        valuation_date,
        forwarding_curve=None,
        hydrate_fixings=True,
        **_kwargs,
    ):
        assert uuid.UUID(str(target_index_uid)) == index_uid
        ql_date = to_ql_date(valuation_date)
        curve = forwarding_curve
        if curve is None:
            curve = ql.YieldTermStructureHandle(ql.FlatForward(ql_date, 0.05, ql.Actual360()))
        return ql.IborIndex(
            "USD-SOFR-TEST",
            ql.Period("3M"),
            2,
            ql.USDCurrency(),
            ql.UnitedStates(ql.UnitedStates.Settlement),
            ql.ModifiedFollowing,
            False,
            ql.Actual360(),
            curve,
        )

    monkeypatch.setattr(AssetCurrentPricingDetails, "upsert", staticmethod(fake_upsert))
    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "get_by_asset_uid",
        staticmethod(fake_get_by_asset_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_quantlib_index",
        fake_resolve_quantlib_index,
    )

    instrument = FloatingRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 6, 1),
        maturity_date=dt.date(2031, 6, 1),
        day_count=ql.Actual360(),
        calendar=ql.UnitedStates(ql.UnitedStates.Settlement),
        business_day_convention=ql.ModifiedFollowing,
        settlement_days=2,
        coupon_frequency=ql.Period("3M"),
        floating_rate_index_uid=index_uid,
        spread=0.0015,
    )

    instrument.attach_to_asset(
        asset,
        pricing_details_date=valuation_date,
        source="unit-test",
    )
    loaded = Instrument.load_from_asset(asset)
    loaded.set_valuation_date(valuation_date)

    assert isinstance(loaded, FloatingRateBond)
    assert loaded.floating_rate_index_uid == index_uid
    assert loaded._asset_uid == asset_uid
    assert loaded.price(with_yield=0.05) > 0
