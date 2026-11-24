"""Provider-owned instances of any Markets time-index storage (ADR 0047).

A provider that produces a Markets time series (discount curves, index fixings,
pricing details, index values, orders, trades ...) writes it into its own
instance of the Markets storage, in its own MetaTables namespace, migrated by
its own Alembic provider, and binds its updater with ``output_table=``. Markets
keeps owning the storage contract: the instance has the core storage's columns,
dtypes, nullability, time index, index names and foreign keys to the Markets
registries. How Markets finds the instance depends on the series: pricing
market-data bindings carry its ``storage_table_uid``, the Index dataset catalog
its table uid (both outside ADR 0060's decision). Portfolio values and weights are
never instances: they are published to Markets' own tables (ADR 0060). A computed
signal writes an instance of ``SignalWeightsTS``, its node's own table, and publishes
the same rows to Markets' (ADR 0060 as amended on 2026-11-24). An application's private
portfolio state uses the portfolio package's own contract-instance factories.

Those foreign keys point at Markets' own ``Column`` objects. No Markets table is
copied into the provider's metadata, so ``target_metadata=<its base>.metadata``
migrates the provider's tables only.

The instance is named ``<storage_app>__<core table>__<instance_key>`` and
identified as ``<CoreIdentifier>.<instance_key>``, namespace-prefixed outside the
default Markets namespace. MetaTables' ``schema_table_name`` writes the name: it
puts ``t_`` before a key that starts with a digit and shortens a name longer than
63 characters.

The factory has no default owner: namespace, storage app and declarative base
are the caller's (#95).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table
from sqlalchemy.orm import DeclarativeBase

from metatables import PlatformTimeIndexMetaTable, schema_index_name, schema_table_name
from msm.base import MarketsTimeIndexMetaTableMixin
from msm.settings import markets_identifier

INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")
STORAGE_CONTRACT_COMPONENT = "storage_contract"
INSTANCE_KEY_COMPONENT = "instance_key"


def configured_time_index_instance(
    core_storage: type[PlatformTimeIndexMetaTable],
    *,
    instance_key: str,
    namespace: str,
    storage_app: str,
    base: type[DeclarativeBase],
    cadence: str | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build a provider-owned instance of ``core_storage``.

    ``namespace`` is the MetaTables namespace that owns the instance, for example
    ``my-provider``; ``storage_app`` the physical-name app segment, for example
    ``my_provider``; ``base`` the provider's own declarative base, whose metadata
    its Alembic provider targets. All three are required, and an empty value is
    refused. The instance adds only its own table to that metadata: its foreign
    keys point at Markets' own columns, so the provider's autogenerate never
    compares a Markets table.

    ``cadence`` is for a storage that declares none, where each instance has its
    own: an interpolated-price table's cadence is its upsample frequency. An
    instance of a storage that declares a cadence keeps it. One table has one
    declaration: a second one that differs, in cadence or namespace for example,
    is refused.
    """

    key = str(instance_key).strip().lower()
    if not INSTANCE_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "instance_key must be 1-63 lowercase letters, digits or underscores and start "
            f"with a letter or digit; got {instance_key!r}."
        )
    owner_namespace, app, owner_base = require_instance_owner(namespace, storage_app, base)
    if not isinstance(core_storage, type) or not hasattr(core_storage, "__table__"):
        raise TypeError("core_storage must be a Markets time-index storage class.")
    return _configured_time_index_instance(
        core_storage,
        key,
        owner_namespace,
        app,
        owner_base,
        _instance_cadence(core_storage, cadence),
    )


def require_instance_owner(
    namespace: str,
    storage_app: str,
    base: type[DeclarativeBase],
) -> tuple[str, str, type[DeclarativeBase]]:
    """The owner of an instance, which no instance factory supplies by itself."""

    owner_namespace = str(namespace or "").strip()
    if not owner_namespace:
        raise ValueError("namespace is required: the MetaTables namespace of the table's owner.")
    app = required_storage_app(storage_app)
    if not base:
        raise ValueError(
            "base is required: the owner's declarative base, whose metadata its migration "
            "provider targets."
        )
    return owner_namespace, app, base


def required_storage_app(storage_app: str) -> str:
    """The owner's app segment of a table name, which has no default either."""

    app = str(storage_app or "").strip()
    if not app:
        raise ValueError("storage_app is required: the owner's app segment of the table name.")
    return app


