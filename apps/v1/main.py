from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from mainsequence.server.fastapi import install_request_identity
from mainsequence.client.exceptions import ServerError
from metatables.endpoint import ApiResolutionError, api_endpoint_scope

from apps.v1.routers.accounts import router as accounts_router
from apps.v1.routers.asset_categories import router as asset_categories_router
from apps.v1.routers.assets import router as assets_router
from apps.v1.routers.calendars import router as calendars_router
from apps.v1.routers.command_center import router as command_center_router
from apps.v1.routers.indices import index_type_router, router as indices_router
from apps.v1.routers.portfolio_groups import router as portfolio_groups_router
from apps.v1.routers.portfolio_signals import router as portfolio_signals_router
from apps.v1.routers.portfolios import router as portfolios_router
from apps.v1.routers.pricing_curves import router as pricing_curves_router
from apps.v1.routers.pricing_assets import router as pricing_assets_router
from apps.v1.routers.pricing_market_data import router as pricing_market_data_router
from apps.v1.routers.resource_discovery import router as resource_discovery_router
from apps.v1.routers.rows import router as rows_router
from apps.v1.routers.settings import router as settings_router
from apps.v1.routers.virtual_funds import router as virtual_funds_router
from apps.v1.openapi_documentation import apply_metatable_documentation
from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime, ensure_apps_v1_runtime

