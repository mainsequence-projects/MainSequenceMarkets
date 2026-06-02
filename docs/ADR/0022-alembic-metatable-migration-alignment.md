# 0022. Thin Alembic MetaTable Migration Integration

## Status

Accepted

## Context

ADR 0020 designed a project-owned MetaTable migration runner for `ms-markets`.
ADR 0022 initially narrowed that design to Alembic-rendered SQL, but it still
assigned too much orchestration to this project.

The SDK migration machinery now owns the provider-based Alembic workflow. The
current SDK source and SDK migration docs expose:

- `AlembicMetaTableMigration`;
- `AlembicVersionMetaTable`;
- `load_alembic_metatable_migration_provider(...)`;
- `render_packaged_alembic_migration_for_provider(...)`;
- `resolve_alembic_revision_metadata(...)`;
- `AlembicMigrationOperation`;
- `AlembicMigrationStatusRequest`;
- `MetaTable.apply_migration(...)`;
- `MetaTable.get_migration_status(...)`;
- SDK CLI commands under `mainsequence migrations`.

The SDK CLI already provides:

```text
mainsequence migrations register-version-table
mainsequence migrations current
mainsequence migrations revision
mainsequence migrations render
mainsequence migrations upgrade
```

The project should not reimplement that machinery. The `ms-markets` integration
should be small and package-specific.

## Current Project Machinery

Before this ADR, the project had an obsolete custom migration implementation in
`src/msm/maintenance/migrations.py`.

It loads modules from:

```text
src/msm/migrations/versions/
```

The current initial module is:

```text
src/msm/migrations/versions/v0001_initial.py
```

That file is not an Alembic revision. It declares `REVISION`,
`EXPECTED_CURRENT_REVISION`, `affected_models()`, and `operations()`. The
`operations()` function emits project-authored `add_column` dictionaries.

That implementation is wrong for the new SDK for three reasons:

1. The SDK no longer uses custom operation dictionaries as the migration
   language.
2. The SDK no longer stores package migration rows in an SDK `MigrationMetaTable`.
3. The initial migration must create tables through Alembic DDL, not add columns
   to missing tables.

The current `MarketsMigrationTable` declaration in
`src/msm/maintenance/models.py` is also obsolete because it imports the old SDK
`MigrationMetaTable`. The new state binding is `AlembicVersionMetaTable`.

## SDK Migration Shape

The SDK migration lifecycle is provider-based:

```text
AlembicMetaTableMigration provider
-> Alembic revision from provider.target_metadata
-> Alembic renders SQL from provider.script_location
-> SDK sends the SQL artifact to TS Manager
-> TS Manager executes SQL and updates Alembic's version table
-> project tooling registers or refreshes provider.metatable_models
```

The SDK owns:

- provider loading and validation;
- Alembic config construction;
- revision generation;
- SQL rendering;
- dry-run/apply request construction;
- backend status reads;
- version-table binding registration;
- optional post-apply MetaTable registration through
  `migration.register_metatables(...)`.

The backend apply request contains Alembic-rendered SQL and manifest metadata.
It does not contain:

- custom SDK schema operations;
- affected-table operation lists;
- old/new contract hashes;
- migration-row UIDs;
- project-owned migration ledger rows.

## Decision

`ms-markets` will stop owning a migration engine.

`ms-markets` will provide a small SDK-compatible migration provider and package
Alembic environment. Migration execution will use the SDK provider workflow and
SDK CLI.

The repository has three import packages with MetaTables:

```text
msm
msm_portfolios
msm_pricing
```

They are handled by one migration provider, not three. They share the same
`MarketsBase.metadata`, the same Alembic script location, the same physical
Alembic version table, and the same `ms-markets` revision graph.

There must not be separate providers such as:

```text
msm_portfolios.migrations:migration
msm_pricing.migrations:migration
```

unless those packages are split into independently installed distributions with
independent schema lifecycles.

The preferred operational command shape is:

