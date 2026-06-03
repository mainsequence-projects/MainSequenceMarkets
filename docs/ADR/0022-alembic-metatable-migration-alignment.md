# 0022. Thin Alembic MetaTable Migration Integration

## Status

Accepted

## Context

ADR 0020 designed a project-owned MetaTable migration runner for `ms-markets`.
That design is no longer the target architecture.

The SDK now owns the provider-based Alembic workflow. `ms-markets` should only
provide package scope, package Alembic files, and a post-upgrade catalog refresh
hook.

The current SDK migration API exposes:

- `AlembicMetaTableMigration`;
- `AlembicVersionMetaTable`;
- `load_alembic_metatable_migration_provider(...)`;
- `alembic_config_for_provider(...)`;
- `apply_mainsequence_migration_role(...)`;
- `resolve_alembic_revision_metadata(...)`;
- SDK CLI commands under `mainsequence migrations`.

The implemented SDK CLI command surface is:

```text
mainsequence migrations current
mainsequence migrations revision
mainsequence migrations upgrade
mainsequence migrations downgrade
```

The current SDK CLI does not expose:

```text
mainsequence migrations register-version-table
mainsequence migrations render
mainsequence migrations upgrade --to head
mainsequence migrations upgrade --dry-run
```

Any project docs, examples, skills, or runtime errors that mention those removed
forms are stale.

## Current Project State

The obsolete custom migration runner and old SDK migration models have been
removed from the normal runtime path. The project now exposes a provider at:

```text
src/msm/migrations/__init__.py
```

with the provider reference:

```text
msm.migrations:migration
```

The provider is broadly aligned with the SDK:

- it uses `AlembicMetaTableMigration`;
- it defines a package-specific `AlembicVersionMetaTable`;
- it uses one combined provider model scope for `msm`, `msm_portfolios`, and
  `msm_pricing`;
- it wires `after_register_metatables` to refresh the markets catalog.

The project is not fully current yet:

1. `src/msm/migrations/env.py` does not call
   `apply_mainsequence_migration_role(connection, config)` before Alembic runs.
2. `src/msm/migrations/versions/` has no source Alembic revision file. A
   `__pycache__/v0001_initial...pyc` file is not migration history.
3. `src/msm/maintenance/catalog.py` still reports the old
   `mainsequence migrations upgrade --provider msm.migrations:migration --to head`
   command.
4. Project docs, tutorials, examples, and skills still reference removed command
   forms such as `register-version-table`, `render`, `--to head`, and
   `--dry-run`.
5. `msm.start_engine(...)` is attach-only, but it still exposes old
   creation/registration-era arguments: `data_source_uid`,
   `open_for_everyone`, `protect_from_deletion`, `introspect`, and
   `storage_hash_by_identifier`. Those arguments are also carried into runtime
   cache keys and logs even though they no longer control runtime attachment.
   They must be removed from `msm.start_engine(...)` and from wrappers that
   forward into it.
6. Several row API helpers are still named `create_schemas()`, although they now
   attach to an already-migrated runtime instead of creating schemas.
   That name is misleading under the new architecture and must not remain the
   primary row API bootstrap name.

## Decision

`ms-markets` will not own a migration engine.

`ms-markets` will provide one SDK-compatible Alembic provider and one package
Alembic script location. Migration execution will use the SDK provider workflow
and SDK CLI.

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

The operational command shape is:

```text
mainsequence migrations current --provider msm.migrations:migration
mainsequence migrations revision --provider msm.migrations:migration --autogenerate -m "..."
mainsequence migrations upgrade --provider msm.migrations:migration head
mainsequence migrations downgrade --provider msm.migrations:migration <revision>
```

`msm` will not keep a migration command group. `msm migrations current`,
`msm migrations sync`, `msm migrations upgrade`, `msm migrations validate`, and
any other `msm migrations ...` subcommands must remain deleted. There will be no
compatibility alias, no wrapper that prints equivalent commands, and no
project-owned migration CLI surface.

## SDK Migration Flow

The SDK migration lifecycle is provider-based and uses Alembic directly:

