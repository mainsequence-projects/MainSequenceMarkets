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
| Application that publishes signals or portfolios through the Markets API (`msm.client`) | none: it calls the Markets API |

Prefer table `editor` for producers: namespace `editor` also allows deleting every
table in the namespace. Signal weights, portfolio weights and portfolio values are
never written with a role: they are published through the Markets API
(`SignalWeightsSeries`, `PortfolioWeightsSeries`, `PortfolioValuesSeries`, ADR 0060).
The project's own tables belong in its own namespace, which its first migration
creates (see `.agents/skills/metatables/metatables-migrations/SKILL.md`).

The other direction never exists: a Markets workload (`markets-api`,
`migrate-markets`) gets no role on a project's tables or namespace, and a project
never registers a table with Markets or sends it a table uid. Markets reads and writes
only its own tables; read `.agents/skills/ms_markets/platform/producer_boundary/SKILL.md`
before designing how a project meets it.

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

The project migration provider owns the migrated model list and targets the metadata
of the project's own declarative base:

```python
from metatables import sqlalchemy_naming_convention
from metatables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)
from msm.base import MarketsMetaTableMixin
from msm.models import IndexTable
from msm_portfolios.time_index.contract_instances import (
    configured_portfolio_rebalance_state_storage,
)
from sqlalchemy import ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class ProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    __abstract__ = True
    __metatable_namespace__ = "my-project"
    __markets_storage_app__ = "my_project"


class ProjectMarketTable(ProjectMarketsMetaTableMixin, Base):
    __markets_base_identifier__ = "MarketTable"
    __metatable_description__ = "One row per Markets Index that the project follows."

    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(IndexTable.__table__.c.unique_identifier, ondelete="RESTRICT"),
        primary_key=True,
    )


ProjectRebalanceState = configured_portfolio_rebalance_state_storage(
    instance_key="main", namespace="my-project", storage_app="my_project", base=Base
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
        ProjectRebalanceState,
    ],
    after_register_metatables=refresh_project_market_specs,
)
```

Autogenerate compares every table in `target_metadata` with the database, so that
metadata holds the project's tables and no Markets table:

- `Base` is the project's own base, never `MarketsBase`, whose metadata holds every
  Markets table. Its `MetaData` sets no `schema`: Alembic would write that schema
  onto each key to Markets.
- Every model in `metatable_models` is on `Base`, hand-written or factory-built. A
  model on another base is missing from the target, so its table is never created
  and the upgrade fails. When the target holds no table at all, MetaTables 0.1.71
  compares every table of the database, and autogenerate drops them all.
- A table that `msm.start_engine` attaches carries a Markets mixin with the
  project's own namespace and storage app, as above. It refuses a table built only
  on `PlatformManagedMetaTable`.
- A key to a Markets table passes Markets' column object, as above, or
  `ForeignKey(AssetTable.__table__.c.uid)` for a key to `uid`. SQLAlchemy resolves a
  key given as text only inside one `MetaData`, so
  `ForeignKey("ms_markets__asset.uid")` on `Base` raises `NoReferencedTableError`.
  The ms-markets instance factories key their instances by column object.
- Never copy a Markets table into that metadata, with `to_metadata` or as a `Table`
  of the same name. Autogenerate would compare the copy with the deployed table and
  drop whatever the copy lacks.
- Target `Base.metadata` itself. `metadata_for_models` copies the models' tables,
  which turns their keys back into text that does not resolve.

The revision file still holds only the physical name and key column, for example
`["ms_markets__index.unique_identifier"]`, and needs no Markets import and no include
hook.

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
- `target_metadata` is the metadata of the project's own base and holds no Markets
  table; keys to Markets pass column objects.
- Every project table, hand-written or factory-built, is on that base.
- A generated revision has operations on the project's tables only.
- Default PostgreSQL `public` tables are authored as `schema=None`, not
  `schema="public"`.
- Generated revisions with unchanged FK drop/create churn from `None` versus
  `public` schema mismatch are rejected.
- `after_register_metatables` is present only when project table specs need
  refresh.
- The hook handles project tables/specs only.
- Built-in ms-markets tables are not added to the hook.
- No project table spec is added when the project has no project tables.