API_TITLE = "MainSequence Markets Public API"
API_VERSION = version("ms-markets")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_SOURCE_REPOSITORY = "https://github.com/mainsequence-projects/MainSequenceMarkets"
OPENAPI_LOGO_URL = "/static/main-sequence-markets/main_sequence_markets_icon_emblem_transparent.png"
OPENAPI_LOGO = {
    "url": OPENAPI_LOGO_URL,
    "altText": "Main Sequence Markets",
    "backgroundColor": "#111827",
    "href": "/docs",
}
API_DESCRIPTION = (
    "HTTP interface for Main Sequence Markets application resources. The API exposes "
    "canonical Command Center collections and discovery contracts alongside typed detail, "
    "summary, action, pricing, and market-data operations. Route handlers resolve into reusable "
    "markets logic from `src/`; OpenAPI is the authoritative machine-readable description of "
    "this HTTP surface."
)
API_TAGS = [
    {
        "name": "account",
        "x-displayName": "Accounts",
        "description": "Managed-account identities, target allocations, holdings, and account operations.",
    },
    {
        "name": "asset",
        "x-displayName": "Assets",
        "description": (
            "Canonical asset identities, current display snapshots, pricing details, and related "
            "MetaTable discovery. Asset identity remains separate from timestamped facts and "
            "instrument-specific detail records."
        ),
    },
    {
        "name": "asset-category",
        "x-displayName": "Asset Categories",
        "description": "Named asset groupings and their many-to-many membership with canonical assets.",
    },
    {
        "name": "index",
        "x-displayName": "Indices",
        "description": (
            "Reusable market observables, index types, versioned formulas, canonical datasets, "
            "and related MetaTables. An Index is not implicitly a tradable Asset."
        ),
    },
    {
        "name": "calendar",
        "x-displayName": "Calendars",
        "description": "Calendar identities plus dated business-day, session, and event facts.",
    },
    {
        "name": "pricing-market-data",
        "x-displayName": "Pricing Market Data",
        "description": "Pricing market-data set and concept binding management endpoints.",
    },
    {
        "name": "pricing-curve",
        "x-displayName": "Pricing Curves",
        "description": "Pricing curve registry endpoints.",
    },
    {
        "name": "pricing-asset",
        "x-displayName": "Asset Pricing",
        "description": "Fixed income asset pricing operation endpoints.",
    },
    {
        "name": "portfolio",
        "x-displayName": "Portfolios",
        "description": "Portfolio identities, summaries, weights, values, signals, and deletion operations.",
    },
    {
        "name": "portfolio-group",
        "x-displayName": "Portfolio Groups",
        "description": "Portfolio group registry and many-to-many membership endpoints.",
    },
    {
        "name": "portfolio-signal",
        "x-displayName": "Portfolio Signals",
        "description": "Portfolio signal metadata and signal-weight storage cleanup endpoints.",
    },
    {
        "name": "virtualfund",
        "x-displayName": "Virtual Funds",
        "description": "Virtual-fund identities, details, allocations, and holdings snapshots.",
    },
    {
        "name": "settings",
        "x-displayName": "Settings",
        "description": "Read-only app settings and runtime assumption endpoints.",
    },
    {
        "name": "command-center",
        "x-displayName": "Command Center",
        "description": "Command Center Adapter from API discovery and health endpoints.",
    },
    {
        "name": "rows",
        "x-displayName": "Remote Row Operations",
        "description": (
            "Row class methods for `msm.client`'s remote backend (ADR 0047): an application "
            "runs `msm.api` row operations here instead of holding MetaTables grants."
        ),
    },
    {
        "name": "resource-discovery",
        "x-displayName": "Resource Discovery",
        "description": (
            "Canonical `command-center.resource_discovery@v1` descriptions for every collection, "
            "including identity, search, filters, ordering, columns, and authorized bulk actions."
        ),
    },
]
API_TAG_GROUPS = [
    {
        "name": "Markets resources",
        "tags": [
            "asset",
            "asset-category",
            "index",
            "portfolio",
            "portfolio-group",
            "portfolio-signal",
            "account",
            "virtualfund",
            "calendar",
        ],
    },
    {
        "name": "Pricing",
        "tags": ["pricing-asset", "pricing-curve", "pricing-market-data"],
    },
    {
        "name": "Platform integration",
        "tags": ["resource-discovery", "command-center", "settings", "rows"],
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    deadline = time.monotonic() + 300
    while True:
        try:
            # These attachments only read migrated tables. Each attempt pins
            # the Environment endpoint; successful attachments are cached.
            with api_endpoint_scope(discovery_timeout=max(0.1, deadline - time.monotonic())):
                ensure_apps_v1_runtime()
                ensure_apps_v1_pricing_runtime()
            break
        except (ServerError, ApiResolutionError) as exc:
            temporary_auth = (
                isinstance(exc, ServerError)
                and exc.status_code == 503
                and isinstance(exc.payload, dict)
                and exc.payload.get("code") == "authentication_unavailable"
            )
            temporary_wake = (
                type(exc) is ApiResolutionError
                and str(exc) == "MetaTables deployment is unavailable; check its deployment status."
            )
            remaining = deadline - time.monotonic()
            if not (temporary_auth or temporary_wake) or remaining <= 0:
                raise
            logging.getLogger(__name__).warning("Temporary MetaTables startup unavailability; retrying attachment")
            await asyncio.sleep(min(5, remaining))
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
    app.mount(
        "/static/main-sequence-markets",
        StaticFiles(directory=PROJECT_ROOT / "docs" / "img" / "main-sequence-markets"),
        name="main-sequence-markets-static",
    )
    from apps.v1.policy import RegistryWriteForbidden, RegistryWritePolicyError

    @app.exception_handler(RegistryWriteForbidden)
    async def _registry_write_forbidden(_request: Request, exc: RegistryWriteForbidden):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(RegistryWritePolicyError)
    async def _registry_write_policy_error(_request: Request, exc: RegistryWritePolicyError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.include_router(command_center_router)
    # Discovery routes must precede parameterized resource-detail routes.
    app.include_router(resource_discovery_router, prefix="/api/v1")
    app.include_router(accounts_router, prefix="/api/v1")
    app.include_router(assets_router, prefix="/api/v1")
    app.include_router(asset_categories_router, prefix="/api/v1")
    app.include_router(indices_router, prefix="/api/v1")
    app.include_router(index_type_router, prefix="/api/v1")
    app.include_router(portfolio_groups_router, prefix="/api/v1")
    app.include_router(portfolio_signals_router, prefix="/api/v1")
    app.include_router(portfolios_router, prefix="/api/v1")
    app.include_router(virtual_funds_router, prefix="/api/v1")
    app.include_router(calendars_router, prefix="/api/v1")
    app.include_router(pricing_assets_router, prefix="/api/v1")
    app.include_router(pricing_curves_router, prefix="/api/v1")
    app.include_router(pricing_market_data_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
    app.include_router(rows_router, prefix="/api/v1")

    def custom_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=API_TITLE,
            version=API_VERSION,
            description=API_DESCRIPTION,
            routes=app.routes,
            tags=API_TAGS,
        )
        openapi_schema["servers"] = [
            {"url": "/", "description": "Current deployment"},
        ]
        openapi_schema.setdefault("info", {})
        openapi_schema["info"]["x-app-scope"] = "apps/v1"
        openapi_schema["info"]["x-logo"] = OPENAPI_LOGO
        openapi_schema["externalDocs"] = {
            "description": "Main Sequence Markets API source repository",
            "url": API_SOURCE_REPOSITORY,
        }
        openapi_schema["x-tagGroups"] = API_TAG_GROUPS
        apply_metatable_documentation(openapi_schema)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    # Authenticates every request before its handler: the gateway's signed caller
    # assertion when hosted, the caller's Bearer token locally. The platform
    # launcher refuses to serve an application without it.
    install_request_identity(app)
    return app


app = create_app()
