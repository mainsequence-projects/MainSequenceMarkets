from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from apps.v1 import dev_cors, main


def test_dev_cors_wrapper_adds_cors_without_mutating_main_app() -> None:
    assert any(middleware.cls is CORSMiddleware for middleware in dev_cors.app.user_middleware)
    assert not any(middleware.cls is CORSMiddleware for middleware in main.app.user_middleware)


def test_dev_cors_allows_delete_preflight() -> None:
    client = TestClient(dev_cors.app)

    response = client.options(
        "/api/v1/portfolio/portfolio-uid/weights/",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "DELETE" in response.headers["access-control-allow-methods"]
