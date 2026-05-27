from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_asset_categories_returns_frontend_rows_payload(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.list_asset_categories",
        lambda **kwargs: {
            "search": kwargs["search"],
            "rows": [
                {
                    "uid": str(category_uid),
                    "unique_identifier": "crypto_core",
                    "display_name": "Crypto Core",
                    "description": "Core digital assets",
                    "number_of_assets": 2,
                }
            ],
            "pagination": {
                "page": 1,
                "page_size": 50,
                "total_pages": 1,
                "total_items": 1,
                "has_next": False,
                "has_previous": False,
                "start_index": 1,
                "end_index": 1,
            },
        },
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
        "search": "crypto",
        "rows": [
            {
                "uid": str(category_uid),
                "unique_identifier": "crypto_core",
                "display_name": "Crypto Core",
                "description": "Core digital assets",
                "number_of_assets": 2,
            }
        ],
        "pagination": {
            "page": 1,
            "page_size": 50,
            "total_pages": 1,
            "total_items": 1,
            "has_next": False,
            "has_previous": False,
            "start_index": 1,
            "end_index": 1,
        },
    }


def test_get_asset_categories_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/asset-category/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_asset_category_detail_returns_frontend_detail_payload(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.get_asset_category_detail",
        lambda uid: {
            "uid": str(category_uid),
            "title": "Crypto Core",
            "selected_category": {
                "text": "Crypto Core",
                "sub_text": "crypto_core",
            },
            "details": [
                {
                    "name": "description",
                    "label": "Description",
                    "value_type": "text",
                    "value": "Core digital assets",
                }
            ],
            "actions": {
                "can_edit": True,
                "can_delete": True,
                "update_endpoint": f"/api/v1/asset-category/{category_uid}/",
                "delete_endpoint": f"/api/v1/asset-category/{category_uid}/",
            },
            "assets_list": {
                "list_endpoint": "/api/v1/asset/",
                "query_endpoint": "/api/v1/asset/query/",
                "response_format": "frontend_list",
                "default_filters": {"categories__uid": str(category_uid)},
            },
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/asset-category/{category_uid}/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 200
    assert response.json()["selected_category"]["sub_text"] == "crypto_core"
    assert response.json()["assets_list"]["default_filters"] == {
        "categories__uid": str(category_uid)
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
            "assets": ["asset-1", "asset-2"],
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
        "assets": ["asset-1", "asset-2"],
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
            "assets": [],
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