```text
mainsequence migrations current --provider msm.migrations:migration
mainsequence migrations revision --provider msm.migrations:migration --autogenerate -m "..."
mainsequence migrations render --provider msm.migrations:migration --to head
mainsequence migrations upgrade --provider msm.migrations:migration --to head --dry-run
mainsequence migrations upgrade --provider msm.migrations:migration --to head
```

`msm` will not keep a migration command group. `msm migrations current`,
`msm migrations sync`, `msm migrations upgrade`, `msm migrations validate`, and
any other `msm migrations ...` subcommands must be removed. There will be no
compatibility alias, no wrapper that prints equivalent commands, and no
project-owned migration CLI surface.

## Provider Contract

`ms-markets` should define one provider object at:

```text
src/msm/migrations/__init__.py
```

The provider reference is:

```text
msm.migrations:migration
```

Use an explicit provider reference because the distribution name is
`ms-markets`, while the import package is `msm`. SDK package-name inference would
look for `ms_markets.migrations:migration`, which is not this package.

Target shape:

```python
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    AlembicVersionMetaTable,
)

from msm.base import MARKETS_SCHEMA, MarketsBase
from msm.migrations.registry import migration_model_registry
from msm.settings import markets_namespace


class MarketsAlembicVersion(AlembicVersionMetaTable):
    __metatable_namespace__ = "msm"
    __metatable_identifier__ = "msm.alembic_version"
    __alembic_version_schema__ = MARKETS_SCHEMA
    __alembic_version_table_name__ = "msm_alembic_version"
    __alembic_version_column_name__ = "version_num"


migration = AlembicMetaTableMigration(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="msm:migrations",
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=migration_model_registry(),
    after_register_metatables=refresh_markets_catalog_from_registered_metatables,
)
```

The package model registry remains useful, but only as provider scope. It tells
the SDK which SQLAlchemy MetaTable models belong to this migration stream.
It is not migration history.

The provider's model registry must include the combined `msm`,
`msm_portfolios`, and `msm_pricing` MetaTable graph:

```python
def migration_model_registry() -> list[type[MarketsBase]]:
    return dedupe_in_dependency_order(
        [
            *markets_sqlalchemy_models(),
            *portfolio_sqlalchemy_models(),
            *pricing_sqlalchemy_models(),
        ]
    )
```

`msm_portfolios` and `msm_pricing` include some core `msm` dependency models,
such as `IndexTable` or `AssetTable`. The combined registry must de-duplicate by
model identity and logical MetaTable identifier so Alembic, SDK registration,
and catalog refresh see each managed table once.

The physical Alembic version table is package-specific:

```text
public.msm_alembic_version
```

This avoids collisions with other independent providers in the same database.
Projects that use or inherit the `ms-markets` migration provider should use this
same version table for the `ms-markets` revision graph. They should only define
a different Alembic version table when they create a separate independent
provider with its own revision graph.

## Alembic Environment

`src/msm/migrations/` should become a standard Alembic script location:

```text
src/msm/migrations/
  __init__.py
  env.py
  versions/
```

The `versions/` directory is where the SDK/Alembic CLI writes generated
revision files. `ms-markets` should not hand-create `0001_initial.py` or any
other migration operation file as part of the integration work.

`env.py` should delegate to the selected provider:

```python
from alembic import context

from msm.migrations import migration


def include_name(name, type_, parent_names):
    return migration.include_name(name, type_, parent_names)


def run_migrations_offline():
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=migration.target_metadata,
        version_table=migration.version_table,
        version_table_schema=migration.version_table_schema,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_offline()
```

The revision files are normal Alembic Python revisions. They must use Alembic
operations such as `op.create_table(...)`, `op.add_column(...)`, and
`op.create_index(...)`. They must not define custom `OPERATIONS` lists or SDK
operation dictionaries. Those files are produced by
`mainsequence migrations revision --provider msm.migrations:migration ...`, not
by a custom `ms-markets` migration generator.

## Data Source Boundary

The SDK provider supports explicit `data_source_uid` overrides for cross-data-
source workflows, but the normal `ms-markets` workflow should not ask users to
pass a data source UID through `msm`.

