from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from mainsequence.meta_tables import (
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaData,
    POSTGRES_IDENTIFIER_MAX_LENGTH,
    metatable_tablename,
    slugify_identifier,
)

from msm.settings import (
    DEFAULT_MARKETS_NAMESPACE,
    MSM_AUTO_REGISTER_NAMESPACE_ENV,
    markets_identifier,
    markets_namespace,
)

try:
    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase
except ImportError as exc:  # pragma: no cover - exercised only in partial envs.
    raise ImportError(
        "msm SQLAlchemy MetaTable models require SQLAlchemy in the runtime environment."
    ) from exc


MARKETS_NAMESPACE = DEFAULT_MARKETS_NAMESPACE
MARKETS_SCHEMA = "public"


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
        namespace=markets_namespace(),
        identifier=markets_identifier(identifier),
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
                "namespace": markets_namespace(),
                "identifier": markets_identifier(identifier),
            },
        },
    )


class MarketsBase(DeclarativeBase):
    metadata = MetaData()


def _assign_markets_metatable_identifiers(cls: type) -> None:
    """Resolve and assign `__markets_base_identifier__`/`__metatable_identifier__`.

    Shared by the plain and time-indexed markets mixins so both derive the
    namespaced identifier the same way.
    """

    base_identifier = (
        cls.__dict__.get("__markets_base_identifier__")
        or cls.__dict__.get("__metatable_identifier__")
        or getattr(cls, "__markets_base_identifier__", None)
        or getattr(cls, "__metatable_identifier__", cls.__name__)
    )
    cls.__markets_base_identifier__ = str(base_identifier).strip(".")
    cls.__metatable_identifier__ = markets_identifier(
        cls.__markets_base_identifier__,
        namespace=getattr(cls, "__metatable_namespace__", None),
    )


class MarketsMetaTableMixin(PlatformManagedMetaTable):
    """Shared metadata contract for markets SQLAlchemy MetaTable models."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str] = MARKETS_SCHEMA
    __metatable_identifier__: ClassVar[str]
    __markets_base_identifier__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        _assign_markets_metatable_identifiers(cls)

    @classmethod
    def metatable_identifier(cls) -> str:
        return getattr(cls, "__metatable_identifier__", cls.__name__)


class MarketsTimeIndexMetaTableMixin(PlatformTimeIndexMetaData):
    """Shared contract for markets storage-first time-indexed MetaTable models.

    Sibling of `MarketsMetaTableMixin` for `PlatformTimeIndexMetaData` storage
    classes. Concrete subclasses set `__markets_base_identifier__`,
    `__time_index_name__`, `__index_names__`, and a unique
    `__metatable_extra_hash_components__` (the physical table name derives from
    the storage shape, so identical shapes collide without it).
    """

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str] = MARKETS_SCHEMA
    __metatable_identifier__: ClassVar[str]
    __markets_base_identifier__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        _assign_markets_metatable_identifiers(cls)

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
    "MarketsTimeIndexMetaTableMixin",
    "markets_fk_name",
    "markets_index_name",
    "markets_identifier",
    "markets_postgres_identifier",
    "markets_table_args",
    "markets_table_name",
    "markets_namespace",
    "new_markets_uid",
]
