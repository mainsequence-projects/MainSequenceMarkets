---
name: mainsequence-markets-metatable-migrations
description: Use this skill when an ms-markets project extension needs SDK-managed MetaTable migration wiring. MetaTable migrations are handled by mainsequence-sdk; this skill only covers project table/spec refresh through after_register_metatables.
---

# Main Sequence Markets MetaTable Migration Extensions

MetaTable migrations are handled by `mainsequence-sdk`.

Use the SDK migration system for schema changes and MetaTable registration:

- `mainsequence.meta_tables.migrations.AlembicMetaTableMigration`
- `mainsequence.meta_tables.migrations.build_alembic_version_metatable`
- `mainsequence.meta_tables.migrations.build_metatable_migration_provider`
- `mainsequence.meta_tables.migrations.build_metatable_model_registry`
- `mainsequence.meta_tables.migrations.metadata_for_models`
- `mainsequence.meta_tables.migrations.run_mainsequence_alembic_env`
- the SDK MetaTable migration CLI
- the SDK migration tutorial and knowledge docs
- the project-local SDK migration provider, when the project defines one

This skill does not own schema migration commands, migration engines, registry
rows, DDL apply behavior, or built-in ms-markets table registration.

## Core Rule

The default path is the SDK helper/scaffold path. Do not hand-roll namespace
slugging, Alembic version-table subclasses, provider model dedupe, Alembic
`env.py` online/offline boilerplate, or revision templates in ms-markets.

The only ms-markets-specific extension point here is
`after_register_metatables`.

Use `after_register_metatables` only when the project defines project tables
that need project table specs refreshed after SDK MetaTable registration.

Do not add built-in ms-markets tables to `after_register_metatables`.

Do not add project table specs when the project does not define project tables.

## Read First

Before changing project extension migration wiring, inspect:

1. `mainsequence-sdk/docs/tutorial/metatable_migrations.md`
2. `mainsequence-sdk/docs/knowledge/meta_tables/migrations.md`
3. `mainsequence-sdk/mainsequence/meta_tables/migrations.py`
4. the project-local `AlembicMetaTableMigration` provider, if present
5. the project code that defines project table specs, if present

## Expected Project Pattern

The project SDK provider owns the migrated model list:

```python
from mainsequence.meta_tables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)


ProjectAlembicVersion = build_alembic_version_metatable(
    class_name="ProjectAlembicVersion",
    namespace="my-project",
    identifier="my_project.alembic_version",
    schema=None,
    table_name="my_project__alembic_version",
)

migration = build_metatable_migration_provider(
    package="my_project",
    migration_namespace="my-project",
    script_location="my_project:migrations",
    target_metadata=Base.metadata,
    alembic_registry=ProjectAlembicVersion,
    metatable_models=[
        ProjectMarketTable,
    ],
    after_register_metatables=refresh_project_market_specs,
)
```

`refresh_project_market_specs` should refresh only specs for project tables
registered by that provider.

It must not register built-in ms-markets tables, infer the built-in model graph,
or mutate schema. The SDK provider already owns schema work.

## Review Checklist

- The provider is an SDK `AlembicMetaTableMigration`.
- Provider construction uses SDK helpers unless a documented SDK helper gap
  requires a direct constructor.
- Project tables are listed in the project provider.
- Default PostgreSQL `public` tables are authored as `schema=None`, not
  `schema="public"`.
- Generated revisions with unchanged FK drop/create churn from `None` versus
  `public` schema mismatch are rejected.
- `after_register_metatables` is present only when project table specs need
  refresh.
- The hook handles project tables/specs only.
- Built-in ms-markets tables are not added to the hook.
- No project table spec is added when the project has no project tables.
