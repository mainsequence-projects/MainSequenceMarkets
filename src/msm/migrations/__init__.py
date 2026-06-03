from __future__ import annotations

from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    AlembicVersionMetaTable,
)

from msm.base import MARKETS_SCHEMA, MarketsBase
from msm.maintenance.catalog import refresh_markets_catalog_from_registered_metatables
from msm.migrations.registry import metatable_provider_models
from msm.settings import markets_identifier, markets_namespace


class MarketsAlembicVersion(AlembicVersionMetaTable):
    __metatable_namespace__ = markets_namespace()
    __metatable_identifier__ = markets_identifier("msm.alembic_version")
    __alembic_version_schema__ = MARKETS_SCHEMA
    __alembic_version_table_name__ = "msm_alembic_version"
    __alembic_version_column_name__ = "version_num"


migration = AlembicMetaTableMigration(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="msm:migrations",
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=metatable_provider_models(),
    after_register_metatables=refresh_markets_catalog_from_registered_metatables,
)


__all__ = [
    "MarketsAlembicVersion",
    "migration",
]
