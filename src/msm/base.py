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


def markets_meta_table_identifier(model_or_table: Any) -> str:
    """Return the stable globally unique MetaTable identifier.

    Runtime bookkeeping uses this authored identifier instead of SQLAlchemy
    table names because SDK registration may rebind tables to backend physical
    names after the model is registered.
    """

    identifier = getattr(model_or_table, "__metatable_identifier__", None)
    if identifier not in (None, ""):
        return str(identifier)

    table = _markets_table(model_or_table)
    info = getattr(table, "info", None)
    if isinstance(info, Mapping):
        identifier = info.get("identifier")
        if identifier not in (None, ""):
            return str(identifier)

    raise ValueError("Markets MetaTable models must expose a non-empty identifier.")


def markets_table_storage_name(model_or_table: Any) -> str:
    """Return the stable storage/table identity for a markets table."""

    storage_hash = getattr(model_or_table, "__metatable_storage_hash__", None)
    if storage_hash not in (None, ""):
        return str(storage_hash)

    table = _markets_table(model_or_table)
    storage_hash = getattr(table, "_mainsequence_storage_hash", None)
    if storage_hash not in (None, ""):
        return str(storage_hash)

    info = getattr(table, "info", None)
    if isinstance(info, Mapping):
        storage_hash = info.get("mainsequence_storage_hash")
        if storage_hash not in (None, ""):
            return str(storage_hash)

    table_name = getattr(table, "name", None)
    if table_name in (None, ""):
        raise ValueError("Markets SQLAlchemy table metadata must expose a non-empty table name.")
    return str(table_name)


def _markets_table(model_or_table: Any) -> Any:
    table = getattr(model_or_table, "__table__", model_or_table)
    if table is None:
        raise ValueError("Markets table identity helpers require SQLAlchemy table metadata.")
    return table


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
    "markets_meta_table_identifier",
    "markets_postgres_identifier",
    "markets_table_args",
    "markets_table_name",
    "markets_table_storage_name",
    "markets_namespace",
    "new_markets_uid",
]
