"""`POST /api/v1/account/{account_uid}/virtual-fund-allocations/` and its typed client method."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.accounts import AccountVirtualFundAllocationResponse
from msm.client import MarketsClient

ACCOUNT_UID = str(uuid.uuid4())
HOLDINGS_SET_UID = str(uuid.uuid4())
POSITION_SET_UID = str(uuid.uuid4())
USD_UID = str(uuid.uuid4())
CAPTURE_TIME = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)


def _plan(*, applied: bool) -> dict[str, Any]:
    return {
        "account_uid": ACCOUNT_UID,
        "holdings_set_uid": HOLDINGS_SET_UID,
        "position_set_uid": POSITION_SET_UID,
        "valuation_time": CAPTURE_TIME,
        "valuation_asset_uid": USD_UID,
        "allocation_mode": "proportional_attribution",
        "status": "feasible",
        "account_nav": 645_000.0,
        "applied": applied,
        "funds": [
            {
                "virtual_fund_unique_identifier": "account-virtual-fund-x",
                "target_portfolio_uid": str(uuid.uuid4()),
                "virtual_fund_uid": str(uuid.uuid4()) if applied else None,
                "holdings_set_uid": str(uuid.uuid4()) if applied else None,
                "requested_notional": 64_500.0,
                "allocated_notional": 64_500.0,
            }
        ],
        "allocations": [],
        "residuals": [],
        "deficits": [],
        "warnings": [
            {
                "code": "portfolio_weights_as_of",
                "message": "weights from earlier",
                "severity": "warning",
                "details": {},
            }
        ],
    }


@pytest.fixture
def service(monkeypatch):
    from apps.v1.services import accounts as account_service

    calls: list[dict[str, Any]] = []
    writes: list[str] = []

    def fake_allocate(context, **kwargs):
        calls.append(kwargs)
        return _plan(applied=kwargs["apply"])

    monkeypatch.setattr(
        account_service,
        "_get_virtual_fund_allocation_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(account_service, "_allocate_account_holdings_set", fake_allocate)
    monkeypatch.setattr(
        "apps.v1.identity.record_registry_write",
        lambda action, **kwargs: writes.append(action),
    )
    return SimpleNamespace(calls=calls, writes=writes, module=account_service)


def _post(body: dict[str, Any], account_uid: str = ACCOUNT_UID):
    return TestClient(app).post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/", json=body
    )


def test_a_dry_run_answers_the_plan_and_records_no_write(service) -> None:
    response = _post({"holdings_set_uid": HOLDINGS_SET_UID, "valuation_asset_uid": USD_UID})

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied"] is False
    assert payload["warnings"][0]["code"] == "portfolio_weights_as_of"
    [call] = service.calls
    assert call["apply"] is False
    assert call["position_set_uid"] is None
    assert call["allocation_policy"].mode == "proportional_attribution"
    assert call["allocation_policy"].stale_valuation_policy == "allow_latest"
    assert service.writes == []


def test_apply_is_a_registry_write(service) -> None:
    response = _post(
        {
            "holdings_set_uid": HOLDINGS_SET_UID,
            "valuation_asset_uid": USD_UID,
            "position_set_uid": POSITION_SET_UID,
            "allocation_policy": {"mode": "strict_feasible", "stale_data_policy": "reject"},
            "apply": True,
        }
    )

    assert response.status_code == 200
    assert response.json()["funds"][0]["virtual_fund_uid"] is not None
    [call] = service.calls
    assert call["position_set_uid"] == POSITION_SET_UID
    assert call["allocation_policy"].mode == "strict_feasible"
    assert call["allocation_policy"].shortage_policy == "fail"
    assert call["allocation_policy"].stale_weight_policy == "reject"
    assert service.writes == ["apply:account-virtual-fund-allocation"]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ValueError("ms-markets has no price for ['SOL']"), 400),
        (LookupError("Account holdings set x was not found"), 404),
    ],
)
def test_planner_failures_map_to_http_errors(monkeypatch, service, error, status_code) -> None:
    def failing(context, **kwargs):
        raise error

    monkeypatch.setattr(service.module, "_allocate_account_holdings_set", failing)

    response = _post({"holdings_set_uid": HOLDINGS_SET_UID, "valuation_asset_uid": USD_UID})

    assert response.status_code == status_code
    assert str(error) in response.json()["detail"]


def test_an_unknown_account_is_404(monkeypatch, service) -> None:
    monkeypatch.setattr(
        service.module, "_allocate_account_holdings_set", lambda context, **kw: None
    )

    response = _post({"holdings_set_uid": HOLDINGS_SET_UID, "valuation_asset_uid": USD_UID})

    assert response.status_code == 404


def test_the_request_rejects_unknown_fields(service) -> None:
    response = _post(
        {"holdings_set_uid": HOLDINGS_SET_UID, "valuation_asset_uid": USD_UID, "prices": {}}
    )

    assert response.status_code == 422


def test_the_client_allocates_without_building_paths(service) -> None:
    client = MarketsClient("http://testserver", session=TestClient(app))

    result = client.allocate_account_virtual_funds(
        ACCOUNT_UID,
        holdings_set_uid=HOLDINGS_SET_UID,
        valuation_asset_uid=USD_UID,
        apply=True,
    )

    assert isinstance(result, AccountVirtualFundAllocationResponse)
    assert result.applied is True
    assert result.valuation_time == CAPTURE_TIME
    [call] = service.calls
    assert call["holdings_set_uid"] == HOLDINGS_SET_UID
    assert call["apply"] is True


def test_openapi_documents_the_allocation_route() -> None:
    operation = app.openapi()["paths"]["/api/v1/account/{account_uid}/virtual-fund-allocations/"][
        "post"
    ]

    assert operation["operationId"] == "allocateAccountVirtualFunds"
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountVirtualFundAllocationRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountVirtualFundAllocationResponse"
    }
