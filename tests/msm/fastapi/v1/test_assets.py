from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services import assets as asset_service


def test_get_assets_returns_frontend_list_rows(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.assets._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.assets._list_asset_catalog_rows",
        lambda context, **kwargs: [
            {
                "uid": str(asset_uid),
                "unique_identifier": "BTC",
                "figi": "BBG000XYZ",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "BNCE",
                "security_market_sector": "Crypto",
                "security_type": "Spot",
                "is_custom_by_organization": True,
            }
        ],
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={
            "response_format": "frontend_list",
            "search": "btc",
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "uid": str(asset_uid),
            "unique_identifier": "BTC",
            "figi": "BBG000XYZ",
            "name": "Bitcoin",
            "ticker": "BTC",
            "exchange_code": "BNCE",
            "security_market_sector": "Crypto",
            "security_type": "Spot",
            "is_custom_by_organization": True,
        }
    ]


def test_get_assets_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_assets_passes_category_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_assets(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("apps.v1.routers.assets.list_assets", fake_list_assets)

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={
            "response_format": "frontend_list",
            "categories__uid": "category-uid-1",
            "limit": 25,
            "offset": 5,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    assert captured == {
        "search": "",
        "limit": 25,
        "offset": 5,
        "category_uid": "category-uid-1",
    }


def test_get_asset_summary_returns_frontend_detail_summary(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_summary",
        lambda uid: {
            "entity": {
                "id": str(asset_uid),
                "type": "asset",
                "title": "NASDAQ 100",
            },
            "badges": [
                {
                    "key": "status",
                    "label": "Active",
                    "tone": "success",
                }
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(asset_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [
                {
                    "key": "name",
                    "label": "Name",
                    "value": "NASDAQ 100",
                    "kind": "text",
                    "icon": "database",
                }
            ],
            "stats": [
                {
                    "key": "rows",
                    "label": "Rows",
                    "display": "25",
                    "value": 25,
                    "kind": "number",
                }
            ],
            "label_management": {
                "labels": ["important", "live"],
                "add_label_url": "/add-label/",
                "remove_label_url": "/remove-label/",
            },
            "summary_warning": None,
            "extensions": {"anything_page_specific": True},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/asset/{asset_uid}/summary/")

    assert response.status_code == 200
    assert response.json() == {
        "entity": {
            "id": str(asset_uid),
            "type": "asset",
            "title": "NASDAQ 100",
        },
        "badges": [
            {
                "key": "status",
                "label": "Active",
                "tone": "success",
            }
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": str(asset_uid),
                "kind": "code",
                "icon": None,
            }
        ],
        "highlight_fields": [
            {
                "key": "name",
                "label": "Name",
                "value": "NASDAQ 100",
                "kind": "text",
                "icon": "database",
            }
        ],
        "stats": [
            {
                "key": "rows",
                "label": "Rows",
                "display": "25",
                "value": 25,
                "kind": "number",
            }
        ],
        "label_management": {
            "labels": ["important", "live"],
            "add_label_url": "/add-label/",
            "remove_label_url": "/remove-label/",
        },
        "summary_warning": None,
        "extensions": {"anything_page_specific": True},
    }


def test_get_asset_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_summary",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/asset/missing-asset/summary/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_get_asset_pricing_details_returns_pricing_contract(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_pricing_details",
        lambda uid: {
            "asset_uid": str(asset_uid),
            "instrument_type": "bond",
            "instrument_dump": {"currency": "USD"},
            "pricing_details_date": "2026-05-28T00:00:00+00:00",
            "serialization_format": "msm_pricing.instrument.v1",
            "pricing_package_version": "1.0.0",
            "source": "test",
            "metadata_json": {"provider": "example"},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/asset/{asset_uid}/get_pricing_details/")

    assert response.status_code == 200
    assert response.json() == {
        "asset_uid": str(asset_uid),
        "instrument_type": "bond",
        "instrument_dump": {"currency": "USD"},
        "pricing_details_date": "2026-05-28T00:00:00Z",
        "serialization_format": "msm_pricing.instrument.v1",
        "pricing_package_version": "1.0.0",
        "source": "test",
        "metadata_json": {"provider": "example"},
    }


def test_get_asset_pricing_details_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_pricing_details",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/asset/missing-asset/get_pricing_details/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_asset_pricing_details_service_uses_pricing_api_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(asset_service, "_ensure_pricing_runtime", lambda: None)

    def fake_get_asset_current_pricing_details(uid):
        captured["uid"] = uid
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "bond",
            "instrument_dump": {"currency": "USD"},
            "pricing_details_date": "2026-05-28T00:00:00+00:00",
            "serialization_format": "msm_pricing.instrument.v1",
            "pricing_package_version": None,
            "source": None,
            "metadata_json": None,
        }

    monkeypatch.setattr(
        asset_service,
        "_get_asset_current_pricing_details",
        fake_get_asset_current_pricing_details,
    )

    response = asset_service.get_asset_pricing_details(uid=str(asset_uid))

    assert captured == {"uid": str(asset_uid)}
    assert response is not None
    assert str(response.asset_uid) == str(asset_uid)
