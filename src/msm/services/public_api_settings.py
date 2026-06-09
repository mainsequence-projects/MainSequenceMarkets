from __future__ import annotations

from typing import Any

from msm.settings import (
    DEFAULT_MARKETS_NAMESPACE,
    MSM_AUTO_REGISTER_NAMESPACE_ENV,
    markets_auto_register_namespace,
    markets_namespace,
)


def get_public_api_settings(
    *,
    app_name: str,
    app_scope: str,
    app_version: str,
    openapi_url: str,
    swagger_url: str,
    redoc_url: str,
) -> dict[str, Any]:
    auto_register_namespace = markets_auto_register_namespace()
    namespace = markets_namespace()
    namespace_source = MSM_AUTO_REGISTER_NAMESPACE_ENV if auto_register_namespace else "default"

    return {
        "app": {
            "name": app_name,
            "scope": app_scope,
            "version": app_version,
        },
        "runtime": {
            "namespace": namespace,
            "namespace_source": namespace_source,
            "default_namespace": DEFAULT_MARKETS_NAMESPACE,
            "auto_register_enabled": auto_register_namespace is not None,
            "management_mode": "platform_managed",
            "schema_mutation_allowed": False,
            "requires_migrations": True,
        },
        "documentation": {
            "openapi_url": openapi_url,
            "swagger_url": swagger_url,
            "redoc_url": redoc_url,
        },
        "assumptions": [
            {
                "key": "namespace",
                "label": "Markets namespace",
                "value": namespace,
                "source": namespace_source,
                "description": "Runtime MetaTables and DataNodes resolve against this namespace.",
            },
            {
                "key": "runtime_bootstrap",
                "label": "Runtime bootstrap",
                "value": "startup_attachment",
                "source": "apps/v1 runtime bootstrap",
                "description": (
                    "The API attaches markets and pricing runtime tables during application "
                    "startup when auto-registration namespace is configured."
                ),
            },
            {
                "key": "schema_management",
                "label": "Schema management",
                "value": "migrations_required",
                "source": "apps/v1 runtime bootstrap",
                "description": (
                    "Schema mutation is not performed by this API; required MetaTable "
                    "migrations must already be applied."
                ),
            },
        ],
    }


__all__ = ["get_public_api_settings"]
