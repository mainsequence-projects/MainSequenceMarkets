from __future__ import annotations

import hashlib
import re

from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    AlembicVersionMetaTable,
)

from msm.base import MARKETS_SCHEMA, MARKETS_TABLE_APP, MarketsBase, markets_table_name
from msm.maintenance.catalog import refresh_markets_catalog_from_registered_metatables
from msm.settings import markets_auto_register_namespace, markets_identifier, markets_namespace
from migrations.registry import metatable_provider_models

NAMESPACE_VERSION_LOCATION_PREFIX = "migrations:versions"


def namespace_version_slug(namespace: str | None) -> str:
    """Return the deterministic filesystem slug for one migration namespace."""

    if namespace is None or namespace.strip() == "":
        return "default"

    slug = re.sub(r"[^0-9a-zA-Z]+", "_", namespace.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        raise ValueError("Migration namespace slug cannot be empty.")
    if len(slug) <= 48:
        return slug

    digest = hashlib.sha1(namespace.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:37].rstrip('_')}_{digest}"


def active_namespace_version_slug() -> str:
    return namespace_version_slug(markets_auto_register_namespace())


def active_namespace_version_location() -> str:
    return f"{NAMESPACE_VERSION_LOCATION_PREFIX}/{active_namespace_version_slug()}"


class MarketsAlembicVersion(AlembicVersionMetaTable):
    __metatable_namespace__ = markets_namespace()
    __metatable_identifier__ = markets_identifier("msm.alembic_version")
    __alembic_version_schema__ = MARKETS_SCHEMA
    __alembic_version_table_name__ = markets_table_name(
        MARKETS_TABLE_APP,
        "alembic_version",
        suffix=markets_auto_register_namespace(),
    )
    __alembic_version_column_name__ = "version_num"


migration = AlembicMetaTableMigration(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    version_locations=[active_namespace_version_location()],
    version_path=active_namespace_version_location(),
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=metatable_provider_models(),
    after_register_metatables=refresh_markets_catalog_from_registered_metatables,
)


__all__ = [
    "MarketsAlembicVersion",
    "active_namespace_version_location",
    "active_namespace_version_slug",
    "migration",
    "namespace_version_slug",
]
