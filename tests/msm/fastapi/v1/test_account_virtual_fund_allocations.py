"""The virtual-fund allocation routes and their ``MarketsClient`` methods (ADR 0053)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from apps.v1.main import app
from msm.api.accounts import (
    AccountVirtualFundAllocationPlanResponse,
    AccountVirtualFundAllocationResponse,
    VirtualFundAllocationPolicyDescription,
)
from msm.api.remote import MarketsConflictError
from msm.client import MarketsClient
from msm.services.accounts.allocation_policies import AllocationError
from msm.services.portfolio_lifecycle import PortfolioRetiredError

VALUATION_TIME = dt.datetime(2026, 11, 14, 21, tzinfo=dt.UTC)
POLICIES_PATH = "/api/v1/account/virtual-fund-allocation-policies/"


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client(http) -> MarketsClient:
    return MarketsClient("http://testserver", session=http)


@pytest.fixture
def account_uid() -> str:
    return str(uuid.uuid4())


def _plan_payload(account_uid: str, **extra) -> dict[str, object]:
    asset_uid, portfolio_uid = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "account_uid": account_uid,
        "holdings_set_uid": str(uuid.uuid4()),
        "position_set_uid": str(uuid.uuid4()),
        "valuation_time": VALUATION_TIME,
        "policy": {
            "id": "proportional_attribution",
            "version": "1.0.0",
            "arguments": {"quantity_tolerance": 1e-9},
        },
        "funds": [
            {"virtual_fund_unique_identifier": "fund-a", "target_portfolio_uid": portfolio_uid}
        ],
        "lines": [
            {
                "owner": "fund",
                "asset_uid": asset_uid,
                "asset_identifier": "MSFT",
                "target": 500.0,
                "assigned": 375.0,
                "delta": 125.0,
                "target_portfolio_uid": portfolio_uid,
                "virtual_fund_unique_identifier": "fund-a",
            },
            {
                "owner": "direct",
                "asset_uid": str(uuid.uuid4()),
                "asset_identifier": "TSLA",
                "target": 0.0,
                "assigned": 1100.0,
                "delta": -1100.0,
            },
        ],
        "account_deltas": [
            {
                "asset_uid": asset_uid,
                "asset_identifier": "MSFT",
                "held": 600.0,
                "target": 800.0,
                "delta": 200.0,
            }
        ],
        "apply_blockers": [],
        "plan_digest": "sha256:" + "a" * 64,
        **extra,
    }


# The policy catalog -------------------------------------------------------------------


def test_the_catalog_lists_every_policy_with_the_path_of_its_description(http) -> None:
    response = http.get(POLICIES_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "policies": [
            {
                "id": "proportional_attribution",
                "version": "1.0.0",
                "title": "Proportional attribution",
                "description": response.json()["policies"][0]["description"],
                "path": f"{POLICIES_PATH}proportional_attribution/",
            }
        ]
    }
    assert http.get(response.json()["policies"][0]["path"]).status_code == 200


def test_a_policy_is_described_with_its_arguments_json_schema(http) -> None:
    response = http.get(f"{POLICIES_PATH}proportional_attribution/")

    assert response.status_code == 200
    description = response.json()
    assert (description["id"], description["version"]) == ("proportional_attribution", "1.0.0")
    argument = description["arguments"]["quantity_tolerance"]
    assert argument["required"] is False
    assert argument["schema"]["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert argument["schema"]["default"] == 1e-9
    Draft202012Validator.check_schema(description["arguments_schema"])
    assert Draft202012Validator(description["arguments_schema"]).is_valid(
        {"quantity_tolerance": 0.01}
    )


def test_an_unknown_policy_is_not_found(http) -> None:
    assert http.get(f"{POLICIES_PATH}strict_feasible/").status_code == 404


def test_the_policy_routes_are_not_taken_for_an_account_uid(http) -> None:
    operations = http.get("/openapi.json").json()["paths"]

    assert operations[POLICIES_PATH]["get"]["operationId"] == "getVirtualFundAllocationPolicies"
    assert (
        operations[f"{POLICIES_PATH}{{policy_id}}/"]["get"]["operationId"]
        == "getVirtualFundAllocationPolicy"
    )


def test_the_client_reads_the_catalog_and_a_description(client) -> None:
    (summary,) = client.virtual_fund_allocation_policies()

    description = client.virtual_fund_allocation_policy(summary.id)

    assert isinstance(description, VirtualFundAllocationPolicyDescription)
    assert description.version == summary.version
    assert description.arguments["quantity_tolerance"].json_schema["type"] == "number"


# Plan ---------------------------------------------------------------------------------


def test_plan_passes_the_request_and_answers_the_plan(monkeypatch, client, account_uid) -> None:
    received: dict[str, object] = {}

    def fake_plan(*, account_uid, payload):
        received.update(account_uid=account_uid, payload=payload)
        return _plan_payload(account_uid)

    monkeypatch.setattr("apps.v1.routers.accounts.plan_account_virtual_funds", fake_plan)
    position_set_uid = uuid.uuid4()

    portfolio_uid, asset_uid = str(uuid.uuid4()), str(uuid.uuid4())

    plan = client.plan_account_virtual_funds(
        account_uid,
        position_set_uid=position_set_uid,
        valuation_time=VALUATION_TIME,
        sized_targets=[
            {
                "target_type": "portfolio",
                "target_uid": portfolio_uid,
                "positions": [{"asset_uid": asset_uid, "quantity": 500.0, "direction": -1}],
            }
        ],
    )

    assert isinstance(plan, AccountVirtualFundAllocationPlanResponse)
    assert received["account_uid"] == account_uid
    payload = received["payload"]
    assert payload.position_set_uid == str(position_set_uid)
    assert payload.valuation_time == VALUATION_TIME
    assert payload.policy is None
    # The caller's sizing of the exposure travels with the request, in units.
    assert [target.model_dump() for target in payload.sized_targets] == [
        {
            "target_type": "portfolio",
            "target_uid": portfolio_uid,
            "positions": [{"asset_uid": asset_uid, "quantity": 500.0, "direction": -1}],
        }
    ]
    fund_line, direct_line = plan.lines
    assert (fund_line.owner, fund_line.target, fund_line.assigned, fund_line.delta) == (
        "fund",
        500.0,
        375.0,
        125.0,
    )
    assert (direct_line.owner, direct_line.delta) == ("direct", -1100.0)
    assert plan.account_deltas[0].delta == 200.0
    assert not hasattr(plan, "status")


def test_plan_sends_the_policy_choice(monkeypatch, client, account_uid) -> None:
    received: dict[str, object] = {}

    def fake_plan(*, account_uid, payload):
        received["policy"] = payload.policy
        return _plan_payload(account_uid)

    monkeypatch.setattr("apps.v1.routers.accounts.plan_account_virtual_funds", fake_plan)

    client.plan_account_virtual_funds(
        account_uid,
        position_set_uid=uuid.uuid4(),
        valuation_time=VALUATION_TIME,
        policy={
            "id": "proportional_attribution",
            "version": "1.0.0",
            "arguments": {"quantity_tolerance": 0.01},
        },
    )

    assert received["policy"].model_dump() == {
        "id": "proportional_attribution",
        "version": "1.0.0",
        "arguments": {"quantity_tolerance": 0.01},
    }


@pytest.mark.parametrize(
    "body",
    [
        {"valuation_time": "2026-11-14T21:00:00Z"},
        {"position_set_uid": "p"},
        {"position_set_uid": "p", "valuation_time": "2026-11-14T21:00:00Z", "nav": 1000},
        {
            "position_set_uid": "p",
            "valuation_time": "2026-11-14T21:00:00Z",
            "valuation": {"nav": 1000},
        },
        {
            "position_set_uid": "p",
            "valuation_time": "2026-11-14T21:00:00Z",
            "valuation_asset_uid": "usd",
        },
    ],
)
def test_plan_takes_only_the_target_the_time_and_the_policy(http, account_uid, body) -> None:
    response = http.post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/plan/", json=body
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (AllocationError("not_found", "No such PositionSet.", status_code=404), 404, "not_found"),
        (AllocationError("target_after_snapshot", "Too late."), 400, "target_after_snapshot"),
        (
            AllocationError(
                "invalid_policy_arguments",
                "Bad arguments.",
                errors=[{"input": "quantity_tolerance", "message": "too large"}],
            ),
            400,
            "invalid_policy_arguments",
        ),
        (
            AllocationError("policy_version_mismatch", "Stale.", status_code=409),
            409,
            "policy_version_mismatch",
        ),
        (ValueError("direction must be 1 or -1."), 400, "bad_request"),
    ],
)
def test_plan_answers_structured_errors(
    monkeypatch, http, account_uid, error, status_code, code
) -> None:
    def refuse(**kwargs):
        raise error

    monkeypatch.setattr("apps.v1.routers.accounts.plan_account_virtual_funds", refuse)

    response = http.post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/plan/",
        json={"position_set_uid": "p", "valuation_time": "2026-11-14T21:00:00Z"},
    )

    assert response.status_code == status_code
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]
    if code == "invalid_policy_arguments":
        assert detail["errors"] == [{"input": "quantity_tolerance", "message": "too large"}]
    else:
        assert detail["errors"] == []


# Allocate -----------------------------------------------------------------------------


def test_allocate_passes_the_digest_and_answers_what_was_written(
    monkeypatch, client, account_uid
) -> None:
    received: dict[str, object] = {}
    fund_uid, holdings_set_uid = str(uuid.uuid4()), str(uuid.uuid4())

    def fake_allocate(*, account_uid, payload):
        received.update(account_uid=account_uid, payload=payload)
        plan = _plan_payload(account_uid, applied=True, already_applied=False)
        plan["funds"][0].update(virtual_fund_uid=fund_uid, holdings_set_uid=holdings_set_uid)
        return plan

    monkeypatch.setattr("apps.v1.routers.accounts.allocate_account_virtual_funds", fake_allocate)
    digest = "sha256:" + "a" * 64

    result = client.allocate_account_virtual_funds(
        account_uid,
        position_set_uid=uuid.uuid4(),
        valuation_time=VALUATION_TIME,
        plan_digest=digest,
    )

    assert isinstance(result, AccountVirtualFundAllocationResponse)
    assert received["account_uid"] == account_uid
    assert received["payload"].plan_digest == digest
    assert (result.applied, result.already_applied) == (True, False)
    assert (result.funds[0].virtual_fund_uid, result.funds[0].holdings_set_uid) == (
        fund_uid,
        holdings_set_uid,
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AllocationError("plan_changed", "Plan again.", status_code=409), "plan_changed"),
        (AllocationError("allocation_exists", "History.", status_code=409), "allocation_exists"),
        (PortfolioRetiredError({"p": VALUATION_TIME}, action="The allocation"), "portfolio_retired"),
    ],
)
def test_allocate_refusals_are_conflicts(monkeypatch, http, client, account_uid, error, code) -> None:
    def refuse(**kwargs):
        raise error

    monkeypatch.setattr("apps.v1.routers.accounts.allocate_account_virtual_funds", refuse)
    body = {"position_set_uid": "p", "valuation_time": "2026-11-14T21:00:00Z"}

    response = http.post(f"/api/v1/account/{account_uid}/virtual-fund-allocations/", json=body)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    with pytest.raises(MarketsConflictError):
        client.allocate_account_virtual_funds(
            account_uid, position_set_uid="p", valuation_time=VALUATION_TIME
        )


def test_sized_targets_that_do_not_match_the_target_are_a_bad_request(
    monkeypatch, http, account_uid
) -> None:
    def refuse(**kwargs):
        raise AllocationError(
            "invalid_sized_targets",
            "The sized targets do not match the account's target.",
            errors=[{"input": "sized_targets", "message": "The exposure is not sized."}],
        )

    monkeypatch.setattr("apps.v1.routers.accounts.allocate_account_virtual_funds", refuse)

    response = http.post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/",
        json={"position_set_uid": "p", "valuation_time": "2026-11-14T21:00:00Z"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_sized_targets"
    assert detail["errors"] == [{"input": "sized_targets", "message": "The exposure is not sized."}]


@pytest.mark.parametrize(
    "position",
    [
        {"asset_uid": "a", "quantity": 0},
        {"asset_uid": "a", "quantity": -1},
        {"asset_uid": "a", "quantity": 1, "direction": 0},
        {"asset_uid": "a", "quantity": 1, "price": 10.0},
    ],
)
def test_a_sized_position_is_a_positive_quantity_with_a_side_and_no_price(
    http, account_uid, position
) -> None:
    response = http.post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/plan/",
        json={
            "position_set_uid": "p",
            "valuation_time": "2026-11-14T21:00:00Z",
            "sized_targets": [{"target_uid": "t", "positions": [position]}],
        },
    )

    assert response.status_code == 422


def test_allocate_does_not_accept_a_plan_from_the_client(http, account_uid) -> None:
    response = http.post(
        f"/api/v1/account/{account_uid}/virtual-fund-allocations/",
        json={
            "position_set_uid": "p",
            "valuation_time": "2026-11-14T21:00:00Z",
            "lines": [{"owner": "fund", "assigned": 10}],
        },
    )

    assert response.status_code == 422


def test_the_stored_allocation_is_read_through_the_route_and_the_client(
    monkeypatch, http, client, account_uid
) -> None:
    received: dict[str, object] = {}
    record = {
        "account_uid": str(account_uid),
        "holdings_set_uid": str(uuid.uuid4()),
        "valuation_time": VALUATION_TIME.isoformat(),
        "position_set_uid": str(uuid.uuid4()),
        "policy": {"id": "proportional_attribution", "version": "1.0.0"},
        "plan_digest": "sha256:" + "1" * 64,
        "lines": [
            {
                "owner": "fund",
                "asset_identifier": "MSFT",
                "target": 400.0,
                "assigned": 309.68,
                "delta": 90.32,
                "virtual_fund_uid": str(uuid.uuid4()),
                "virtual_fund_unique_identifier": "account-virtual-fund-a",
                "target_portfolio_uid": str(uuid.uuid4()),
            },
            {"owner": "direct", "asset_identifier": "TSLA", "target": 200.0, "assigned": 1640.0, "delta": -1440.0},
        ],
    }

    def fake_get(*, account_uid, valuation_time):
        received.update(account_uid=account_uid, valuation_time=valuation_time)
        return record if account_uid != "missing" else None

    monkeypatch.setattr("apps.v1.routers.accounts.get_account_virtual_fund_allocation", fake_get)

    stored = client.account_virtual_fund_allocation(account_uid, valuation_time=VALUATION_TIME)

    assert received == {"account_uid": str(account_uid), "valuation_time": VALUATION_TIME}
    fund_line, direct_line = stored.lines
    assert (fund_line.owner, fund_line.target, fund_line.assigned, fund_line.delta) == (
        "fund",
        400.0,
        309.68,
        90.32,
    )
    assert (direct_line.owner, direct_line.virtual_fund_uid, direct_line.delta) == (
        "direct",
        None,
        -1440.0,
    )
    assert stored.policy.id == "proportional_attribution"

    client.account_virtual_fund_allocation(account_uid)
    assert received["valuation_time"] is None
    assert http.get("/api/v1/account/missing/virtual-fund-allocations/").status_code == 404