The provider should rely on the SDK's binding path:

- `mainsequence migrations register-version-table` registers the provider's
  `AlembicVersionMetaTable`;
- the provider's registry class stores the MetaTable UID and data source UID;
- SDK status/apply calls use `migration.resolve_data_source_uid()`.

If a local project environment genuinely needs an override, that should use the
SDK CLI's explicit option, not a new `msm`-specific mechanism.

## Catalog Integration

The SDK synchronizes provider-scoped MetaTables after a successful apply with:

```text
mainsequence migrations upgrade --provider msm.migrations:migration --to head
```

`ms-markets` still has one package-specific responsibility: keep
`MarketsMetaTableCatalogTable` aligned with the registered provider models so
runtime startup can attach from the catalog.

That catalog work will be automatic through the SDK provider hook:

```python
after_register_metatables=refresh_markets_catalog_from_registered_metatables
```

The hook runs after the SDK applies the migration and synchronizes
`migration.metatable_models` through `migration.sync_metatable_catalog(...)`.
It is not part of SQL execution and does not
create a separate `msm migrations` command surface.

The hook should:

1. iterate `migration.metatable_models`;
2. pair each model with the SDK-registered or refreshed MetaTable;
3. compute the current contract hash through existing catalog helpers;
4. upsert `MarketsMetaTableCatalogTable`;
5. fail if an expected provider model cannot be registered, resolved, or
   validated.

The catalog should not record Alembic revision history. Alembic's version table
is the schema revision state.

## Runtime Startup

`msm.start_engine(...)` remains attach-only.

Runtime startup may validate:

- expected catalog rows exist;
- catalog contract hashes match the current models.

Runtime startup must not:

- generate Alembic revisions;
- render SQL;
- apply SQL;
- register the Alembic version table;
- register application MetaTables as a side effect of normal API/DataNode use.

## Implementation Tasks

### Phase 1. Delete The Obsolete Project Runner

- [x] Remove `MigrationSpec`, `MaterializedMigration`, and custom operation parsing.
- [x] Remove `_build_packaged_migration(...)`.
- [x] Remove `_sdk_migrations()` checks for old SDK names.
- [x] Remove `MarketsMigrationTable`.
- [x] Remove `sync_packaged_migration(...)` usage.
- [x] Remove old tests that assert custom operation manifests.

### Phase 2. Add The SDK Provider

- [x] Define `MarketsAlembicVersion`.
- [x] Define `migration = AlembicMetaTableMigration(...)`.
- [x] Make `migration_model_registry()` combine `msm`, `msm_portfolios`, and
  `msm_pricing` MetaTable models into one de-duplicated dependency-ordered list.
- [x] Use the combined `migration_model_registry()` as the provider's
  `metatable_models` scope.
- [x] Do not create `msm_portfolios.migrations:migration` or
  `msm_pricing.migrations:migration`.
- [x] Add tests that `msm.migrations:migration` loads with
  `load_alembic_metatable_migration_provider(...)`.
- [x] Add tests that provider `include_name(...)` excludes unrelated tables.
- [x] Add tests that the combined provider registry includes portfolio and
  pricing MetaTables once, without duplicate core dependency models.

### Phase 3. Add Standard Alembic Files

- [x] Add `src/msm/migrations/env.py`.
- [x] Add `src/msm/migrations/script.py.mako` so Alembic can write generated
  revision modules.
- [x] Delete the legacy custom `src/msm/migrations/versions/v0001_initial.py`.
- [x] Keep `src/msm/migrations/versions/` as the generated Alembic revision output
  directory.
- [x] Do not hand-author an initial revision as an implementation task.
- [x] Document that the SDK revision command creates revision files.
- [x] Ensure Alembic version-table settings come from `MarketsAlembicVersion`.
- [x] Ensure Alembic environment and revision files are included in wheels and source
  distributions.

### Phase 4. Replace CLI Behavior

