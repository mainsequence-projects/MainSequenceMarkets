from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from apps.v1 import dev_cors, main


def test_dev_cors_wrapper_adds_cors_without_mutating_main_app() -> None:
    assert any(middleware.cls is CORSMiddleware for middleware in dev_cors.app.user_middleware)
    assert not any(middleware.cls is CORSMiddleware for middleware in main.app.user_middleware)
