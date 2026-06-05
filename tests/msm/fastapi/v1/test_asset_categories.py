from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_asset_categories_returns_core_rows(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.list_asset_categories",
        lambda **kwargs: [
            {
                "uid": str(category_uid),
                "unique_identifier": "crypto_core",
                "display_name": "Crypto Core",
                "description": "Core digital assets",
                "metadata_json": {"source": "test"},
            }
        ],
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset-category/",
        params={
            "response_format": "frontend_list",
            "search": "crypto",
            "limit": 50,
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
                "uid": str(category_uid),
                "unique_identifier": "crypto_core",
                "display_name": "Crypto Core",
                "description": "Core digital assets",
                "metadata_json": {"source": "test"},
            }
        ],
    }


def test_get_asset_categories_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/asset-category/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_asset_category_detail_returns_core_row(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.get_asset_category_detail",
        lambda uid: {
            "uid": str(category_uid),
            "unique_identifier": "crypto_core",
            "display_name": "Crypto Core",
            "description": "Core digital assets",
            "metadata_json": None,
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/asset-category/{category_uid}/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(category_uid),
        "unique_identifier": "crypto_core",
        "display_name": "Crypto Core",
        "description": "Core digital assets",
        "metadata_json": None,
    }


def test_get_asset_category_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.get_asset_category_detail",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset-category/missing-category/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 404
    assert "missing-category" in response.json()["detail"]


def test_post_asset_category_returns_record(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.create_asset_category",
        lambda payload: {
            "uid": str(category_uid),
            "unique_identifier": "crypto_core",
            "display_name": "Crypto Core",
            "description": "Core digital assets",
            "metadata_json": None,
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/asset-category/",
        json={
            "display_name": "Crypto Core",
            "description": "Core digital assets",
            "unique_identifier": "crypto_core",
            "assets": [str(uuid.uuid4()), str(uuid.uuid4())],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(category_uid),
        "unique_identifier": "crypto_core",
        "display_name": "Crypto Core",
        "description": "Core digital assets",
        "metadata_json": None,
    }


def test_patch_asset_category_returns_record(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_update_asset_category(*, uid: str, payload: dict[str, object]):
        captured["uid"] = uid
        captured["payload"] = payload
        return {
            "uid": str(category_uid),
            "unique_identifier": "crypto_core",
            "display_name": "Crypto Core Updated",
            "description": "",
            "metadata_json": None,
        }

    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.update_asset_category",
        fake_update_asset_category,
    )

    client = TestClient(app)
    response = client.patch(
        f"/api/v1/asset-category/{category_uid}/",
        json={"display_name": "Crypto Core Updated", "assets": []},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Crypto Core Updated"
    assert captured == {
        "uid": str(category_uid),
        "payload": {"display_name": "Crypto Core Updated", "assets": []},
    }


def test_delete_asset_category_returns_null(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.delete_asset_category",
        lambda uid: True,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/asset-category/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def test_delete_asset_category_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.delete_asset_category",
        lambda uid: False,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/asset-category/missing-category/")

    assert response.status_code == 404
    assert "missing-category" in response.json()["detail"]


def test_bulk_delete_asset_categories_returns_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.bulk_delete_asset_categories",
        lambda payload: {
            "detail": "Deleted 2 asset categories.",
            "deleted_count": 2,
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/asset-category/bulk-delete/",
        json={
            "uids": [str(uuid.uuid4()), str(uuid.uuid4())],
            "select_all": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted 2 asset categories.",
        "deleted_count": 2,
    }