def normalized_cadence(cadence: str | None, *, argument: str = "cadence") -> str:
    """``cadence`` as MetaTables registers it: stripped and lower-case."""

    value = str(cadence or "").strip().lower()
    if not value:
        raise ValueError(f"{argument} must be a non-empty interval such as 5m or 1d.")
    return value


def time_index_instance_identifier(core_storage: type[Any], instance_key: str) -> str:
    """The authored MetaTable identifier of an instance: ``<CoreIdentifier>.<key>``."""

    return f"{_core_identifier(core_storage)}.{str(instance_key).strip().lower()}"


# Unbounded: every instance stays in its base's metadata anyway, and building one a second
# time would be refused as a second declaration of its table.
@lru_cache(maxsize=None)
def _configured_time_index_instance(
    core_storage: type[Any],
    instance_key: str,
    namespace: str,
    storage_app: str,
    base: type[DeclarativeBase],
    cadence: str | None,
) -> type[PlatformTimeIndexMetaTable]:
    core_table: Table = core_storage.__table__
    concept = core_table.name.split("__", 1)[-1]
    table_name = schema_table_name(storage_app, concept, suffix=instance_key)
    authored_identifier = time_index_instance_identifier(core_storage, instance_key)
    resolved_identifier = markets_identifier(authored_identifier, namespace=namespace)
    table = _copy_table(
        core_table,
        table_name=table_name,
        metadata=base.metadata,
        index_names=list(core_storage.__index_names__),
        info={
            "namespace": namespace,
            "identifier": resolved_identifier,
            "markets_storage_app": storage_app,
        },
    )
    class_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", f"{instance_key}_{storage_app}")
    attributes: dict[str, Any] = {
        "__module__": __name__,
        "__table__": table,
        "__metatable_identifier__": authored_identifier,
        "__metatable_namespace__": namespace,
        "__markets_storage_app__": storage_app,
        "__metatable_description__": (
            f"{getattr(core_storage, '__metatable_description__', '')} Instance "
            f"{instance_key!r} of {_core_identifier(core_storage)}."
        ).strip(),
        "__metatable_extra_hash_components__": {
            STORAGE_CONTRACT_COMPONENT: _core_identifier(core_storage),
            INSTANCE_KEY_COMPONENT: instance_key,
        },
        "__time_index_name__": core_storage.__time_index_name__,
        "__index_names__": list(core_storage.__index_names__),
    }
    if cadence:
        attributes["__cadence__"] = cadence
    return type(
        f"{core_storage.__name__}_{class_suffix}",
        (MarketsTimeIndexMetaTableMixin, base),
        attributes,
    )


def _instance_cadence(core_storage: type[Any], cadence: str | None) -> str | None:
    declared = getattr(core_storage, "__cadence__", None) or None
    if cadence is None:
        return declared
    requested = normalized_cadence(cadence)
    if declared and normalized_cadence(declared) != requested:
        raise ValueError(
            f"{_core_identifier(core_storage)} declares cadence {declared!r}, which its "
            f"instances keep; got cadence {requested!r}."
        )
    return declared or requested


def _core_identifier(core_storage: type[Any]) -> str:
    return str(
        getattr(core_storage, "__markets_authored_identifier__", None)
        or core_storage.__metatable_identifier__
    )


def _copy_table(
    core_table: Table,
    *,
    table_name: str,
    metadata: MetaData,
    index_names: list[str],
    info: dict[str, Any],
) -> Table:
    if table_name in metadata.tables:
        raise ValueError(
            f"{table_name} is already declared on this base, and one table has one declaration. "
            "Use that one, or give another table another instance_key or storage_app."
        )
    # Column objects, not names: a name resolves only inside the table's own MetaData.
    constraints = [
        ForeignKeyConstraint(
            list(foreign_key.column_keys),
            [element.column for element in foreign_key.elements],
            ondelete=foreign_key.ondelete,
        )
        for foreign_key in core_table.foreign_key_constraints
    ]
    table = Table(
        table_name,
        metadata,
        *(column._copy() for column in core_table.columns),
        *constraints,
        schema=core_table.schema,
        info=dict(info),
    )
    Index(
        schema_index_name(table_name, index_names, unique=True),
        *(table.c[column_name] for column_name in index_names),
        unique=True,
    )
    return table


__all__ = [
    "configured_time_index_instance",
    "time_index_instance_identifier",
]
