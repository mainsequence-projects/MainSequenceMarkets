from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from apps.v1.routers.accounts import router as accounts_router
from apps.v1.routers.asset_categories import router as asset_categories_router
from apps.v1.routers.assets import router as assets_router
from apps.v1.routers.calendars import router as calendars_router
from apps.v1.routers.command_center import router as command_center_router
from apps.v1.routers.indices import router as indices_router
from apps.v1.routers.portfolio_signals import router as portfolio_signals_router
from apps.v1.routers.portfolios import router as portfolios_router
from apps.v1.routers.pricing_curves import router as pricing_curves_router
from apps.v1.routers.pricing_assets import router as pricing_assets_router
from apps.v1.routers.pricing_market_data import router as pricing_market_data_router
from apps.v1.routers.settings import router as settings_router
from apps.v1.routers.virtual_funds import router as virtual_funds_router
from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime, ensure_apps_v1_runtime

API_TITLE = "MainSequence Markets Public API"
API_VERSION = version("ms-markets")
API_DESCRIPTION = (
    "HTTP API for the local `apps/v1` surface in MainSequence Markets. "
    "This API resolves requests into reusable markets logic from `src/` and "
    "returns documented Pydantic response contracts."
)
API_TAGS = [
    {
        "name": "account",
        "description": "Account registry endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "asset",
        "description": "Asset catalog endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "asset-category",
        "description": "Asset category endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "index",
        "description": "Index registry endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "calendar",
        "description": "Calendar reference-data endpoints exposed through the `apps/v1` FastAPI surface.",
    },
    {
        "name": "pricing-market-data",
        "description": "Pricing market-data set and concept binding management endpoints.",
    },
    {
        "name": "pricing-curve",
        "description": "Pricing curve registry endpoints.",
    },
    {
        "name": "pricing-asset",
        "description": "Fixed income asset pricing operation endpoints.",
    },
    {
        "name": "portfolio",
        "description": "Portfolio identity, detail, latest weights, and delete endpoints.",
    },
    {
        "name": "portfolio-signal",
        "description": "Portfolio signal metadata and signal-weight storage cleanup endpoints.",
    },
    {
        "name": "virtualfund",
        "description": "Virtual-fund identity, detail, and holdings endpoints.",
    },
    {
        "name": "settings",
        "description": "Read-only app settings and runtime assumption endpoints.",
    },
    {
        "name": "command-center",
        "description": "Command Center Adapter from API discovery and health endpoints.",
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_apps_v1_runtime()
    ensure_apps_v1_pricing_runtime()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
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
    app.include_router(command_center_router)
    app.include_router(accounts_router, prefix="/api/v1")
    app.include_router(assets_router, prefix="/api/v1")
    app.include_router(asset_categories_router, prefix="/api/v1")
    app.include_router(indices_router, prefix="/api/v1")
    app.include_router(portfolio_signals_router, prefix="/api/v1")
    app.include_router(portfolios_router, prefix="/api/v1")
    app.include_router(virtual_funds_router, prefix="/api/v1")
    app.include_router(calendars_router, prefix="/api/v1")
    app.include_router(pricing_assets_router, prefix="/api/v1")
    app.include_router(pricing_curves_router, prefix="/api/v1")
    app.include_router(pricing_market_data_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")

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
