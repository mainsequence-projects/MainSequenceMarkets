from __future__ import annotations

import os

DEFAULT_MARKETS_NAMESPACE = "mainsequence.markets"
MSM_AUTO_REGISTER_NAMESPACE_ENV = "MSM_AUTO_REGISTER_NAMESPACE"
ASSET_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"
INDEX_UNIQUE_IDENTIFIER_DIMENSION = "unique_identifier"


def markets_namespace(namespace: str | None = None) -> str:
    """Return the active markets namespace for MetaTables and DataNodes."""

    if namespace not in (None, ""):
        return str(namespace)
    return os.getenv(MSM_AUTO_REGISTER_NAMESPACE_ENV) or DEFAULT_MARKETS_NAMESPACE


def markets_auto_register_namespace() -> str | None:
    """Return the environment-provided startup namespace when configured."""

    if os.getenv(MSM_AUTO_REGISTER_NAMESPACE_ENV):
        return markets_namespace()
    return None


def markets_identifier(identifier: str, namespace: str | None = None) -> str:
    """Return the active logical identifier for markets resources."""

    resolved_identifier = str(identifier).strip(".")
    resolved_namespace = markets_namespace(namespace)
    if resolved_namespace == DEFAULT_MARKETS_NAMESPACE:
        return resolved_identifier

    namespace_prefix = f"{resolved_namespace}."
    if resolved_identifier.startswith(namespace_prefix):
        return resolved_identifier
    return f"{namespace_prefix}{resolved_identifier}"


def markets_data_node_identifier(identifier: str, namespace: str | None = None) -> str:
    """Return a DataNode identifier scoped to the markets application namespace."""

    return markets_identifier(identifier, namespace=namespace)


__all__ = [
    "ASSET_UNIQUE_IDENTIFIER_DIMENSION",
    "DEFAULT_MARKETS_NAMESPACE",
    "INDEX_UNIQUE_IDENTIFIER_DIMENSION",
    "MSM_AUTO_REGISTER_NAMESPACE_ENV",
    "markets_auto_register_namespace",
    "markets_data_node_identifier",
    "markets_identifier",
    "markets_namespace",
]
