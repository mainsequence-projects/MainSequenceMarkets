from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app


def _asset_category_detail_payload(category_uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(category_uid),
        "title": "Crypto Core",
        "selected_category": {
            "text": "Crypto Core",
            "sub_text": "crypto_core",
        },
        "details": [
            {
                "name": "display_name",
                "label": "Display name",
                "value_type": "text",
                "value": "Crypto Core",
            },
            {
                "name": "unique_identifier",
                "label": "Identifier",
                "value_type": "text",
                "value": "crypto_core",
            },
            {
                "name": "description",
                "label": "Description",
                "value_type": "text",
                "value": "Core digital assets",
            },
            {
                "name": "number_of_assets",
                "label": "Assets",
                "value_type": "number",
                "value": 2,
            },
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
    }


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


def test_get_asset_category_detail_returns_membership_detail(monkeypatch) -> None:
    category_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.get_asset_category_detail",
        lambda uid: _asset_category_detail_payload(category_uid),
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/asset-category/{category_uid}/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uid"] == str(category_uid)
    assert payload["selected_category"] == {
        "text": "Crypto Core",
        "sub_text": "crypto_core",
    }
    assert payload["details"][-1] == {
        "name": "number_of_assets",
        "label": "Assets",
        "value_type": "number",
        "value": 2,
    }
    assert payload["assets_list"]["default_filters"] == {
        "categories__uid": str(category_uid),
    }


def test_asset_category_detail_service_uses_membership_frontend_detail(monkeypatch) -> None:
    from apps.v1.services import asset_categories

    category_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_detail(context, *, uid: str):
        captured["context"] = context
        captured["uid"] = uid
        return _asset_category_detail_payload(category_uid)

    monkeypatch.setattr(
        asset_categories,
        "_get_runtime",
        lambda: SimpleNamespace(context="runtime-context"),
    )
    monkeypatch.setattr(
        asset_categories,
        "_get_asset_category_frontend_detail",
        fake_detail,
    )

    detail = asset_categories.get_asset_category_detail(uid=str(category_uid))

    assert captured == {"context": "runtime-context", "uid": str(category_uid)}
    assert detail is not None
    assert detail.uid == category_uid
    assert detail.assets_list.default_filters == {"categories__uid": str(category_uid)}


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
