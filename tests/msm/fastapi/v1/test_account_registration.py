"""`POST /api/v1/account/registration/` (`registerAccount`, ADR 0051).

The route runs the real `apps.v1` service with the registration service of `msm.services`
replaced, so these tests cover the HTTP contract, the error mapping, the audit records and
`MarketsClient.register_account`. The writes themselves are covered end to end by
`tests/msm/repositories/test_sqlite_account_registration.py`.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mainsequence.server.caller_assertions import ASSERTION_HEADER

from apps.v1.main import app
from msm.api.accounts import AccountRegistrationRequest, AccountRegistrationResponse
from msm.api.remote import MarketsConflictError
from msm.client import MarketsClient
from msm.services import (
    AccountHoldingsSnapshotExistsError,
    AccountRegistrationResult,
    AccountRegistrationWrite,
    AssetTypeConflictError,
)

ROUTE = "/api/v1/account/registration/"
USER_UID = "9b4d2f8e-1a3c-4e5b-8d7f-6c0a2e4b6d35"
ACCOUNT_UID = str(uuid.uuid4())
HOLDINGS_SET_UID = str(uuid.uuid4())
ASSET_UID = str(uuid.uuid4())
WHEN = dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC)


def _payload(**overrides):
    return {
        "account": {"unique_identifier": "venue::account-1", "account_name": "Venue account", "is_paper": True},
        "assets": [
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "US Equity", "display_name": "US equity"},
                "snapshot": {"name": "Apple Inc.", "ticker": "AAPL", "exchange_code": "XNAS"},
            }
        ],
        "cash_currency": "USD",
        "holdings_date": WHEN.isoformat(),
        "overwrite": False,
        "positions": [
            {"asset_identifier": "venue::AAPL", "quantity": "3", "direction": 1, "extra_details": {"lot": 1}}
        ],
        **overrides,
    }


def _result(**written):
    return AccountRegistrationResult(
        response={
            "account": {
                "uid": ACCOUNT_UID,
                "unique_identifier": "venue::account-1",
                "account_name": "Venue account",
                "is_paper": True,
                "account_is_active": False,
                "account_group_uid": None,
                "holdings_storage_table_uid": None,
                "holdings_data_node_uid": None,
                "metadata_json": None,
            },
            "asset_uids": {"venue::AAPL": ASSET_UID},
            "holdings_set_uid": HOLDINGS_SET_UID,
            "holdings_date": WHEN,
            "written": {
                table: {"created": 0, "changed": 0, **written.get(table, {})}
                for table in ("asset_types", "assets", "asset_snapshots", "accounts", "holdings_sets", "holdings")
            },
        },
        writes=(
            AccountRegistrationWrite(
                "asset",
                "create",
                ASSET_UID,
                {"unique_identifier": "venue::AAPL", "account_identifier": "venue::account-1"},
            ),
            AccountRegistrationWrite("account", "create", ACCOUNT_UID, {"account_identifier": "venue::account-1"}),
            AccountRegistrationWrite(
                "account-holdings",
                "add",
                HOLDINGS_SET_UID,
                {"row_count": 1, "account_identifier": "venue::account-1"},
            ),
        ),
    )


@pytest.fixture
def registration(monkeypatch):
    """Run the real route and `apps.v1` service; record what reaches `msm.services`."""

    seen: list[AccountRegistrationRequest] = []
    state = SimpleNamespace(seen=seen, result=_result(assets={"created": 1}), error=None)
    monkeypatch.setattr(
        "apps.v1.services.accounts._get_registration_runtime",
        lambda: SimpleNamespace(context=object()),
    )

    def register(context, request):
        seen.append(request)
        if state.error is not None:
            raise state.error
        return state.result

    monkeypatch.setattr("msm.services.register_account", register, raising=False)
    return state


def test_registration_answers_the_account_assets_and_holdings_set(registration) -> None:
    response = TestClient(app).post(ROUTE, json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["account"]["uid"] == ACCOUNT_UID
    assert body["asset_uids"] == {"venue::AAPL": ASSET_UID}
    assert body["holdings_set_uid"] == HOLDINGS_SET_UID
    assert body["written"]["assets"] == {"created": 1, "changed": 0}
    (request,) = registration.seen
    assert isinstance(request, AccountRegistrationRequest)
    assert request.assets[0].asset_type.asset_type == "us_equity"
    assert str(request.positions[0].quantity) == "3"
    assert request.account.account_is_active is None


def test_registration_records_each_sub_write_and_the_registration(
    registration, caplog, caller_assertions
) -> None:
    caplog.set_level(logging.INFO, logger="apps.v1.identity")

    response = TestClient(app).post(
        ROUTE,
        json=_payload(),
        headers={ASSERTION_HEADER: caller_assertions.sign(USER_UID)},
    )

    assert response.status_code == 200
    records = [record for record in caplog.records if record.name == "apps.v1.identity"]
    assert [(record.resource, record.action, record.uid) for record in records] == [
        ("asset", "create", ASSET_UID),
        ("account", "create", ACCOUNT_UID),
        ("account-holdings", "add", HOLDINGS_SET_UID),
        ("account", "register", ACCOUNT_UID),
    ]
    assert {record.actor_uid for record in records} == {USER_UID}
    assert records[0].unique_identifier == "venue::AAPL"
    assert records[2].row_count == 1
    assert {record.account_identifier for record in records[:3]} == {"venue::account-1"}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AssetTypeConflictError("Existing assets keep their asset_type"), 409),
        (AccountHoldingsSnapshotExistsError("A different account holdings snapshot already exists"), 409),
        (ValueError("Asset 'GHOST' was not found and is not in assets."), 400),
    ],
)
def test_refusals_map_to_conflict_or_bad_request_and_record_nothing(
    registration, caplog, error, status
) -> None:
    registration.error = error
    caplog.set_level(logging.INFO, logger="apps.v1.identity")

    response = TestClient(app).post(ROUTE, json=_payload())

    assert response.status_code == status
    assert response.json()["detail"] == str(error)
    assert [record for record in caplog.records if record.name == "apps.v1.identity"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"positions": []},
        {"positions": [{"asset_identifier": "venue::AAPL", "quantity": "0"}]},
        {"positions": [{"asset_identifier": "venue::AAPL", "quantity": "1", "direction": 2}]},
        {"positions": [{"asset_identifier": "venue::AAPL", "quantity": "1", "target_trade_time": WHEN.isoformat()}]},
        {"account": {"unique_identifier": "a", "account_name": "A", "holdings_storage_table_uid": None}},
        {"assets": [{"unique_identifier": "venue::AAPL", "asset_type": {"asset_type": "x"}, "snapshot": {"exchange": "X"}}]},
    ],
)
def test_invalid_payloads_are_refused_before_the_service(registration, overrides) -> None:
    response = TestClient(app).post(ROUTE, json=_payload(**overrides))

    assert response.status_code == 422
    assert registration.seen == []


def test_registration_is_a_command_center_mutation() -> None:
    from apps.v1.services.command_center_adapter import MUTATION_OPERATION_IDS

    assert "registerAccount" in MUTATION_OPERATION_IDS


def test_the_client_registers_through_the_route(registration) -> None:
    client = MarketsClient("http://testserver", session=TestClient(app))

    answer = client.register_account(
        account={"unique_identifier": "venue::account-1", "account_name": "Venue account"},
        holdings_date=WHEN,
        positions=[{"asset_identifier": "venue::AAPL", "quantity": 3}],
        cash_currency="USD",
    )

    assert isinstance(answer, AccountRegistrationResponse)
    assert answer.uid == uuid.UUID(ACCOUNT_UID)
    assert answer.holdings_set_uid == uuid.UUID(HOLDINGS_SET_UID)
    (request,) = registration.seen
    # Flags left out stay unset, so an existing account keeps its values.
    assert request.account.is_paper is None
    assert request.cash_currency == "USD"
    assert request.positions[0].quantity == 3

    registration.error = AccountHoldingsSnapshotExistsError("A different account holdings snapshot already exists")
    with pytest.raises(MarketsConflictError, match="already exists"):
        client.register_account(AccountRegistrationRequest.model_validate(_payload()))
