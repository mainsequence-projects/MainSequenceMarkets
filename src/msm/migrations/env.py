from __future__ import annotations

from alembic import context
from mainsequence.meta_tables.migrations import apply_mainsequence_migration_role
from sqlalchemy import engine_from_config, pool

from msm.base import MARKETS_DEFAULT_SCHEMA, MARKETS_SCHEMA
from msm.migrations import migration as default_migration


def _migration_provider():
    return context.config.attributes.get("mainsequence_migration_provider") or default_migration


def _included_schema(name: str | None) -> bool:
    if MARKETS_SCHEMA is None:
        return name in (None, MARKETS_DEFAULT_SCHEMA)
    return name == MARKETS_SCHEMA


def _uses_named_schemas() -> bool:
    migration = _migration_provider()
    if migration.version_table_schema is not None:
        return True
    return any(table.schema is not None for table in migration.target_metadata.tables.values())


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return _included_schema(name)

    schema_name = parent_names.get("schema_name") if parent_names else None
    if not _included_schema(schema_name):
        return False

    return _migration_provider().include_name(name, type_, parent_names)


def include_object(object_, name, type_, reflected, compare_to):
    object_schema = getattr(object_, "schema", None)
    if not _included_schema(object_schema):
        return False

    return _migration_provider().include_object(
        object_,
        name,
        type_,
        reflected,
        compare_to,
    )


def _configure_kwargs():
    migration = _migration_provider()
    return {
        "target_metadata": migration.target_metadata,
        "version_table": migration.version_table,
        "version_table_schema": migration.version_table_schema,
        "include_schemas": _uses_named_schemas(),
        "include_name": include_name,
        "include_object": include_object,
        "compare_type": True,
        "compare_server_default": True,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        **_configure_kwargs(),
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config = context.config
    connection = config.attributes.get("connection")
    if connection is not None:
        apply_mainsequence_migration_role(connection, config)
        context.configure(connection=connection, **_configure_kwargs())
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        apply_mainsequence_migration_role(connection, config)
        context.configure(connection=connection, **_configure_kwargs())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
