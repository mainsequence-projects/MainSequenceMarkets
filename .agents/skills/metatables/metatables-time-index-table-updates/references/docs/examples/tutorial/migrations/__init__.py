from __future__ import annotations

from examples.tutorial.migrations.registry import metatable_provider_models
from examples.tutorial.tables import Base
from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)

TutorialAlembicVersion = build_alembic_version_metatable(
    class_name="TutorialAlembicVersion",
    namespace="metatables_market_tutorial",
    identifier="metatables_market_tutorial.alembic_version",
    schema=None,
    table_name="metatables_market_tutorial__alembic_version",
)

migration = build_metatable_migration_provider(
    package="examples.tutorial",
    migration_namespace="metatables_market_tutorial",
    script_location="examples.tutorial.migrations:",
    version_location_prefix="examples.tutorial.migrations:versions",
    target_metadata=Base.metadata,
    alembic_registry=TutorialAlembicVersion,
    metatable_models=metatable_provider_models(),
)


__all__ = ["TutorialAlembicVersion", "migration"]
