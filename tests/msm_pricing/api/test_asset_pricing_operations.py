from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from msm_pricing.api.asset_pricing_operations import (
    UnsupportedAssetPricingOperationError,
    build_asset_pricing_support,
    execute_asset_pricing_operation,
)


class FixedRateBond:
    def __init__(self):
        self.calls = []

    def set_valuation_date(self, valuation_date):
        self.calls.append(("set_valuation_date", valuation_date))

    def price(self, **kwargs):
        self.calls.append(("price", kwargs))
        return 101.25

    def analytics(self, **kwargs):
        self.calls.append(("analytics", kwargs))
        return {
            "clean_price": 100.75,
            "dirty_price": 101.25,
            "accrued_amount": 0.5,
        }

    def duration(self, **kwargs):
        self.calls.append(("duration", kwargs))
        return 4.82

    def get_yield(self, **kwargs):
        self.calls.append(("get_yield", kwargs))
        return 0.0525

    def z_spread(self, **kwargs):
        self.calls.append(("z_spread", kwargs))
        return 0.0042

    def get_cashflows(self, **kwargs):
        self.calls.append(("get_cashflows", kwargs))
        return {
            "fixed": [{"payment_date": dt.date(2026, 12, 9), "amount": 2.5}],
            "redemption": [{"payment_date": dt.date(2030, 6, 9), "amount": 100.0}],
        }

    def get_net_cashflows(self):
        self.calls.append(("get_net_cashflows", {}))
        return {dt.date(2026, 12, 9): 2.5}

    def carry_roll_down(self, horizon_days, *, clean=False):
        self.calls.append(("carry_roll_down", {"horizon_days": horizon_days, "clean": clean}))
        return {
            "cr_dirty": 0.35,
            "roll_down_dirty": 0.2,
        }

    def pricing_engine_id(self):
        self.calls.append(("pricing_engine_id", {}))
        return "engine-id"


def _patch_loaders(monkeypatch, instrument):
    asset_uid = uuid.uuid4()
    asset = SimpleNamespace(uid=asset_uid)
    monkeypatch.setattr(
        "msm_pricing.api.asset_pricing_operations._load_asset",
        lambda uid: asset,
    )
    monkeypatch.setattr(
        "msm_pricing.api.asset_pricing_operations._load_instrument",
        lambda asset: instrument,
    )
    return asset_uid


def test_asset_pricing_support_lists_registered_bond_operations() -> None:
    asset_uid = uuid.uuid4()

    support = build_asset_pricing_support(
        asset_uid=asset_uid,
        instrument_type="FixedRateBond",
    )

    assert support["supported"] is True
    assert {operation["key"] for operation in support["operations"]} == {
        "analytics",
        "carry-roll-down",
        "cashflows",
        "curve-preview",
        "duration",
        "fixings-availability",
        "net-cashflows",
        "price",
        "yield",
        "z-spread",
    }
    price_operation = next(
        operation for operation in support["operations"] if operation["key"] == "price"
    )
    assert price_operation["url"] == f"/api/v1/pricing/assets/{asset_uid}/price/"
    assert price_operation["response_contract"] == "provider-native-json"
    assert price_operation["app_component"] == {
        "output_root": "response:$",
        "flat_outputs": ["price", "units"],
    }

    cashflows_operation = next(
        operation for operation in support["operations"] if operation["key"] == "cashflows"
    )
    assert cashflows_operation["frame_url"] == (
        f"/api/v1/pricing/assets/{asset_uid}/cashflows/frame/"
    )
    assert cashflows_operation["frame_response_model"] == "TabularFrameResponse"
    assert cashflows_operation["frame_response_contract"] == "core.tabular_frame@v1"
    assert cashflows_operation["response_mappings"][0]["contract"] == "core.tabular_frame@v1"


def test_asset_pricing_support_rejects_unsupported_instrument() -> None:
    support = build_asset_pricing_support(
        asset_uid=uuid.uuid4(),
        instrument_type="EquityOption",
    )

    assert support == {
        "supported": False,
        "instrument_type": "EquityOption",
        "operations": [],
        "reason": "Instrument type is not registered for the fixed income pricer API.",
    }


def test_execute_price_delegates_to_instrument_price(monkeypatch) -> None:
    instrument = FixedRateBond()
    asset_uid = _patch_loaders(monkeypatch, instrument)
    valuation_date = dt.datetime(2026, 6, 9, tzinfo=dt.UTC)

    response = execute_asset_pricing_operation(
        asset_uid=asset_uid,
        operation="price",
        valuation_date=valuation_date,
        market_data_set="eod",
        parameters={"with_yield": 0.05},
    )

    assert response["price"] == 101.25
    assert instrument.calls == [
        ("set_valuation_date", valuation_date),
        ("price", {"market_data_set": "eod", "with_yield": 0.05}),
    ]


def test_execute_z_spread_requires_target_dirty_ccy(monkeypatch) -> None:
    asset_uid = _patch_loaders(monkeypatch, FixedRateBond())

    with pytest.raises(ValueError, match="target_dirty_ccy"):
        execute_asset_pricing_operation(
            asset_uid=asset_uid,
            operation="z-spread",
            valuation_date=dt.datetime(2026, 6, 9, tzinfo=dt.UTC),
            market_data_set="eod",
            parameters={},
        )


def test_execute_cashflows_serializes_dates(monkeypatch) -> None:
    instrument = FixedRateBond()
    asset_uid = _patch_loaders(monkeypatch, instrument)

    response = execute_asset_pricing_operation(
        asset_uid=asset_uid,
        operation="cashflows",
        valuation_date=dt.datetime(2026, 6, 9, tzinfo=dt.UTC),
        market_data_set="eod",
        parameters={},
    )

    assert response["legs"]["fixed"][0]["payment_date"] == "2026-12-09"
    assert instrument.calls[-1] == ("get_cashflows", {"market_data_set": "eod"})


def test_execute_carry_roll_down_prices_then_calls_carry(monkeypatch) -> None:
    instrument = FixedRateBond()
    asset_uid = _patch_loaders(monkeypatch, instrument)

    response = execute_asset_pricing_operation(
        asset_uid=asset_uid,
        operation="carry-roll-down",
        valuation_date=dt.datetime(2026, 6, 9, tzinfo=dt.UTC),
        market_data_set="eod",
        parameters={"horizon_days": 30, "clean": True},
    )

    assert response["metrics"] == {"cr_dirty": 0.35, "roll_down_dirty": 0.2}
    assert instrument.calls[-2:] == [
        ("price", {"market_data_set": "eod"}),
        ("carry_roll_down", {"horizon_days": 30, "clean": True}),
    ]


def test_execute_unknown_operation_fails_before_dispatch(monkeypatch) -> None:
    _patch_loaders(monkeypatch, FixedRateBond())

    with pytest.raises(UnsupportedAssetPricingOperationError):
        execute_asset_pricing_operation(
            asset_uid=uuid.uuid4(),
            operation="unknown",
            valuation_date=dt.datetime(2026, 6, 9, tzinfo=dt.UTC),
            market_data_set="eod",
            parameters={},
        )
