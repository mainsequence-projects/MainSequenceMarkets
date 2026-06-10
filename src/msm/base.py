from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from mainsequence.meta_tables import (
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaTable,
    schema_table_name,
    sqlalchemy_naming_convention,
)

from msm.settings import (
    DEFAULT_MARKETS_NAMESPACE,
    MSM_AUTO_REGISTER_NAMESPACE_ENV,
    markets_auto_register_namespace,
    markets_configured_namespace,
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


def markets_table_storage_app(model_or_table: Any) -> str:
    """Return the SQLAlchemy table-name app segment for a markets model."""

    storage_app = getattr(model_or_table, "__markets_storage_app__", None)
    if storage_app in (None, ""):
        table = getattr(model_or_table, "__table__", None)
        if table is None and not isinstance(model_or_table, type):
            table = model_or_table
        info = getattr(table, "info", None)
        if isinstance(info, Mapping):
            storage_app = info.get("markets_storage_app")

    if storage_app in (None, ""):
        storage_app = MARKETS_TABLE_APP

    storage_app = str(storage_app).strip()
    if not storage_app:
        raise ValueError("Markets table storage app must be a non-empty string.")
    return storage_app


def _markets_table(model_or_table: Any) -> Any:
    table = getattr(model_or_table, "__table__", model_or_table)
    if table is None:
        raise ValueError("Markets table identity helpers require SQLAlchemy table metadata.")
    return table


def markets_table_args(
    identifier: str,
    *constraints: Any,
    schema: str | None = MARKETS_SCHEMA,
    namespace: str | None = None,
) -> tuple[Any, ...]:
    resolved_namespace = markets_configured_namespace(namespace)
    table_options: dict[str, Any] = {
        "info": {
            "namespace": resolved_namespace,
            "identifier": markets_identifier(identifier, namespace=resolved_namespace),
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

    if (
        "__markets_base_identifier__" not in cls.__dict__
        and "__metatable_identifier__" not in cls.__dict__
        and cls.__dict__.get("__abstract__") is True
    ):
        return

    authored_identifier = _authored_metatable_identifier_for_model(cls)
    cls.__markets_authored_identifier__ = authored_identifier
    cls.__metatable_identifier__ = _resolved_metatable_identifier_for_model(
        cls,
        authored_identifier,
    )


def _markets_table_name_for_model(cls: type) -> str:
    return markets_table_name(
        markets_table_storage_app(cls),
        _authored_metatable_identifier_for_model(cls),
        suffix=markets_auto_register_namespace(),
    )


def _authored_metatable_identifier_for_model(cls: type) -> str:
    identifier = cls.__dict__.get("__markets_base_identifier__")
    if identifier in (None, ""):
        identifier = cls.__dict__.get("__markets_authored_identifier__")
    if identifier in (None, ""):
        identifier = cls.__dict__.get("__metatable_identifier__")
    if identifier in (None, ""):
        raise ValueError(
            f"{cls.__name__} must declare __markets_base_identifier__ or __metatable_identifier__."
        )
    return str(identifier).strip(".")


def _resolved_metatable_identifier_for_model(cls: type, authored_identifier: str) -> str:
    declared_namespace = getattr(cls, "__metatable_namespace__", None)
    effective_namespace = markets_configured_namespace(declared_namespace)
    identifier = _identifier_for_effective_namespace(
        cls=cls,
        authored_identifier=authored_identifier,
        declared_namespace=declared_namespace,
        effective_namespace=effective_namespace,
    )
    return markets_identifier(identifier, namespace=effective_namespace)


def _identifier_for_effective_namespace(
    *,
    cls: type,
    authored_identifier: str,
    declared_namespace: str | None,
    effective_namespace: str,
) -> str:
    if "__markets_base_identifier__" in cls.__dict__:
        return authored_identifier

    if declared_namespace in (None, "", effective_namespace):
        return authored_identifier

    namespace_prefix = f"{str(declared_namespace).strip('.')}."
    if authored_identifier.startswith(namespace_prefix):
        return authored_identifier.removeprefix(namespace_prefix)

    return authored_identifier


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

    table_info = dict(table_kwargs.get("info") or {})
    table_info.setdefault("markets_storage_app", markets_table_storage_app(cls))
    authored_identifier = _authored_metatable_identifier_for_model(cls)
    table_info["namespace"] = markets_configured_namespace(
        getattr(cls, "__metatable_namespace__", None)
    )
    table_info["identifier"] = _resolved_metatable_identifier_for_model(
        cls,
        authored_identifier,
    )
    table_kwargs["info"] = table_info

    return Table(str(name), metadata, *table_items, **table_kwargs)


class MarketsMetaTableMixin(PlatformManagedMetaTable):
    """Shared metadata contract for markets SQLAlchemy MetaTable models."""

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str | None] = MARKETS_SCHEMA
    __markets_storage_app__: ClassVar[str] = MARKETS_TABLE_APP
    __markets_base_identifier__: ClassVar[str]
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

    @classmethod
    def get_identifier(cls) -> str:
        meta_table = cls.get_meta_table()
        identifier = getattr(meta_table, "identifier", None)
        if identifier in (None, ""):
            raise RuntimeError(
                f"{cls.__name__} is not attached to a backend MetaTable. Attach schemas "
                "before requesting the registered identifier."
            )
        return str(identifier)


class MarketsTimeIndexMetaTableMixin(PlatformTimeIndexMetaTable):
    """Shared contract for markets storage-first time-indexed MetaTable models.

    Sibling of `MarketsMetaTableMixin` for time-index storage classes. Concrete
    subclasses set `__metatable_identifier__`, `__time_index_name__`, and
    `__index_names__`. The authored MetaTable identifier seeds the SQLAlchemy
    table name and default DataNode identifier.
    """

    __abstract__ = True
    __metatable_namespace__: ClassVar[str] = markets_namespace()
    __metatable_schema__: ClassVar[str | None] = MARKETS_SCHEMA
    __markets_storage_app__: ClassVar[str] = MARKETS_TABLE_APP
    __markets_base_identifier__: ClassVar[str]
    __metatable_identifier__: ClassVar[str]

    @classmethod
    def __table_cls__(cls, *args: Any, **kwargs: Any) -> Any:
        table_kwargs = dict(kwargs)
        schema = normalize_metatable_schema(
            table_kwargs.get("schema", getattr(cls, "__metatable_schema__", None))
        )
        if schema is None:
            table_kwargs.pop("schema", None)
        else:
            table_kwargs["schema"] = schema

        table_info = dict(table_kwargs.get("info") or {})
        table_info.setdefault("markets_storage_app", markets_table_storage_app(cls))
        authored_identifier = _authored_metatable_identifier_for_model(cls)
        table_info["namespace"] = markets_configured_namespace(
            getattr(cls, "__metatable_namespace__", None)
        )
        table_info["identifier"] = _resolved_metatable_identifier_for_model(
            cls,
            authored_identifier,
        )
        table_kwargs["info"] = table_info

        return PlatformTimeIndexMetaTable.__table_cls__.__func__(cls, *args, **table_kwargs)

    def __init_subclass__(cls, **kwargs: Any):
        super().__init_subclass__(**kwargs)
        _assign_markets_metatable_identifiers(cls)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return _markets_table_name_for_model(cls)

    @classmethod
    def metatable_identifier(cls) -> str:
        return cls.__metatable_identifier__

    @classmethod
    def get_identifier(cls) -> str:
        meta_table = cls.get_meta_table()
        identifier = getattr(meta_table, "identifier", None)
        if identifier in (None, ""):
            raise RuntimeError(
                f"{cls.__name__} is not attached to a backend TimeIndexMetaTable. "
                "Attach schemas before requesting the registered identifier."
            )
        return str(identifier)


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
    "markets_configured_namespace",
    "markets_identifier",
    "markets_meta_table_identifier",
    "markets_table_args",
    "markets_table_name",
    "markets_table_storage_app",
    "markets_table_storage_name",
    "markets_namespace",
    "new_markets_uid",
    "normalize_metatable_schema",
]
