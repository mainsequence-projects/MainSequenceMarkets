from __future__ import annotations

from mainsequence.meta_tables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)

from msm.base import MARKETS_SCHEMA, MARKETS_TABLE_APP, MarketsBase, markets_table_name
from msm.settings import markets_auto_register_namespace, markets_identifier, markets_namespace
from migrations.registry import metatable_provider_models


MarketsAlembicVersion = build_alembic_version_metatable(
    class_name="MarketsAlembicVersion",
    namespace=markets_namespace(),
    identifier=markets_identifier("msm.alembic_version"),
    schema=MARKETS_SCHEMA,
    table_name=markets_table_name(
        MARKETS_TABLE_APP,
        "alembic_version",
        suffix=markets_auto_register_namespace(),
    ),
)


migration = build_metatable_migration_provider(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=metatable_provider_models(),
)


__all__ = [
    "MarketsAlembicVersion",
    "migration",
]
