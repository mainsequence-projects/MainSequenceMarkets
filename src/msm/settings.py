from __future__ import annotations

DEFAULT_MARKETS_NAMESPACE = "mainsequence.markets"
ASSET_IDENTIFIER_DIMENSION = "asset_identifier"
INDEX_IDENTIFIER_DIMENSION = "index_identifier"


def markets_namespace(namespace: str | None = None) -> str:
    """Return ``namespace``, or Markets' own namespace when none is given."""

    if namespace not in (None, ""):
        return str(namespace)
    return DEFAULT_MARKETS_NAMESPACE


def markets_identifier(identifier: str, namespace: str | None = None) -> str:
    """Return the logical identifier of a resource in ``namespace``, Markets' own by default."""

    resolved_identifier = str(identifier).strip(".")
    resolved_namespace = markets_namespace(namespace)
    if resolved_namespace == DEFAULT_MARKETS_NAMESPACE:
        return resolved_identifier

    namespace_prefix = f"{resolved_namespace}."
    if resolved_identifier.startswith(namespace_prefix):
        return resolved_identifier
    return f"{namespace_prefix}{resolved_identifier}"


__all__ = [
    "ASSET_IDENTIFIER_DIMENSION",
    "DEFAULT_MARKETS_NAMESPACE",
    "INDEX_IDENTIFIER_DIMENSION",
    "markets_identifier",
    "markets_namespace",
]
