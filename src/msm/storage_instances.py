"""An owner's instances of Markets time-index storages, declared as classes (ADR 0047, 0066).

A provider that produces a Markets time series (discount curves, index fixings,
pricing details, index values, orders, trades ...) writes it into its own
instance of the Markets storage, in its own MetaTables namespace, migrated by
its own Alembic provider, and binds its updater with ``output_table=``. Markets
keeps owning the storage contract: the instance has the core storage's columns,
dtypes, nullability, time index, index names and foreign keys to the Markets
registries. Portfolio values and weights are never instances: they are published
to Markets' own tables (ADR 0060). A computed signal writes an instance of
``SignalWeightsTS``, its node's own table, and publishes the same rows to Markets'.

The owner declares each instance with a ``class`` statement at the top level of a
module of its repository (ADR 0066). The class inherits the contract's base, named
``<Contract>Instance`` next to the core storage (``TradesInstance``,
``InterpolatedPricesInstance``, ``PortfolioEventLedgerInstance`` ...), and the owner's
own declarative base, whose metadata its migration provider targets. Its own
attributes say which instance it is:

- ``__instance_key__``: the instance's key, 1-63 lowercase letters, digits or
  underscores (an Index-value table is keyed by its cadence instead);
- ``__metatable_namespace__``: the owner's MetaTables namespace;
- ``__markets_storage_app__``: the owner's app segment of the table name;
- ``__cadence__``: only where the core declares none and the instance has one, as
  an interpolated-price table's upsample frequency.

The class statement builds the table when the module is imported, so the class
has that module's import address (``module:qualname``), which a node Job run in
another process imports (MetaTables ADR 0032). Nothing builds a table class while
a run is going.

The table is named ``<storage_app>__<core table>__<instance_key>`` and identified
as ``<CoreIdentifier>.<instance_key>``, namespace-prefixed outside the default
Markets namespace. MetaTables' ``schema_table_name`` writes the name: it puts
``t_`` before a key that starts with a digit and shortens a name longer than 63
characters. Its foreign keys point at Markets' own ``Column`` objects, so no
Markets table is copied into the owner's metadata, and ``target_metadata=<its
base>.metadata`` migrates the owner's tables only.

```python
class MyTrades(TradesInstance, MyBase):
    __instance_key__ = "main"
    __metatable_namespace__ = "my-provider"
    __markets_storage_app__ = "my_provider"
```
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table
from sqlalchemy.orm import DeclarativeBase

from metatables import (
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaTable,
    schema_index_name,
    schema_table_name,
)
from msm.base import MarketsTimeIndexMetaTableMixin
from msm.settings import markets_identifier

INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")
STORAGE_CONTRACT_COMPONENT = "storage_contract"
INSTANCE_KEY_COMPONENT = "instance_key"

# Defaults that Markets' and MetaTables' own bases give every table. An instance never
# takes its owner from them (#95): the owner states its namespace and app segment.
_LIBRARY_BASES = (
    MarketsTimeIndexMetaTableMixin,
    PlatformTimeIndexMetaTable,
    PlatformManagedMetaTable,
)
# What the contract gives the class. An owner that states one would change the contract.
_CONTRACT_ATTRIBUTES = (
    "__table__",
    "__tablename__",
    "__metatable_identifier__",
    "__metatable_extra_hash_components__",
    "__time_index_name__",
    "__index_names__",
    "__storage_layout__",
)


class TimeIndexInstance(MarketsTimeIndexMetaTableMixin):
    """The base of every contract's instance base (``<Contract>Instance``).

    A contract's base names its core storage in ``__core_storage__`` and stays
    abstract. A class that inherits it and is not abstract is an instance: its
    ``class`` statement builds its table on the owner's declarative base, from the
    contract and the owner's attributes (see the module docstring). A contract with
    its own rules (the portfolio contracts, Index values) overrides the
    ``_instance_*`` class methods.
    """

    __abstract__ = True
    __core_storage__: ClassVar[type[PlatformTimeIndexMetaTable]]
    __instance_key__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # Before the declarative mapping, which reads __table__ from the class.
        if not cls.__dict__.get("__abstract__", False):
            _declare_instance(cls)
        super().__init_subclass__(**kwargs)

    @classmethod
    def _instance_key(cls) -> str:
        return instance_key(owner_attribute(cls, "__instance_key__"))

    @classmethod
    def _instance_cadence(cls) -> str | None:
        """The core's cadence, or the owner's where the core declares none."""

        core = cls.__core_storage__
        declared = getattr(core, "__cadence__", None) or None
        requested = owner_attribute(cls, "__cadence__")
        if requested is None:
            return declared
        cadence = normalized_cadence(requested)
        if declared and normalized_cadence(declared) != cadence:
            raise ValueError(
                f"{cls.__name__}: {core_identifier(core)} declares cadence {declared!r}, which "
                f"its instances keep; got __cadence__ = {requested!r}."
            )
        return declared or cadence

    @classmethod
    def _instance_table_name(cls, key: str, storage_app: str) -> str:
        concept = cls.__core_storage__.__table__.name.split("__", 1)[-1]
        return schema_table_name(storage_app, concept, suffix=key)

    @classmethod
    def _instance_identifier(cls, key: str) -> str:
        return f"{core_identifier(cls.__core_storage__)}.{key}"

    @classmethod
    def _instance_hash_components(cls, key: str) -> dict[str, str]:
        return {
            STORAGE_CONTRACT_COMPONENT: core_identifier(cls.__core_storage__),
            INSTANCE_KEY_COMPONENT: key,
        }

    @classmethod
    def _instance_description(cls, key: str) -> str:
        core = cls.__core_storage__
        return (
            f"{getattr(core, '__metatable_description__', '')} Instance "
            f"{key!r} of {core_identifier(core)}."
        ).strip()

    @classmethod
    def _instance_table(cls, table_name: str, metadata: MetaData, info: dict[str, Any]) -> Table:
        """The core's columns and foreign keys, with the unique index on its index names."""

        core_table: Table = cls.__core_storage__.__table__
        # Column objects, not names: a name resolves only inside the table's own MetaData.
        # In the order of their columns, so the DDL is the same in every process: the
        # core's keys are a set.
        constraints = [
            ForeignKeyConstraint(
                list(foreign_key.column_keys),
                [element.column for element in foreign_key.elements],
                ondelete=foreign_key.ondelete,
            )
            for foreign_key in sorted(
                core_table.foreign_key_constraints, key=lambda item: list(item.column_keys)
            )
        ]
        table = Table(
            table_name,
            metadata,
            *(column._copy() for column in core_table.columns),
            *constraints,
            schema=core_table.schema,
            info=dict(info),
        )
        add_unique_index(table, list(cls.__core_storage__.__index_names__))
        return table

    @classmethod
    def _instance_attributes(cls) -> dict[str, Any]:
        """Further attributes the contract gives every instance."""

        return {}


