"""`GET /api/v1/account/{uid}/target-positions/history/`, and the client's call of it."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.client import MarketsClient

ACCOUNT_UID = str(uuid.uuid4())
ROUTE = f"/api/v1/account/{ACCOUNT_UID}/target-positions/history/"
WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)


@pytest.fixture
def history(monkeypatch):
    seen: list[dict] = []

    def answer(**kwargs):
        seen.append(kwargs)
        if kwargs["account_uid"] != ACCOUNT_UID:
            return None
        snapshot = {
            "related_account_uid": ACCOUNT_UID,
            "target_positions_date": WHEN,
            "position_set_uid": str(uuid.uuid4()),
            "positions": [],
        }
        return {"count": 3, "results": [snapshot, snapshot]}

    monkeypatch.setattr("apps.v1.routers.accounts.get_account_target_positions_history", answer)
    return seen


def test_the_history_route_answers_one_page_of_snapshots(history) -> None:
    response = TestClient(app).get(ROUTE, params={"limit": 2, "include_asset_detail": "false"})

    assert response.status_code == 200
    assert history == [
        {
            "account_uid": ACCOUNT_UID,
            "order": "desc",
            "limit": 2,
            "offset": 0,
            "include_asset_detail": False,
        }
    ]
    payload = response.json()
    assert [item["related_account_uid"] for item in payload["items"]] == [ACCOUNT_UID] * 2
    assert payload["pageInfo"]["totalItems"] == 3
    assert payload["pageInfo"]["hasNextPage"] is True


def test_the_history_route_refuses_a_large_page_and_an_unknown_account(history) -> None:
    client = TestClient(app)

    assert client.get(ROUTE, params={"limit": 51}).status_code == 422
    missing = client.get(f"/api/v1/account/{uuid.uuid4()}/target-positions/history/")
    assert missing.status_code == 404


def test_the_history_declares_its_discovery() -> None:
    response = TestClient(app).get(f"{ROUTE}discovery/")

    assert response.status_code == 200
    assert response.json()["resource"]["identity"]["fields"] == ["position_set_uid"]


def test_the_client_reads_the_history(history) -> None:
    http = TestClient(app)
    client = MarketsClient(base_url="http://testserver", session=http)

    page = client.account_target_positions_history(ACCOUNT_UID, limit=2, order="asc")

    assert history[0]["order"] == "asc"
    assert page.page_info.total_items == 3
    assert [item.target_positions_date for item in page.items] == [WHEN, WHEN]