```text
AlembicMetaTableMigration provider
-> SDK ensures the Alembic version table MetaTable is registered
-> SDK prepares and binds provider MetaTables for Alembic
-> SDK requests a scoped migration connection from the backend
-> Alembic autogenerates or executes revisions through that connection
-> Alembic updates the provider's version table
-> SDK refreshes provider.metatable_models with create_table=false
-> SDK calls provider.after_register_metatables
```

The SDK owns:

- provider loading and validation;
- Alembic config construction;
- revision generation;
- scoped migration connection acquisition;
- migration owner role propagation;
- direct Alembic `current`, `revision`, `upgrade`, and `downgrade` execution;
- version-table binding registration;
- post-upgrade MetaTable refresh through
  `migration.refresh_metatable_catalog(...)`.

The backend does not receive a project-authored SQL artifact from `ms-markets`.
It provides the scoped migration credential and backend-bound MetaTable
contracts. Alembic remains the migration engine and owns the revision files.

The migration path does not contain:

- custom SDK schema operations;
- affected-table operation lists;
- old/new contract hashes;
- migration-row UIDs;
- project-owned migration ledger rows;
- project-generated SQL render artifacts.

## Provider Contract

`ms-markets` defines one provider object at:

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
```

The provider model scope remains useful, but only as provider scope. It tells
the SDK which SQLAlchemy MetaTable models belong to this migration stream. It is
not migration history and not a project migration engine.

The registry naming must reflect that boundary. `MIGRATION_MODEL_REGISTRY` and
`migration_model_registry()` preserve the old mental model that `ms-markets`
owns a migration engine. They must be renamed to provider-scope terms such as
`METATABLE_PROVIDER_MODELS` and `metatable_provider_models()`.

The provider's model scope must include the combined `msm`, `msm_portfolios`,
and `msm_pricing` MetaTable graph. It must de-duplicate by model identity and
logical MetaTable identifier so Alembic, SDK registration, and catalog refresh
see each managed table once.

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

`src/msm/migrations/` is a standard Alembic script location:

```text
src/msm/migrations/
  __init__.py
  env.py
  script.py.mako
  versions/
```

The `versions/` directory is where the SDK/Alembic CLI writes generated revision
files. `ms-markets` should not hand-create SDK operation dictionaries, but it
must commit real Alembic Python revision files. A package with no source
revision files has no Alembic migration history.

`env.py` must delegate to the selected provider and apply the SDK migration owner
role on online connections:

```python
from alembic import context
from sqlalchemy import engine_from_config, pool

from mainsequence.meta_tables.migrations import apply_mainsequence_migration_role

from msm.migrations import migration as default_migration


def _migration_provider():
    return (
        context.config.attributes.get("mainsequence_migration_provider")
        or default_migration
    )


def include_name(name, type_, parent_names):
    return _migration_provider().include_name(name, type_, parent_names)