def _declare_instance(cls: type[TimeIndexInstance]) -> None:
    core = getattr(cls, "__core_storage__", None)
    if not isinstance(core, type) or not hasattr(core, "__table__"):
        raise TypeError(
            f"{cls.__name__} must inherit a contract's instance base, such as TradesInstance, "
            "which names its Markets core storage."
        )
    stated = sorted(name for name in _CONTRACT_ATTRIBUTES if name in cls.__dict__)
    if stated:
        raise TypeError(
            f"{cls.__name__} states {', '.join(stated)}, which its contract gives. Declare "
            "only __instance_key__, __metatable_namespace__, __markets_storage_app__ and, "
            "where the contract has none, __cadence__."
        )
    namespace = _required(
        cls, "__metatable_namespace__", "the MetaTables namespace of the table's owner"
    )
    storage_app = _required(
        cls, "__markets_storage_app__", "the owner's app segment of the table name"
    )
    if not issubclass(cls, DeclarativeBase):
        raise TypeError(
            f"{cls.__name__} must also inherit the owner's declarative base, whose metadata its "
            "migration provider targets."
        )
    key = cls._instance_key()
    cadence = cls._instance_cadence()
    # The base's own MetaData: a core may map a column named "metadata" (pricing details).
    metadata = next(
        klass.__dict__["metadata"]
        for klass in cls.__mro__
        if isinstance(klass.__dict__.get("metadata"), MetaData)
    )
    table_name = cls._instance_table_name(key, storage_app)
    if table_name in metadata.tables:
        raise ValueError(
            f"{table_name} is already declared on this base, and one table has one declaration. "
            "Use that class, or give another table another instance key or storage app."
        )
    authored_identifier = cls._instance_identifier(key)
    table = cls._instance_table(
        table_name,
        metadata,
        {
            "namespace": namespace,
            "identifier": markets_identifier(authored_identifier, namespace=namespace),
            "markets_storage_app": storage_app,
        },
    )
    attributes: dict[str, Any] = {
        "__table__": table,
        "__metatable_identifier__": authored_identifier,
        "__metatable_namespace__": namespace,
        "__markets_storage_app__": storage_app,
        "__metatable_description__": cls.__dict__.get("__metatable_description__")
        or cls._instance_description(key),
        "__metatable_extra_hash_components__": cls._instance_hash_components(key),
        "__time_index_name__": core.__time_index_name__,
        "__index_names__": list(core.__index_names__),
        **cls._instance_attributes(),
    }
    if cadence:
        attributes["__cadence__"] = cadence
    for name, value in attributes.items():
        setattr(cls, name, value)


