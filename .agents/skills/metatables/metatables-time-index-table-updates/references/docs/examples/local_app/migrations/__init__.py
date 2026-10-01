"""Only this application's note table belongs to this application-owned provider."""

from examples.local_app.tables import Base, Note
from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
    build_metatable_model_registry,
)

Version = build_alembic_version_metatable(
    class_name='LocalExampleVersion', namespace='metatables_local_example',
    identifier='metatables_local_example.alembic_version', schema=None,
    table_name='metatables_local_example__alembic_version',
)
migration = build_metatable_migration_provider(
    package='examples.local_app', migration_namespace='metatables_local_example',
    script_location='examples.local_app.migrations:',
    version_location_prefix='examples.local_app.migrations:versions',
    target_metadata=Base.metadata, alembic_registry=Version,
    metatable_models=build_metatable_model_registry([Note], base=Base),
)
