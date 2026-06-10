from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_price_fixed_income_asset_route(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 9, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "operation": "price",
            "valuation_date": valuation_date.isoformat(),
            "market_data_set": "eod",
            "price": 101.25,
            "units": "npv",
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_assets.execute_pricing_asset_operation",
        fake_execute,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/pricing/assets/{asset_uid}/price/",
        json={
            "valuation_date": "2026-06-09T00:00:00Z",
            "market_data_set": "eod",
            "parameters": {"with_yield": 0.05},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "asset_uid": str(asset_uid),
        "instrument_type": "FixedRateBond",
        "operation": "price",
        "valuation_date": "2026-06-09T00:00:00Z",
        "market_data_set": "eod",
        "price": 101.25,
        "units": "npv",
    }
    assert captured == {
        "asset_uid": str(asset_uid),
        "operation": "price",
        "valuation_date": valuation_date,
        "market_data_set": "eod",
        "parameters": {"with_yield": 0.05},
    }


def test_fixed_income_routes_validate_operation_responses(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    valuation_date = "2026-06-09T00:00:00Z"

    payloads = {
        "analytics": {
            "analytics": {
                "clean_price": 100.75,
                "dirty_price": 101.25,
                "accrued_amount": 0.5,
            }
        },
        "duration": {"duration_type": "Modified", "duration": 4.82},
        "yield": {"yield": 0.0525},
        "z-spread": {"target_dirty_ccy": 101.25, "z_spread": 0.0042, "units": "decimal"},
        "cashflows": {
            "legs": {
                "fixed": [{"payment_date": "2026-12-09", "amount": 2.5}],
                "redemption": [],
            }
        },
        "net-cashflows": {"cashflows": [{"payment_date": "2026-12-09", "net_cashflow": 2.5}]},
        "carry-roll-down": {"horizon_days": 30, "metrics": {"cr_dirty": 0.35}},
        "curve-preview": {"curves": [], "diagnostics": {"pricing_engine_id": "engine-id"}},
        "fixings-availability": {"status": "available", "fixings": []},
    }

    def fake_execute(**kwargs):
        operation = kwargs["operation"]
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "operation": operation,
            "valuation_date": valuation_date,
            "market_data_set": "eod",
            **payloads[operation],
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_assets.execute_pricing_asset_operation",
        fake_execute,
    )

    client = TestClient(app)
    for operation in payloads:
        response = client.post(
            f"/api/v1/pricing/assets/{asset_uid}/{operation}/",
            json={
                "valuation_date": valuation_date,
                "market_data_set": "eod",
                "parameters": (
                    {"target_dirty_ccy": 101.25}
                    if operation == "z-spread"
                    else {"horizon_days": 30}
                    if operation == "carry-roll-down"
                    else {}
                ),
            },
        )
        assert response.status_code == 200, operation
        assert response.json()["operation"] == operation


def test_cashflows_frame_route_returns_command_center_tabular_contract(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    valuation_date = "2026-06-09T00:00:00Z"

    def fake_execute(**kwargs):
        assert kwargs["operation"] == "cashflows"
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "operation": "cashflows",
            "valuation_date": valuation_date,
            "market_data_set": "eod",
            "legs": {
                "fixed": [{"payment_date": "2026-12-09", "amount": 2.5, "rate": 0.05}],
                "redemption": [{"payment_date": "2030-06-09", "amount": 100.0}],
            },
        }

    monkeypatch.setattr(
        "apps.v1.services.pricing_assets.execute_pricing_asset_operation",
        fake_execute,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/pricing/assets/{asset_uid}/cashflows/frame/",
        json={
            "valuation_date": valuation_date,
            "market_data_set": "eod",
            "parameters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["columns"] == ["leg", "payment_date", "amount", "rate"]
    assert payload["rows"] == [
        {
            "leg": "fixed",
            "payment_date": "2026-12-09",
            "amount": 2.5,
            "rate": 0.05,
        },
        {
            "leg": "redemption",
            "payment_date": "2030-06-09",
            "amount": 100.0,
        },
    ]
    assert payload["fields"][0] == {
        "key": "leg",
        "label": "Leg",
        "description": None,
        "type": "string",
        "nullable": None,
        "nativeType": None,
        "provenance": "manual",
        "reason": None,
        "derivedFrom": None,
        "warnings": None,
    }
    assert payload["source"]["kind"] == "api"
    assert payload["source"]["context"]["operation"] == "cashflows"


def test_net_cashflows_frame_route_returns_command_center_tabular_contract(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    valuation_date = "2026-06-09T00:00:00Z"

    def fake_execute(**kwargs):
        assert kwargs["operation"] == "net-cashflows"
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "operation": "net-cashflows",
            "valuation_date": valuation_date,
            "market_data_set": "eod",
            "cashflows": [
                {"payment_date": "2026-12-09", "net_cashflow": 2.5},
                {"payment_date": "2030-06-09", "net_cashflow": 100.0},
            ],
        }

    monkeypatch.setattr(
        "apps.v1.services.pricing_assets.execute_pricing_asset_operation",
        fake_execute,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/pricing/assets/{asset_uid}/net-cashflows/frame/",
        json={
            "valuation_date": valuation_date,
            "market_data_set": "eod",
            "parameters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["columns"] == ["payment_date", "net_cashflow"]
    assert payload["rows"] == [
        {"payment_date": "2026-12-09", "net_cashflow": 2.5},
        {"payment_date": "2030-06-09", "net_cashflow": 100.0},
    ]
    assert payload["source"]["context"]["operation"] == "net-cashflows"


def test_fixed_income_route_maps_dependency_errors_to_409(monkeypatch) -> None:
    from msm_pricing.api import AssetPricingDependencyError

    def fake_execute(**_kwargs):
        raise AssetPricingDependencyError("missing curve")

    monkeypatch.setattr(
        "apps.v1.routers.pricing_assets.execute_pricing_asset_operation",
        fake_execute,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/pricing/assets/{uuid.uuid4()}/price/",
        json={
            "valuation_date": "2026-06-09T00:00:00Z",
            "market_data_set": "eod",
            "parameters": {},
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "missing curve"}