def owner_attribute(cls: type, name: str) -> Any:
    """``name`` as the owner states it on the class or a base of its own, else ``None``.

    A value Markets' or MetaTables' own bases give every table does not count, wherever
    the owner's own mixin comes in the class's bases.
    """

    for klass in cls.__mro__:
        if klass not in _LIBRARY_BASES and name in klass.__dict__:
            return klass.__dict__[name]
    return None


def _required(cls: type, name: str, meaning: str) -> str:
    value = str(owner_attribute(cls, name) or "").strip()
    if not value:
        raise ValueError(f"{cls.__name__} must declare {name}: {meaning}.")
    return value


def instance_key(value: Any) -> str:
    """A validated instance key: stripped and lower-case."""

    key = str(value or "").strip().lower()
    if not INSTANCE_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "__instance_key__ must be 1-63 lowercase letters, digits or underscores and start "
            f"with a letter or digit; got {value!r}."
        )
    return key


def normalized_cadence(cadence: str | None, *, argument: str = "cadence") -> str:
    """``cadence`` as MetaTables registers it: stripped and lower-case."""

    value = str(cadence or "").strip().lower()
    if not value:
        raise ValueError(f"{argument} must be a non-empty interval such as 5m or 1d.")
    return value


def core_identifier(core_storage: type[Any]) -> str:
    """The authored MetaTable identifier of a Markets core storage."""

    return str(
        getattr(core_storage, "__markets_authored_identifier__", None)
        or core_storage.__metatable_identifier__
    )


def add_unique_index(table: Table, index_names: list[str]) -> None:
    """The grain index every instance has on its index names."""

    Index(
        schema_index_name(table.name, index_names, unique=True),
        *(table.c[column_name] for column_name in index_names),
        unique=True,
    )


__all__ = [
    "INSTANCE_KEY_COMPONENT",
    "STORAGE_CONTRACT_COMPONENT",
    "TimeIndexInstance",
    "add_unique_index",
    "core_identifier",
    "instance_key",
    "normalized_cadence",
    "owner_attribute",
]
