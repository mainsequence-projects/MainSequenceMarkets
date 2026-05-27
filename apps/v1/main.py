from __future__ import annotations

from importlib.metadata import version

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from apps.v1.routers.asset_categories import router as asset_categories_router
from apps.v1.routers.assets import router as assets_router

API_TITLE = "MainSequence Markets Public API"
API_VERSION = version("ms-markets")
API_DESCRIPTION = (
    "HTTP API for the local `apps/v1` surface in MainSequence Markets. "
    "This API resolves requests into reusable markets logic from `src/` and "
    "returns documented Pydantic response contracts."
)
API_TAGS = [
    {
        "name": "asset",
        "description": "Asset catalog endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "asset-category",
        "description": "Asset category endpoints exposed through the `apps/v1` FastAPI surface.",
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        openapi_tags=API_TAGS,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        contact={
            "name": "Main Sequence GmbH",
            "email": "dev@main-sequence.io",
        },
        license_info={
            "name": "Apache-2.0",
        },
    )
    app.include_router(assets_router, prefix="/api/v1")
    app.include_router(asset_categories_router, prefix="/api/v1")

    def custom_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=API_TITLE,
            version=API_VERSION,
            description=API_DESCRIPTION,
            routes=app.routes,
        )
        openapi_schema["servers"] = [
            {"url": "/", "description": "Current deployment"},
        ]
        openapi_schema.setdefault("info", {})
        openapi_schema["info"]["x-app-scope"] = "apps/v1"
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()
