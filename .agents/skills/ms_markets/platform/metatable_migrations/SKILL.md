---
name: mainsequence-markets-metatable-migrations
description: Use this skill when an ms-markets project extension needs MetaTables-managed migration wiring, or when a workload needs MetaTables roles on the `mainsequence.markets` namespace. MetaTable migrations are handled by the metatables client (mainsequence-metatable); this skill covers project table/spec refresh through after_register_metatables and the roles that the ms-markets deployment and consuming projects need.
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
- the `metatables-migrations` skill that `metatables copy-metatables-skills`
  installs under `.agents/skills/metatables/`
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
2. `.agents/skills/mainsequence/maintenance/metatables_transition/SKILL.md` when the
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

The MetaTables API needs no provider code, allowlist, or
`application_migration_providers` alias. Keep the provider package, namespace,
model registry, version-table binding, revision IDs, and applied revision
history when upgrading the client.

## MetaTables Access

Access to the ms-markets tables follows the MetaTables namespace and table roles
(MetaTables ADR 0024, copied with the MetaTables skills under
`.agents/skills/metatables/metatables-migrations/references/docs/adr/api/0024-namespace-and-table-access-roles.md`).
Every ms-markets table is in the `mainsequence.markets` namespace, and a role on the
namespace covers every table in it, including tables registered later. Workloads run
as their own workload Users: they never grant roles, are never `owner`, and get no
MetaTables role from a workflow entry. The workflow's
`access.branches: [{repository: MetaTables, policy: reader}]` only lets them find the
Environment's MetaTables API.

In each Environment, the ms-markets deployment's principals hold these roles on
`mainsequence.markets`:

| Principal | Role |
| --- | --- |
| `migrate-markets` (migration Job) | `editor` |
| `markets-api` (FastAPI release) | `data_writer` |
| a person, or a Team of people only | `owner` |

Where `mainsequence.markets` predates roles, an Organization admin granted its first
owner once, and its owners grant every other role. In an Environment where it does
not exist yet, the first `migrate-markets` run creates it and gets `editor`; the
people who manage that Job then grant the API `data_writer` and an owner. Nobody
creates the namespace before the push.

A workload without a role can't see the tables: `msm.start_engine` then fails at
startup because they look unregistered, so that workload's rollout fails and only
the next push deploys it.

A project that installs ms-markets and uses these tables asks an owner of
`mainsequence.markets` for the smallest role each of its workloads needs, in each
Environment. Ask before the project's push when the workload already exists. A
workload the push creates gets its role right after it, and the next push deploys
it if it attaches the tables at startup.

| Consumer workload | Role on `mainsequence.markets` |
| --- | --- |
| Migration Job that registers its own tables in `mainsequence.markets` | `editor` on the namespace |
| Updater producer that writes an ms-markets table | table `editor` on each output table, plus `data_viewer` on the namespace for its inputs |
| Row writer (asset or OpenFIGI registration, categories, calendars, Index rows) | `data_writer` |
| Reader | `data_viewer` |

Prefer table `editor` for producers: namespace `editor` also allows deleting every
table in the namespace. The project's own tables belong in its own namespace, which
its first migration creates (see `.agents/skills/metatables/metatables-migrations/SKILL.md`).

Refusals name what is missing:

- `namespace_access_required` (403) when a migration Job registers into
  `mainsequence.markets`: the Job's workload User (`caller_user_uid`) lacks
  `tables.create` there, for example after the platform recreated the Job. An owner
  grants it `editor`, then the Job runs again.
- `table_not_editable`: the caller lacks `tables.update` on an existing table. An
  owner of the table or of the namespace grants `editor`.
- A refused row read or write in a running workload: it lacks `data_viewer` or
  `data_writer`. Its requests succeed from the next one after the grant, with no
  redeployment.

Do not work around a refusal by changing revisions, table definitions or physical
names, by putting grants in a Job or in application code, or by running the Job as an
Organization admin. Check the Job run logs, then ask an owner of
`mainsequence.markets` for the role. "MetaTables access in each Environment" in the
ms-markets `docs/releasing.md` lists the grants for its own deployment.

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
