---
name: mainsequence-markets-metatable-migrations
description: Use this skill when an ms-markets project extension needs to participate in SDK-managed MetaTable migrations. MetaTable migrations are handled by mainsequence-sdk; this skill only covers ms-markets-specific project table/spec wiring after SDK registration.
---

# Main Sequence Markets MetaTable Migration Extensions

MetaTable migrations are owned by `mainsequence-sdk`.

Use the SDK migration provider lifecycle for schema changes:

- `mainsequence.meta_tables.migrations.AlembicMetaTableMigration`
- the SDK MetaTable migration CLI
- the SDK migration tutorial and knowledge docs
- the project-local migration provider, when the project defines one

This skill does not own migration engines, migration commands, schema apply
logic, registry row sync, or built-in ms-markets table migration behavior.

## Core Rule

For ms-markets project extensions, the only ms-markets-specific migration hook is
`after_register_metatables`.

Use `after_register_metatables` only when the project defines project tables that
need ms-markets catalog/spec refresh after the SDK has registered those project
MetaTables.

Do not add built-in ms-markets tables to `after_register_metatables`.

Do not add any table spec when the project has no project-specific tables.

## Read First

Before changing project extension migration wiring, inspect:

1. `mainsequence-sdk/docs/tutorial/metatable_migrations.md`
2. `mainsequence-sdk/docs/knowledge/meta_tables/migrations.md`
3. `mainsequence-sdk/mainsequence/meta_tables/migrations.py`
4. the project-local `AlembicMetaTableMigration` provider, if present
5. the project code that defines extension table specs, if present

## Project Extension Pattern

The SDK provider owns the migrated table list:

```python
from mainsequence.meta_tables.migrations import AlembicMetaTableMigration

migration = AlembicMetaTableMigration(
    package="my_project",
    migration_namespace="my-project",
    script_location="my_project:migrations",
    target_metadata=Base.metadata,
    alembic_registry=ProjectAlembicVersion,
    metatable_models=[
        ProjectAssetDetailsTable,
    ],
    after_register_metatables=refresh_project_market_specs,
)
```

The hook should refresh only project extension specs for the project tables
registered by that provider.

It must not register built-in ms-markets tables, infer the built-in model graph,
or mutate schema. Schema work is already handled by the SDK provider.

## Review Checklist

- The migration provider is SDK-owned and uses `AlembicMetaTableMigration`.
- Project extension tables are listed in the project provider.
- `after_register_metatables` is present only when project table specs need
  refresh.
- The hook handles project tables/specs only.
- Built-in ms-markets tables are not added to the hook.
- No table spec is added when the project does not define project tables.
