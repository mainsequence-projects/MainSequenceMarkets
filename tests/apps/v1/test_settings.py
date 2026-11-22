from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_api_settings() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/settings/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"]["name"] == "MainSequence Markets Public API"
    assert payload["app"]["scope"] == "apps/v1"
    assert payload["app"]["version"]
    assert payload["runtime"] == {
        "namespace": "mainsequence.markets",
        "default_namespace": "mainsequence.markets",
        "management_mode": "platform_managed",
        "schema_mutation_allowed": False,
        "requires_migrations": True,
    }
    assert payload["documentation"] == {
        "openapi_url": "/openapi.json",
        "swagger_url": "/docs",
        "redoc_url": "/redoc",
    }
    assert "identity" not in payload
    assert payload["assumptions"][0] == {
        "key": "namespace",
        "label": "Markets namespace",
        "value": "mainsequence.markets",
        "source": "msm.settings",
        "description": (
            "Runtime MetaTables and time-index table updaters resolve against this namespace."
        ),
    }


def test_get_api_settings_does_not_expose_secret_or_identity_context(monkeypatch) -> None:
    monkeypatch.setenv("MAINSEQUENCE_ACCESS_TOKEN", "secret-token-value")
    monkeypatch.setenv("MAINSEQUENCE_REFRESH_TOKEN", "refresh-token-value")

    client = TestClient(app)
    response = client.get("/api/v1/settings/")

    assert response.status_code == 200
    serialized = json.dumps(response.json())
    assert "identity" not in serialized
    assert "secret-token-value" not in serialized
    assert "refresh-token-value" not in serialized
    assert "MAINSEQUENCE_ACCESS_TOKEN" not in serialized
    assert "MAINSEQUENCE_REFRESH_TOKEN" not in serialized


def test_openapi_json_documents_settings_route() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    operation = payload["paths"]["/api/v1/settings/"]["get"]
    assert operation["summary"] == "Get API settings"
    assert operation["operationId"] == "getApiSettings"
    assert operation["tags"] == ["settings"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiSettingsResponse"
    }
