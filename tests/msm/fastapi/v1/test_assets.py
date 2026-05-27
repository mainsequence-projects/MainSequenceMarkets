from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app


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
