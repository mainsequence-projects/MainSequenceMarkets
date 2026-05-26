from __future__ import annotations

from importlib.metadata import version

from fastapi import FastAPI

from apps.v1.routers.assets import router as assets_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="MainSequence Markets API",
        version=version("ms-markets"),
    )
    app.include_router(assets_router, prefix="/api/v1")
    return app


app = create_app()
