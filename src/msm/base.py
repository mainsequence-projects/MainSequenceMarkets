from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from mainsequence.tdag.meta_tables import (
    PlatformManagedMetaTable,
    POSTGRES_IDENTIFIER_MAX_LENGTH,
    metatable_tablename,
    slugify_identifier,
)

try:
    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase
except ImportError as exc:  # pragma: no cover - exercised only in partial envs.
    raise ImportError(
        "msm SQLAlchemy MetaTable models require SQLAlchemy in the runtime environment."
    ) from exc


MARKETS_NAMESPACE = "mainsequence.markets"
MARKETS_SCHEMA = "public"
MSM_AUTO_REGISTER_NAMESPACE_ENV = "MSM_AUTO_REGISTER_NAMESPACE"


def markets_runtime_namespace() -> str:
    """Return the namespace used when markets models are mapped."""

    return os.getenv(MSM_AUTO_REGISTER_NAMESPACE_ENV) or MARKETS_NAMESPACE


def markets_table_name(
    identifier: str,
    *,
    schema: str = MARKETS_SCHEMA,
    hash_namespace: str | None = None,
    extra_hash_components: Mapping[str, Any] | None = None,
) -> str:
    """Return the low-level explicit MetaTable name for a markets identifier.

    Normal markets models inherit `MarketsMetaTableMixin` and let the SDK derive
    `__tablename__` from the resolved SQLAlchemy table contract.
    """

    return metatable_tablename(
        namespace=MARKETS_NAMESPACE,
        identifier=identifier,
        schema=schema,
        hash_namespace=hash_namespace,
        extra_hash_components=extra_hash_components,
    )


def markets_postgres_identifier(*parts: str, suffix: str) -> str:
    """Build a stable PostgreSQL-safe name for indexes and foreign keys."""

    base = slugify_identifier("_".join(str(part) for part in parts if part))
    suffix = slugify_identifier(suffix)
    digest = hashlib.md5(f"{base}:{suffix}".encode()).hexdigest()[:12]
    max_prefix_length = POSTGRES_IDENTIFIER_MAX_LENGTH - len(digest) - len(suffix) - 2
    prefix = base[:max_prefix_length].rstrip("_") or "markets"
    return f"{prefix}_{digest}_{suffix}"


def markets_index_name(model_identifier: str, *columns: str, unique: bool = False) -> str:
    return markets_postgres_identifier(
        "mainsequence_markets",
        model_identifier,
        *columns,
        suffix="uidx" if unique else "idx",
    )


def markets_fk_name(source_identifier: str, target_identifier: str, *columns: str) -> str:
    return markets_postgres_identifier(
        "mainsequence_markets",
        source_identifier,
        target_identifier,
        *columns,
        suffix="fkey",
    )


def markets_table_args(
    identifier: str,
    *constraints: Any,
    schema: str = MARKETS_SCHEMA,
) -> tuple[Any, ...]:
    return (
        *constraints,
        {
            "schema": schema,
            "info": {
                "namespace": markets_runtime_namespace(),
                "identifier": identifier,
            },
        },
    )


class MarketsBase(DeclarativeBase):
    metadata = MetaData()


class MarketsMetaTableMixin(PlatformManagedMetaTable):
    """Shared metadata contract for markets SQLAlchemy MetaTable models."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_runtime_namespace()
    __metatable_schema__: ClassVar[str] = MARKETS_SCHEMA
    __metatable_identifier__: ClassVar[str]

    @classmethod
    def metatable_identifier(cls) -> str:
        return getattr(cls, "__metatable_identifier__", cls.__name__)


def new_markets_uid() -> uuid.UUID:
    return uuid.uuid4()


__all__ = [
    "MARKETS_NAMESPACE",
    "MARKETS_SCHEMA",
    "MSM_AUTO_REGISTER_NAMESPACE_ENV",
    "MarketsBase",
    "MarketsMetaTableMixin",
    "markets_fk_name",
    "markets_index_name",
    "markets_postgres_identifier",
    "markets_table_args",
    "markets_table_name",
    "markets_runtime_namespace",
    "new_markets_uid",
]
