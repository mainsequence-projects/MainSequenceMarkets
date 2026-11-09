"""Typed ``MarketsClient`` methods for an account's target positions."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.accounts import (
    AccountAddAssetTargetPositionRequest,
    AccountTargetPositionsSnapshotResponse,
)
from msm.client import MarketsClient

TARGET_DATE = dt.datetime(2026, 11, 2, 14, 30, tzinfo=dt.UTC)


@pytest.fixture
def client() -> MarketsClient:
    return MarketsClient("http://testserver", session=TestClient(app))


@pytest.fixture
def account_uid() -> str:
    return str(uuid.uuid4())


def _snapshot(account_uid: str, positions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "related_account_uid": account_uid,
        "target_positions_date": TARGET_DATE,
        "position_set_uid": str(uuid.uuid4()),
        "positions": positions,
    }


def test_writes_the_target_without_building_paths(monkeypatch, client, account_uid) -> None:
    asset_uid = str(uuid.uuid4())
    received: dict[str, object] = {}

    def fake_add(*, account_uid, payload):
        received["account_uid"] = account_uid
        received["payload"] = payload
        return _snapshot(
            account_uid,
            [
                {
                    "target_type": "asset",
                    "target_uid": asset_uid,
                    "asset_uid": asset_uid,
                    "unique_identifier": "ACME",
                    "weight_notional_exposure": "0.25",
                }
            ],
        )

    monkeypatch.setattr("apps.v1.routers.accounts.add_account_target_positions", fake_add)

    snapshot = client.add_account_target_positions(
        account_uid,
        target_positions_date=TARGET_DATE,
        positions=[
            AccountAddAssetTargetPositionRequest(
                target_type="asset",
                target_uid=asset_uid,
                asset_uid=asset_uid,
                weight_notional_exposure=0.25,
            )
        ],
        overwrite=True,
    )

    assert isinstance(snapshot, AccountTargetPositionsSnapshotResponse)
    assert snapshot.positions[0].unique_identifier == "ACME"
    assert received["account_uid"] == account_uid
    payload = received["payload"]
    assert payload.overwrite is True
    assert payload.target_positions_date == TARGET_DATE
    assert payload.positions[0].asset_uid == asset_uid


def test_validates_positions_before_sending(client, account_uid) -> None:
    with pytest.raises(ValueError, match="exactly one exposure field"):
        client.add_account_target_positions(
            account_uid,
            target_positions_date=TARGET_DATE,
            positions=[
                {"target_type": "asset", "target_uid": "a", "asset_uid": "a"},
            ],
        )


def test_reads_the_target_with_its_query(monkeypatch, client, account_uid) -> None:
    received: dict[str, object] = {}

    def fake_get(**kwargs):
        received.update(kwargs)
        return _snapshot(kwargs["account_uid"], [])

    monkeypatch.setattr("apps.v1.routers.accounts.get_account_target_positions", fake_get)

    snapshot = client.account_target_positions(
        account_uid,
        target_positions_date=TARGET_DATE,
        include_asset_detail=False,
    )

    assert snapshot.related_account_uid == account_uid
    assert snapshot.positions == []
    assert received == {
        "account_uid": account_uid,
        "order": "desc",
        "limit": 1,
        "include_asset_detail": False,
        "target_positions_date": TARGET_DATE,
    }


def test_clear_sends_an_empty_target(monkeypatch, client, account_uid) -> None:
    received: dict[str, object] = {}

    def fake_add(*, account_uid, payload):
        received["payload"] = payload
        return _snapshot(account_uid, [])

    monkeypatch.setattr("apps.v1.routers.accounts.add_account_target_positions", fake_add)

    snapshot = client.clear_account_target_positions(account_uid, target_positions_date=TARGET_DATE)

    assert received["payload"].positions == []
    assert received["payload"].overwrite is False
    assert snapshot.positions == []
    assert snapshot.position_set_uid is not None


def test_an_unknown_account_raises_lookup_error(monkeypatch, client, account_uid) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_target_positions",
        lambda **kwargs: None,
    )

    with pytest.raises(LookupError):
        client.account_target_positions(account_uid)
