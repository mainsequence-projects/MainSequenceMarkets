from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_indexes_returns_core_index_rows(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.list_indices",
        lambda **kwargs: [
            {
                "uid": str(index_uid),
                "unique_identifier": "SPX",
                "index_type": "equity",
                "display_name": "S&P 500 Index",
                "description": "Large-cap US equity index",
                "provider": "example",
                "metadata_json": {"currency": "USD"},
            }
        ],
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/index/",
        params={
            "response_format": "frontend_list",
            "search": "spx",
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "uid": str(index_uid),
                "unique_identifier": "SPX",
                "index_type": "equity",
                "display_name": "S&P 500 Index",
                "description": "Large-cap US equity index",
                "provider": "example",
                "metadata_json": {"currency": "USD"},
            }
        ],
    }


def test_get_indexes_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/index/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_index_returns_record(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index",
        lambda uid: {
            "uid": str(index_uid),
            "unique_identifier": "SPX",
            "index_type": "equity",
            "display_name": "S&P 500 Index",
            "description": "Large-cap US equity index",
            "provider": "example",
            "metadata_json": {"currency": "USD"},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/index/{index_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(index_uid),
        "unique_identifier": "SPX",
        "index_type": "equity",
        "display_name": "S&P 500 Index",
        "description": "Large-cap US equity index",
        "provider": "example",
        "metadata_json": {"currency": "USD"},
    }


def test_get_index_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/index/missing-index/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]


def test_delete_index_returns_null(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: True,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/index/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def test_delete_index_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: False,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/index/missing-index/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]
