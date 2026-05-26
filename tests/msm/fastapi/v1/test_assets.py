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
        "apps.v1.services.assets._search_assets",
        lambda context, **kwargs: {
            "rows": [
                {
                    "uid": str(asset_uid),
                    "unique_identifier": "BTC",
                    "asset_type": "crypto",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "apps.v1.services.assets._search_openfigi_details",
        lambda context, **kwargs: {
            "rows": [
                {
                    "asset_uid": str(asset_uid),
                    "figi": "BBG000XYZ",
                    "name": "Bitcoin",
                    "ticker": "BTC",
                    "exchange_code": "BNCE",
                    "security_market_sector": "Crypto",
                    "security_type": "Spot",
                }
            ]
        },
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
            "id": str(asset_uid),
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
