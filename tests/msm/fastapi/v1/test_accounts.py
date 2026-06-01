from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_accounts_returns_count_and_results(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.accounts.list_accounts",
        lambda **kwargs: {
            "count": 1,
            "results": [
                {
                    "uid": str(account_uid),
                    "display_name": "Some account",
                    "is_paper": False,
                    "account_is_active": True,
                }
            ],
        },
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/", params={"limit": 25, "offset": 0})

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "results": [
            {
                "uid": str(account_uid),
                "display_name": "Some account",
                "is_paper": False,
                "account_is_active": True,
            }
        ],
    }


def test_get_accounts_passes_query_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_accounts(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "results": []}

    monkeypatch.setattr("apps.v1.routers.accounts.list_accounts", fake_list_accounts)

    client = TestClient(app)
    response = client.get(
        "/api/v1/account/",
        params={"search": "some", "limit": 10, "offset": 5},
    )

    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": []}
    assert captured == {"search": "some", "limit": 10, "offset": 5}


def test_account_service_maps_account_rows(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.accounts._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.accounts._list_account_rows_response",
        lambda context, **kwargs: {
            "count": 1,
            "results": [
                {
                    "uid": str(account_uid),
                    "display_name": "Some account",
                    "is_paper": False,
                    "account_is_active": True,
                    "unique_identifier": "ignored-extra-field",
                }
            ],
        },
    )

    from apps.v1.services.accounts import list_accounts

    response = list_accounts(limit=25, offset=0)

    assert response.model_dump(mode="json") == {
        "count": 1,
        "results": [
            {
                "uid": str(account_uid),
                "display_name": "Some account",
                "is_paper": False,
                "account_is_active": True,
            }
        ],
    }


def test_get_account_summary_returns_frontend_detail_summary(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_summary",
        lambda uid: {
            "entity": {
                "id": str(account_uid),
                "type": "account",
                "title": "Some account",
            },
            "badges": [
                {
                    "key": "account_is_active",
                    "label": "Active",
                    "tone": "success",
                },
                {
                    "key": "is_paper",
                    "label": "Live",
                    "tone": "success",
                },
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(account_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [
                {
                    "key": "display_name",
                    "label": "Display name",
                    "value": "Some account",
                    "kind": "text",
                    "icon": "database",
                }
            ],
            "stats": [],
            "label_management": {
                "labels": [],
                "add_label_url": None,
                "remove_label_url": None,
            },
            "summary_warning": None,
            "extensions": {
                "holdings_data_node_uid": None,
                "metadata_json": None,
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/account/{account_uid}/summary/")

    assert response.status_code == 200
    assert response.json() == {
        "entity": {
            "id": str(account_uid),
            "type": "account",
            "title": "Some account",
        },
        "badges": [
            {
                "key": "account_is_active",
                "label": "Active",
                "tone": "success",
            },
            {
                "key": "is_paper",
                "label": "Live",
                "tone": "success",
            },
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": str(account_uid),
                "kind": "code",
                "icon": None,
            }
        ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display name",
                "value": "Some account",
                "kind": "text",
                "icon": "database",
            }
        ],
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "holdings_data_node_uid": None,
            "metadata_json": None,
        },
    }


def test_get_account_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_summary",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/missing-account/summary/")

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]