- [x] Delete the `migrations` command group from the `msm` CLI.
- [x] Delete `msm migrations current`.
- [x] Delete `msm migrations sync`.
- [x] Delete `msm migrations upgrade`.
- [x] Delete `msm migrations validate`.
- [x] Do not add compatibility aliases.
- [x] Do not add a wrapper that prints equivalent `mainsequence migrations`
  commands.
- [x] Document the SDK CLI as the only migration command surface.

### Phase 5. Add Minimal Catalog Finalization

- [x] Add a small function that refreshes `MarketsMetaTableCatalogTable` from
  provider-scoped registered MetaTables.
- [x] Wire it into the SDK provider through
  `after_register_metatables=refresh_markets_catalog_from_registered_metatables`.
- [x] Let the SDK call it automatically after a successful `upgrade`.
- [x] Keep runtime bootstrap dependent on catalog state, not responsible for writing
  it.

### Phase 6. Update Documentation And Tests

- [x] Rewrite `docs/knowledge/msm/migrations/` around
  `mainsequence migrations --provider msm.migrations:migration`.
- [x] Rewrite the platform migration docs that still mention SDK
  `MigrationMetaTable` or package migration rows.
- [x] Add a concise maintainer note explaining how to generate a revision and how
  to finalize catalog rows.
- [x] Add focused tests for provider loading, include filtering,
  `msm migrations` removal, and catalog refresh.
- [ ] Raise the project dependency floor to the first published SDK release that
  removes deprecated `upgrade --apply` / `upgrade --register-metatables` flags
  and applies `upgrade` by default after validation.

## Open Decisions

No open decisions remain for the initial implementation plan.

## Resolved Decisions

- Catalog refresh is automatic after SDK `upgrade` through
  the provider hook
  `after_register_metatables=refresh_markets_catalog_from_registered_metatables`.
- There is no `msm migrations` wrapper for this catalog refresh.
- The `ms-markets` provider uses the package-specific physical Alembic version
  table `public.msm_alembic_version`.
- Projects that inherit or use the `ms-markets` provider share
  `public.msm_alembic_version` for the `ms-markets` revision graph.
- `msm`, `msm_portfolios`, and `msm_pricing` are covered by one provider:
  `msm.migrations:migration`.
- There is one Alembic script location and one revision graph for the repository:
  `msm:migrations`.
- There are no existing deployed `ms-markets` tables to adopt for this initial
  implementation. The first Alembic revision is a normal generated initial
  create-schema revision.

## Success Criteria

The project is aligned with the SDK migration machinery when:

- `load_alembic_metatable_migration_provider("msm.migrations:migration")`
  loads the `ms-markets` provider;
- the loaded provider includes `msm`, `msm_portfolios`, and `msm_pricing`
  MetaTables in one de-duplicated model registry;
- no `msm_portfolios` or `msm_pricing` migration providers exist;
- `mainsequence migrations revision --provider msm.migrations:migration --autogenerate -m "..."`
  creates normal Alembic revision files;
- `mainsequence migrations render --provider msm.migrations:migration --to head`
  renders Alembic SQL;
- `mainsequence migrations upgrade --provider msm.migrations:migration --to head --dry-run`
  validates through the SDK backend apply path;
- `mainsequence migrations upgrade --provider msm.migrations:migration --to head`
  executes through SDK machinery;
- the installed SDK `mainsequence migrations upgrade --help` output does not
  expose `--apply` or `--register-metatables`;
- `MarketsMetaTableCatalogTable` is refreshed by the provider
  `after_register_metatables` hook after the SDK synchronizes provider
  MetaTables;
- `msm migrations ...` is not available;
- no project runtime code depends on `MigrationMetaTable`,
  `PackagedMetaTableMigration`, `sync_packaged_migration(...)`, or custom
  `operations()` migration modules.

## Consequences

The migration integration becomes much smaller. `ms-markets` defines scope,
metadata, package Alembic files, and catalog finalization. The SDK owns
generation, rendering, status, dry-run, apply, version-table binding, and normal
MetaTable registration.

This reduces duplicate migration code in `ms-markets` and keeps the project
aligned with the SDK's canonical migration workflow.
