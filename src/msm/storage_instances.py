"""Provider-owned instances of any Markets time-index storage (ADR 0047).

A provider that produces a Markets time series (discount curves, index fixings,
pricing details, index values, orders, trades ...) writes it into its own
instance of the Markets storage, in its own MetaTables namespace, migrated by
its own Alembic provider, and binds its updater with ``output_table=``. Markets
keeps owning the storage contract: the instance has the core storage's columns,
dtypes, nullability, time index, index names and foreign keys to the Markets
registries. How Markets finds the instance depends on the series: pricing
market-data bindings carry its ``storage_table_uid``, the Index dataset catalog
its table uid. Portfolio values, weights, signal weights and the portfolio
engine outputs use the dedicated portfolio contracts and their catalog instead.

The instance is named ``<storage_app>__<core table>__<instance_key>`` and
identified as ``<CoreIdentifier>.<instance_key>``, namespace-prefixed outside the
default Markets namespace.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table
from sqlalchemy.orm import DeclarativeBase

from metatables import PlatformTimeIndexMetaTable, schema_index_name, schema_table_name
from msm.base import MARKETS_TABLE_APP, MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.settings import markets_identifier, markets_namespace

INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")
STORAGE_CONTRACT_COMPONENT = "storage_contract"
INSTANCE_KEY_COMPONENT = "instance_key"


def configured_time_index_instance(
    core_storage: type[PlatformTimeIndexMetaTable],
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build a provider-owned instance of ``core_storage``.

    ``namespace`` is the MetaTables namespace that owns the instance, for example
    ``my-provider``; ``storage_app`` the physical-name app segment, for example
    ``my_provider``; ``base`` the provider's declarative base when its own Alembic
    provider migrates the instance (the referenced Markets tables are copied into
    that base's metadata, so the migration never imports Markets classes).
    """

    key = str(instance_key).strip().lower()
    if not INSTANCE_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "instance_key must be 1-63 lowercase letters, digits or underscores and start "
            f"with a letter or digit; got {instance_key!r}."
        )
    app = str(storage_app).strip()
    if not app:
        raise ValueError("storage_app must be a non-empty app segment.")
    if not isinstance(core_storage, type) or not hasattr(core_storage, "__table__"):
        raise TypeError("core_storage must be a Markets time-index storage class.")
    return _configured_time_index_instance(
        core_storage, key, markets_namespace(namespace), app, base or MarketsBase
    )


def time_index_instance_identifier(core_storage: type[Any], instance_key: str) -> str:
    """The authored MetaTable identifier of an instance: ``<CoreIdentifier>.<key>``."""

    return f"{_core_identifier(core_storage)}.{str(instance_key).strip().lower()}"


@lru_cache(maxsize=256)
def _configured_time_index_instance(
    core_storage: type[Any],
    instance_key: str,
    namespace: str,
    storage_app: str,
    base: type[DeclarativeBase],
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
    cadence = getattr(core_storage, "__cadence__", None)
    if cadence not in (None, ""):
        attributes["__cadence__"] = cadence
    return type(
        f"{core_storage.__name__}_{class_suffix}",
        (MarketsTimeIndexMetaTableMixin, base),
        attributes,
    )


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
    existing = metadata.tables.get(table_name)
    if isinstance(existing, Table):
        return existing
    constraints = []
    for foreign_key in core_table.foreign_key_constraints:
        targets = []
        for element in foreign_key.elements:
            target_table = element.column.table
            if target_table.metadata is not metadata:
                copied = metadata.tables.get(target_table.key)
                target_table = copied if copied is not None else target_table.to_metadata(metadata)
            targets.append(f"{target_table.fullname}.{element.column.name}")
        constraints.append(
            ForeignKeyConstraint(
                list(foreign_key.column_keys),
                targets,
                ondelete=foreign_key.ondelete,
            )
        )
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
