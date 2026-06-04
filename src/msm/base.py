from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from mainsequence.meta_tables import (
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaData,
    schema_table_name,
    sqlalchemy_naming_convention,
)

from msm.settings import (
    DEFAULT_MARKETS_NAMESPACE,
    MSM_AUTO_REGISTER_NAMESPACE_ENV,
    markets_auto_register_namespace,
    markets_identifier,
    markets_namespace,
)

try:
    from sqlalchemy import MetaData, Table
    from sqlalchemy.orm import DeclarativeBase, declared_attr
except ImportError as exc:  # pragma: no cover - exercised only in partial envs.
    raise ImportError(
        "msm SQLAlchemy MetaTable models require SQLAlchemy in the runtime environment."
    ) from exc


MARKETS_NAMESPACE = DEFAULT_MARKETS_NAMESPACE
MARKETS_DEFAULT_SCHEMA = "public"
MARKETS_SCHEMA = None
MARKETS_TABLE_APP = "ms_markets"
markets_table_name = schema_table_name


def normalize_metatable_schema(schema: str | None) -> str | None:
    if schema is None:
        return None
    schema_name = str(schema).strip()
    if schema_name in ("", MARKETS_DEFAULT_SCHEMA):
        return None
    return schema_name


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
    """Return the authored SQLAlchemy table name for a markets table."""

    table = _markets_table(model_or_table)
    table_name = getattr(table, "name", None)
    if table_name in (None, ""):
        raise ValueError("Markets SQLAlchemy table metadata must expose a non-empty table name.")
    return str(table_name)


def _markets_table(model_or_table: Any) -> Any:
    table = getattr(model_or_table, "__table__", model_or_table)
    if table is None:
        raise ValueError("Markets table identity helpers require SQLAlchemy table metadata.")
    return table


def markets_table_args(
    identifier: str,
    *constraints: Any,
    schema: str | None = MARKETS_SCHEMA,
) -> tuple[Any, ...]:
    table_options: dict[str, Any] = {
        "info": {
            "namespace": markets_namespace(),
            "identifier": markets_identifier(identifier),
        },
    }
    normalized_schema = normalize_metatable_schema(schema)
    if normalized_schema is not None:
        table_options["schema"] = normalized_schema

    return (
        *constraints,
        table_options,
    )


class MarketsBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


def _assign_markets_metatable_identifiers(cls: type) -> None:
    """Assign the SDK MetaTable identifier from the authored table identity."""

    authored_identifier = _authored_metatable_identifier_for_model(cls)
    cls.__metatable_identifier__ = markets_identifier(
        authored_identifier,
        namespace=getattr(cls, "__metatable_namespace__", None),
    )


def _markets_table_name_for_model(cls: type) -> str:
    return markets_table_name(
        MARKETS_TABLE_APP,
        _authored_metatable_identifier_for_model(cls),
        suffix=markets_auto_register_namespace(),
    )


def _authored_metatable_identifier_for_model(cls: type) -> str:
    return str(cls.__dict__["__metatable_identifier__"]).strip(".")


def _build_markets_table(cls: type, *args: Any, **kwargs: Any) -> Any:
    if len(args) < 2:
        raise TypeError("SQLAlchemy __table_cls__ expected name, metadata, and columns.")

    name, metadata, *table_items = args
    table_kwargs = dict(kwargs)
    schema = normalize_metatable_schema(
        table_kwargs.get("schema", getattr(cls, "__metatable_schema__", None))
    )
    if schema is None:
        table_kwargs.pop("schema", None)
    else:
        table_kwargs["schema"] = schema

    return Table(str(name), metadata, *table_items, **table_kwargs)


class MarketsMetaTableMixin(PlatformManagedMetaTable):
    """Shared metadata contract for markets SQLAlchemy MetaTable models."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str | None] = MARKETS_SCHEMA
    __metatable_identifier__: ClassVar[str]

    @classmethod
    def __table_cls__(cls, *args: Any, **kwargs: Any) -> Any:
        return _build_markets_table(cls, *args, **kwargs)

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        _assign_markets_metatable_identifiers(cls)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return _markets_table_name_for_model(cls)

    @classmethod
    def metatable_identifier(cls) -> str:
        return cls.__metatable_identifier__


class MarketsTimeIndexMetaTableMixin(PlatformTimeIndexMetaData):
    """Shared contract for markets storage-first time-indexed MetaTable models.

    Sibling of `MarketsMetaTableMixin` for time-index storage classes. Concrete
    subclasses set `__metatable_identifier__`, `__time_index_name__`, and
    `__index_names__`. The authored MetaTable identifier seeds the package-owned
    SQLAlchemy table name and default DataNode identifier.
    """

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str | None] = MARKETS_SCHEMA
    __metatable_identifier__: ClassVar[str]

    @classmethod
    def __table_cls__(cls, *args: Any, **kwargs: Any) -> Any:
        return _build_markets_table(cls, *args, **kwargs)

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        _assign_markets_metatable_identifiers(cls)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return _markets_table_name_for_model(cls)

    @classmethod
    def metatable_identifier(cls) -> str:
        return cls.__metatable_identifier__


def new_markets_uid() -> uuid.UUID:
    return uuid.uuid4()


__all__ = [
    "MARKETS_NAMESPACE",
    "MARKETS_DEFAULT_SCHEMA",
    "MARKETS_SCHEMA",
    "MARKETS_TABLE_APP",
    "MSM_AUTO_REGISTER_NAMESPACE_ENV",
    "MarketsBase",
    "MarketsMetaTableMixin",
    "MarketsTimeIndexMetaTableMixin",
    "markets_identifier",
    "markets_meta_table_identifier",
    "markets_table_args",
    "markets_table_name",
    "markets_table_storage_name",
    "markets_namespace",
    "new_markets_uid",
    "normalize_metatable_schema",
]
