---
name: mainsequence-markets-metatable-migrations
description: Use this skill when an ms-markets project extension needs MetaTables-managed migration wiring. MetaTable migrations are handled by the metatables client (mainsequence-metatable); this skill only covers project table/spec refresh through after_register_metatables.
---

# Main Sequence Markets MetaTable Migration Extensions

MetaTable migrations are handled by the MetaTables client: the
`mainsequence-metatable` distribution, imported as `metatables`. Main Sequence
SDK 9 no longer ships `mainsequence.meta_tables` or the `mainsequence
migrations` commands.

Use the application-owned MetaTables migration system for schema changes and
MetaTable registration:

- `metatables.migrations.AlembicMetaTableMigration`
- `metatables.migrations.build_alembic_version_metatable`
- `metatables.migrations.build_metatable_migration_provider`
- `metatables.migrations.build_metatable_model_registry`
- `metatables.migrations.metadata_for_models`
- `metatables.migrations.run_mainsequence_alembic_env`
- the `metatables migrations ... --provider <package>.migrations:migration` CLI
- the `metatables-migrations` and `metatables-upgrade-legacy-app` skills that
  `metatables copy-metatables-skills` installs under `.agents/skills/metatables/`
- the project-local migration provider, when the project defines one

This skill does not own schema migration commands, migration engines, registry
rows, DDL apply behavior, or built-in ms-markets table registration. Built-in
ms-markets tables are migrated by the package provider
`msm_migrations:migration` (compatibility alias `msm.migrations:migration`).

## Core Rule

The default path is the `metatables.migrations` helper/scaffold path. Do not hand-roll namespace
slugging, Alembic version-table subclasses, provider model dedupe, Alembic
`env.py` online/offline boilerplate, or revision templates in ms-markets.

The only ms-markets-specific extension point here is
`after_register_metatables`.

Use `after_register_metatables` only when the project defines project tables
that need project table specs refreshed after MetaTable registration.

Do not add built-in ms-markets tables to `after_register_metatables`.

Do not add project table specs when the project does not define project tables.

## Read First

Before changing project extension migration wiring, inspect:

1. `.agents/skills/metatables/metatables-migrations/SKILL.md` and its
   `references/docs/client/define-and-migrate-tables.md`
2. `.agents/skills/metatables/metatables-upgrade-legacy-app/SKILL.md` when the
   project still imports `mainsequence.meta_tables` or calls
   `mainsequence migrations`
3. `metatables migrations --help` for the installed client's command shape
4. the project-local `AlembicMetaTableMigration` provider, if present
5. the project code that defines project table specs, if present

Run provider commands with the project's Python provider reference, for example
`metatables --local migrations upgrade --provider my_project.migrations:migration head`.
Run `upgrade` and `downgrade` from a developer or agent session only against a
local runtime.

Hosted runtimes are migrated only by the deployment workflow's migration Job,
as `.agents/skills/metatables/metatables-migrations/SKILL.md` describes. The
ms-markets schema is migrated only by the ms-markets deployment's
`migrate-markets` Job. A project that installs ms-markets to read or write its
tables does not apply `msm_migrations:migration`; its own migration Job applies
only its own providers. Do not migrate at application startup.

Required in every Environment: the `migrate-markets` Job and the `markets-api`
release run as their own workload Users, which have no MetaTables grants until an
Organization admin runs `scripts/bootstrap_metatables_access.py` from a checkout
of the branch deployed there. The script creates the Team that owns the tables in
that Environment (`ms-markets-<environment>`), as
`.agents/skills/metatables/metatables-migrations/SKILL.md` prescribes. Without it the
Job fails with `403` `table_not_editable` or `namespace_not_writable` (`422 MetaTable
is not editable` from a MetaTables API before 0.1.27), and the API is not deployed.
Do not work around a failed migration by changing revisions or table definitions,
asking for direct table grants or running the Job as an admin. Check the Job run
logs, then have an admin run the bootstrap. `docs/releasing.md` ("MetaTables access
in each Environment") has the steps.
The MetaTables API needs no provider code, allowlist, or
`application_migration_providers` alias. Keep the provider package, namespace,
model registry, version-table binding, revision IDs, and applied revision
history when upgrading the client.

## Expected Project Pattern

The project migration provider owns the migrated model list:

```python
from metatables.migrations import (
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
    script_location="my_project.migrations:",
    version_location_prefix="my_project.migrations:versions",
    target_metadata=Base.metadata,
    alembic_registry=ProjectAlembicVersion,
    metatable_models=[
        ProjectMarketTable,
    ],
    after_register_metatables=refresh_project_market_specs,
)
```

Always pass both `script_location` and `version_location_prefix`, pointing at
the provider's own module the way
`metatables migrations scaffold --module my_project.migrations` derives them.
The client default is `migrations:versions`, which resolves to whichever
top-level `migrations` package is first on `sys.path`, including one installed
by another distribution.

`refresh_project_market_specs` should refresh only specs for project tables
registered by that provider.

It must not register built-in ms-markets tables, infer the built-in model graph,
or mutate schema. The MetaTables provider already owns schema work.

## Review Checklist

- The provider is a `metatables.migrations.AlembicMetaTableMigration`.
- The provider sets `script_location` and `version_location_prefix` inside the
  project's own package, never a bare top-level `migrations` package.
- Provider construction uses `metatables.migrations` helpers unless a
  documented helper gap requires a direct constructor.
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