def include_object(object_, name, type_, reflected, compare_to):
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
        "include_name": include_name,
        "include_object": include_object,
        "compare_type": True,
        "compare_server_default": True,
    }


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
```

Offline mode is not the normal `ms-markets` migration path because the SDK
workflow depends on backend preparation and a scoped migration connection.

The revision files are normal Alembic Python revisions. They must use Alembic
operations such as `op.create_table(...)`, `op.add_column(...)`, and
`op.create_index(...)`. They must not define custom `OPERATIONS` lists or SDK
operation dictionaries. Those files are produced by
`mainsequence migrations revision --provider msm.migrations:migration ...`, not
by a custom `ms-markets` migration generator.

## Initial Baseline

Alembic cannot infer migration history from registered MetaTable rows alone. A
registered backend MetaTable can help the SDK bind physical names before Alembic
autogenerate or upgrade, but Alembic still needs source revision files and an
Alembic version table row to know what has been applied.

For a fresh database, the project should generate and commit a normal initial
revision:

```text
mainsequence migrations revision --provider msm.migrations:migration --autogenerate -m "initial"
mainsequence migrations upgrade --provider msm.migrations:migration head
```

For an environment where the physical tables already exist, the correct baseline
is not to run a create-table revision against existing tables. The project needs
a fake-applied/stamp flow using the same SDK provider preflight and scoped
connection, so Alembic records the baseline revision without executing duplicate
DDL. Until the SDK exposes a supported `mainsequence migrations stamp ...`
command or equivalent API, already-created environments remain a migration
adoption gap and must not be treated as fully current.

## Data Source Boundary

The normal `ms-markets` runtime should not ask users to pass a data source UID
through `msm.start_engine(...)`.

The provider relies on SDK preflight:

- the SDK ensures the provider's `AlembicVersionMetaTable` is registered;
- the provider registry class stores the MetaTable UID and data source UID;
- the SDK prepares provider-scoped MetaTables and binds backend physical names;
- the SDK requests a scoped migration connection through the resolved data
  source;
- Alembic runs through that scoped connection.

If a local project environment genuinely needs a data-source override, that
belongs in SDK migration/provider configuration, not in `msm` runtime bootstrap.

## Catalog Integration

The SDK refreshes provider-scoped MetaTables after a successful Alembic upgrade
with:

```text
mainsequence migrations upgrade --provider msm.migrations:migration head
```

`ms-markets` still has one package-specific responsibility: keep
`MarketsMetaTableCatalogTable` aligned with the registered provider models so
runtime startup can attach from the catalog.

That catalog work is automatic through the SDK provider hook:

```python
after_register_metatables=refresh_markets_catalog_from_registered_metatables
```

The hook runs after Alembic upgrade and after the SDK refreshes
`migration.metatable_models` through `migration.refresh_metatable_catalog(...)`
with `create_table=false`. It is not part of SQL execution and does not create a
separate `msm migrations` command surface.

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
- apply SQL;
- register the Alembic version table;
- register application MetaTables as a side effect of normal API/DataNode use.

Runtime bootstrap arguments must reflect this boundary. Arguments that imply
creation, registration, storage naming, or introspection do not belong on
`msm.start_engine(...)`.

The following arguments must be removed from the `msm.start_engine(...)` public
signature, runtime cache key, and logs:

```text
data_source_uid
open_for_everyone
protect_from_deletion
introspect
storage_hash_by_identifier
```

Wrappers such as `msm_portfolios.start_engine(...)` must not expose or forward
those arguments either. They belong to SDK migration/provider setup, not runtime
attachment.

Row API bootstrap names must reflect the same boundary. Public helpers named
`create_schemas()` imply that row APIs create or migrate MetaTables, which is
false. Those helpers must be renamed toward `start_engine(...)`,
`attach_schemas(...)`, or another attach/runtime term. A temporary
`create_schemas()` compatibility alias is acceptable only if it is explicitly
deprecated and not used in docs, tutorials, examples, or skills.

## Project Extension Tables

Project extension tables are not built-in `ms-markets` tables.

If a downstream project defines its own project tables, migration/provider
ownership remains SDK-side. The project should add only those project table specs
to its own `after_register_metatables` hook when catalog/spec refresh is needed.
It should not add built-in `ms-markets` tables to project extension hooks.

## Implementation Tasks

### Completed

- [x] Remove the obsolete project migration runner and custom operation parsing.
- [x] Remove old SDK migration model usage from the normal runtime path.
- [x] Define `MarketsAlembicVersion`.
- [x] Define `migration = AlembicMetaTableMigration(...)`.
- [x] Use one provider for `msm`, `msm_portfolios`, and `msm_pricing`.
- [x] Keep `msm_portfolios.migrations:migration` and
  `msm_pricing.migrations:migration` absent.
- [x] Add standard Alembic `env.py` and `script.py.mako`.
- [x] Delete the legacy custom `src/msm/migrations/versions/v0001_initial.py`.
- [x] Delete the `msm migrations ...` command group.
- [x] Wire catalog refresh through
  `after_register_metatables=refresh_markets_catalog_from_registered_metatables`.

### Required To Make The Project Current

- [ ] Update `src/msm/migrations/env.py` to call
  `apply_mainsequence_migration_role(connection, config)` before Alembic
  configures each online connection.
- [ ] Generate and commit real source Alembic revision files under
  `src/msm/migrations/versions/`; do not leave only `__pycache__`.
- [ ] Update `src/msm/maintenance/catalog.py` so runtime errors point to
  `mainsequence migrations upgrade --provider msm.migrations:migration head`.
- [ ] Remove `register-version-table`, `render`, `--to head`, and `--dry-run`
  command references from project docs, tutorials, examples, and skills.
- [ ] Update docs and skills so the only migration command surface is the SDK
  `mainsequence migrations current|revision|upgrade|downgrade` surface.
- [ ] Rename `MIGRATION_MODEL_REGISTRY` / `migration_model_registry()` to
  provider-scope names such as `METATABLE_PROVIDER_MODELS` /
  `metatable_provider_models()`.
- [ ] Remove stale `msm.start_engine(...)` arguments that are not consumed by
  runtime attachment: `data_source_uid`, `open_for_everyone`,
  `protect_from_deletion`, `introspect`, and `storage_hash_by_identifier`.
  Remove them from the public signature, runtime cache key, logs, and any
  wrappers that forward into `msm.start_engine(...)`.
- [ ] Rename row API `create_schemas()` helpers because they now attach an
  already-migrated runtime instead of creating schemas. Any remaining
  `create_schemas()` symbol must be an explicitly deprecated compatibility
  alias, not the documented or preferred API.
- [ ] Update bootstrap docs and skills so `msm.start_engine(...)` is described as
  runtime attachment only.
- [ ] Decide whether the current target environments are fresh or already contain
  physical `ms-markets` tables.
- [ ] For fresh environments, generate and apply the initial Alembic revision
  with the SDK CLI.
- [ ] For existing physical tables, use a supported SDK fake-applied/stamp flow
  before treating the environment as current.
- [ ] If the SDK does not expose that stamp flow yet, add or request it in the
  SDK instead of inventing an `msm` migration command surface.
- [ ] Raise the project dependency floor to the first published SDK release that
  includes the direct Alembic scoped-connection migration CLI.

## Open Decisions

- Existing-table adoption requires a supported fake-applied/stamp path through
  the SDK provider preflight and scoped migration connection. The current project
  should not claim this is solved until that command/API exists and has been run
  where needed.

## Resolved Decisions

- Catalog refresh is automatic after SDK `upgrade` through the provider hook
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
- Source Alembic revision files are required. Backend MetaTable registrations
  alone do not create Alembic migration history.

## Success Criteria

The project is aligned with the SDK migration machinery when:

- `load_alembic_metatable_migration_provider("msm.migrations:migration")`
  loads the `ms-markets` provider;
- the loaded provider includes `msm`, `msm_portfolios`, and `msm_pricing`
  MetaTables in one de-duplicated model scope;
- no `msm_portfolios` or `msm_pricing` migration providers exist;
- `mainsequence migrations revision --provider msm.migrations:migration --autogenerate -m "..."`
  creates normal Alembic revision files;
- source Alembic revision files exist under `src/msm/migrations/versions/`;
- `src/msm/migrations/env.py` applies the SDK migration owner role before
  configuring online Alembic migrations;
- `mainsequence migrations upgrade --provider msm.migrations:migration head`
  executes through SDK-scoped migration credentials;
- `MarketsMetaTableCatalogTable` is refreshed by the provider
  `after_register_metatables` hook after the SDK refreshes provider MetaTables;
- `msm migrations ...` is not available;
- project docs, tutorials, examples, and skills do not reference
  `register-version-table`, `render`, `--to head`, or `--dry-run`;
- runtime bootstrap docs describe `msm.start_engine(...)` as attach-only;
- `msm.start_engine(...)` no longer exposes `data_source_uid`,
  `open_for_everyone`, `protect_from_deletion`, `introspect`, or
  `storage_hash_by_identifier`;
- runtime cache keys and logs no longer include those stale creation or
  registration arguments;
- row APIs no longer present schema creation as the normal runtime path;
- no row API documents, tutorials, examples, or skills instruct users to call
  `create_schemas()`;
- any remaining `create_schemas()` symbol is explicitly deprecated and forwards
  to an attach/runtime bootstrap API;
- no project runtime code depends on `MigrationMetaTable`,
  `PackagedMetaTableMigration`, `sync_packaged_migration(...)`, or custom
  `operations()` migration modules.

## Consequences

The migration integration becomes small and explicit. `ms-markets` defines
provider scope, package Alembic files, and catalog refresh. The SDK owns
generation, scoped connection acquisition, direct Alembic execution, migration
owner role propagation, version-table binding, and provider MetaTable refresh.

This reduces duplicate migration code in `ms-markets` and keeps the project
aligned with the SDK's canonical migration workflow.
