"""The Markets API acts for one identity: the requester when bound, else the caller (ADR 0047)."""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mainsequence.client.models_user import RequestIdentityError
from mainsequence.server.caller_assertions import ASSERTION_HEADER

from apps.v1 import identity
from apps.v1.main import app
from apps.v1.services import portfolio_signals as signal_service

USER_UID = "9b4d2f8e-1a3c-4e5b-8d7f-6c0a2e4b6d35"
REQUESTER_UID = "6e2a8c4f-0b7d-4f1a-9e3c-5d8b2a7f4c61"
CREATE_ROUTE = "/api/v1/portfolio-signal/"


def _install_signal_write(monkeypatch) -> list[identity.ActingIdentity | None]:
    """Let the real decorated service run against a fake runtime and capture the actor it saw."""

    seen: list[identity.ActingIdentity | None] = []
    monkeypatch.setattr(signal_service, "_get_runtime", lambda: SimpleNamespace(context=object()))

    def fake_create(_context, **kwargs):
        seen.append(identity.acting_identity())
        return {
            "uid": str(uuid.uuid4()),
            "signal_uid": kwargs["signal_uid"],
            "signal_description": kwargs.get("signal_description"),
        }

    monkeypatch.setattr(signal_service, "_create_signal_metadata_response", fake_create)
    return seen


def _registry_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "apps.v1.identity"]


def test_caller_bound_write_acts_for_the_verified_caller(monkeypatch, caplog, caller_assertions):
    seen = _install_signal_write(monkeypatch)
    caplog.set_level(logging.INFO, logger="apps.v1.identity")

    response = TestClient(app).post(
        CREATE_ROUTE,
        json={"signal_uid": "example-signal", "signal_description": "Example"},
        headers={ASSERTION_HEADER: caller_assertions.sign(USER_UID)},
    )

    assert response.status_code == 200
    assert seen == [identity.ActingIdentity(uid=USER_UID, kind="caller")]
    (record,) = _registry_records(caplog)
    assert record.resource == "portfolio-signal"
    assert record.action == "create"
    assert record.actor_uid == USER_UID
    assert record.actor_kind == "caller"
    assert record.uid == response.json()["uid"]


def test_requester_bound_write_acts_for_the_requester_not_the_caller(
    monkeypatch, caplog, caller_assertions
):
    seen = _install_signal_write(monkeypatch)
    caplog.set_level(logging.INFO, logger="apps.v1.identity")
    assertion = caller_assertions.sign(
        USER_UID, requester={"sub": REQUESTER_UID, "is_organization_admin": True}
    )

    response = TestClient(app).post(
        CREATE_ROUTE,
        json={"signal_uid": "example-signal"},
        headers={ASSERTION_HEADER: assertion},
    )

    assert response.status_code == 200
    assert seen == [
        identity.ActingIdentity(uid=REQUESTER_UID, kind="requester", is_organization_admin=True)
    ]
    (record,) = _registry_records(caplog)
    assert record.actor_uid == REQUESTER_UID
    assert record.actor_kind == "requester"


def test_failed_write_records_nothing(monkeypatch, caplog, caller_assertions):
    monkeypatch.setattr(signal_service, "_get_runtime", lambda: SimpleNamespace(context=object()))

    def failing_create(_context, **_kwargs):
        raise ValueError("signal_uid already exists")

    monkeypatch.setattr(signal_service, "_create_signal_metadata_response", failing_create)
    caplog.set_level(logging.INFO, logger="apps.v1.identity")

    response = TestClient(app).post(
        CREATE_ROUTE,
        json={"signal_uid": "example-signal"},
        headers={ASSERTION_HEADER: caller_assertions.sign(USER_UID)},
    )

    assert response.status_code == 400
    assert _registry_records(caplog) == []


def test_acting_identity_is_absent_outside_a_request() -> None:
    assert identity.acting_identity() is None
    with pytest.raises(RequestIdentityError, match="authenticated request"):
        identity.require_acting_identity()


def test_every_mutating_service_is_a_registry_write() -> None:
    import importlib
    import inspect

    expected = {
        "accounts": {
            "add_account_holdings", "add_account_target_positions", "create_account", "update_account",
        },
        "asset_categories": {
            "create_asset_category", "update_asset_category", "delete_asset_category",
            "bulk_delete_asset_categories",
        },
        "assets": {"delete_asset"},
        "calendars": {
            "create_calendar", "update_calendar", "delete_calendar",
            "create_calendar_date", "update_calendar_date", "delete_calendar_date",
            "bulk_upsert_calendar_dates",
            "create_calendar_session", "update_calendar_session", "delete_calendar_session",
            "bulk_upsert_calendar_sessions",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "bulk_upsert_calendar_events",
        },
        "indices": {
            "create_index", "update_index", "delete_index",
            "save_index_formula", "activate_index_formula", "retire_index_formula",
        },
        "portfolio_groups": {
            "create_portfolio_group", "update_portfolio_group", "delete_portfolio_group",
            "bulk_delete_portfolio_groups", "add_portfolio_to_group", "remove_portfolio_from_group",
            "bulk_delete_portfolio_group_memberships",
        },
        "portfolio_signals": {
            "create_portfolio_signal", "update_portfolio_signal", "delete_portfolio_signal",
            "delete_portfolio_signal_weights",
        },
        "portfolios": {
            "delete_portfolio", "cascade_delete_portfolio", "delete_portfolio_weights",
            "bulk_delete_portfolios", "bulk_cascade_delete_portfolios",
            "register_portfolio_dataset_catalog", "reconcile_portfolio_dataset_catalog",
        },
        "pricing_curves": {"delete_pricing_curve"},
        "pricing_market_data": {
            "create_pricing_market_data_set", "upsert_pricing_market_data_set",
            "update_pricing_market_data_set", "delete_pricing_market_data_set",
            "create_pricing_market_data_binding", "upsert_pricing_market_data_binding",
            "update_pricing_market_data_binding", "delete_pricing_market_data_binding",
        },
    }
    for module_name, names in expected.items():
        module = importlib.import_module(f"apps.v1.services.{module_name}")
        wrapped = {
            name
            for name, member in inspect.getmembers(module, inspect.isfunction)
            if getattr(member, "__registry_write__", None) and member.__module__ == module.__name__
        }
        assert wrapped == names, module_name
