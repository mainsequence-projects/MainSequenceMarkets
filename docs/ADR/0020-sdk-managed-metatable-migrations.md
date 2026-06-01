# 0020. SDK-Managed MetaTable Migrations

## Status

Accepted

## Context

ADR 0015 moved `ms-markets` startup to an explicit catalog-based bootstrap, but
it intentionally did not design a schema migration engine. The current behavior
is no longer enough: when authored SQLAlchemy MetaTable contracts change, startup
can detect stale catalog rows and stale physical storage, but it cannot apply the
DDL, refresh the platform MetaTable contract, update the `ms-markets` catalog,
and continue safely.

The Main Sequence SDK now has a MetaTable migration engine. The SDK design is a
client-defined migration registry workflow, not a direct Alembic runtime and not
a direct database executor:

- migration artifacts are packaged by the client package;
- the client package stores migration rows in a registered
  `MigrationMetaTable`;
- the migration apply request references a registry row;
- TS Manager reads the registry row, validates checksums and contract hashes,
  locks the migration stream, executes the migration plan, refreshes affected
  MetaTables, and updates migration status.

The local SDK checkout verified for this ADR exposes:

- `MetaTable.apply_migration(...)`;
- `MetaTable.get_migration_status(...)`;
- `mainsequence.meta_tables.migrations.MigrationMetaTable`;
- `load_packaged_migration(...)`;
- `sync_packaged_migration(...)`;
- `build_migration_operation(...)`;
- `apply_migration(...)`;
- `get_migration_status(...)`;
- `metatable-migration.v1` request and response models.

The project dependency declaration must target the SDK release or local SDK
build that contains the migration API. The active implementation target verified
for this ADR is SDK `4.1.15`.

## Decision

`ms-markets` will consume the SDK MetaTable migration engine instead of defining
its own platform migration protocol.

There will be no direct database executor in `ms-markets`. There will also be no
new `MetaTable.execute_migration(...)` API proposed by this project ADR. The SDK
API shape to use is:

```python
from mainsequence.client.models_metatables import MetaTable
from mainsequence.meta_tables.migrations import (
    MigrationMetaTable,
    apply_migration,
    get_migration_status,
    load_packaged_migration,
    sync_packaged_migration,
)
```

The runtime apply call is:

```python
result = apply_migration(migration_meta_table, registry_row, dry_run=False)
```

or equivalently:

```python
result = MetaTable.apply_migration(operation)
```

Status reads use:

```python
status = get_migration_status(
    migration_meta_table,
    package="msm",
    migration_namespace=markets_namespace,
)
```

### SDK Shape To Consume

The SDK migration row is the source of migration execution data. The fields
`ms-markets` must populate and consume include:

- `package`;
- `migration_namespace`;
- `revision`;
- `target_data_source_uid`;
- `expected_current_revision`;
- manifest payload and `manifest_sha256`;
- structured operation payloads and `operations_sha256`;
- affected table identifiers;
- old and new contract hashes;
- new contract payloads;
- idempotency and lock keys;
- status, started/finished timestamps, execution counts, introspection
  snapshots, and failure details.

The apply request does not send raw executable SQL directly. It sends
`migration_meta_table_uid` and `migration_row_uid`, and the backend reads the
registered migration row, validates its structured operations and checksums, and
executes the backend migration plan. SDK fields for SQL text, `sql_sha256`, or
statement boundaries are an alternate SDK surface; `ms-markets` package
migrations must not use hand-authored SQL files as their source of truth.

The migration stream is keyed by:

```text
(data_source_uid, package, migration_namespace)
```

The migration unit is not a single MetaTable. A revision can affect one table,
many tables, the catalog table, or a relationship between tables. Per-table
state is diagnostic data carried by the manifest and response, not the primary
revision graph.

### `ms-markets` Registry

`ms-markets` will define a package-owned registry table by subclassing the SDK
`MigrationMetaTable`.

Target declaration shape:

```python
class MarketsMigrationTable(MigrationMetaTable, MarketsBase):
    __metatable_namespace__ = "msm"
    __metatable_identifier__ = "markets_migrations"
    __metatable_description__ = (
        "Packaged ms-markets MetaTable schema migrations and run state."
    )
```

The registry itself is a normal platform-managed MetaTable. It should be
registered before applying package migrations because SDK apply operations
reference rows in that registry.

The project does not need a separate `MarketsSchemaMigrationTable`; the SDK
`MigrationMetaTable` registry is the migration ledger.

### Package Migration Registry

`ms-markets` needs a package-owned migration registry that defines the universe
of library-owned MetaTables that participate in the schema lifecycle. This is
the equivalent of Django's `INSTALLED_APPS`: it tells migration commands which
models are managed by the package.

This registry is source code, not migration history. It should live beside the
migration runner and contain SQLAlchemy model classes:

```python
MIGRATION_MODEL_REGISTRY = [
    AssetTypeTable,
    AssetTable,
    IndexTable,
    AccountTable,
]
```

The registry answers:

- which MetaTables `msm` owns;
- which models `msm migrations current` must check;
- which models migration commands must consider;
- which models can be referenced by migration modules;
- which catalog rows are expected to exist after migrations are finalized.

The SDK `MigrationMetaTable` registry is different. It is the applied migration
ledger and stores migration rows/status in the platform. The package model
registry is the local source of managed table scope.

### Migration Modules And Runtime Manifest Materialization

`ms-markets` will package Python migration modules as importable resources:

```text
src/msm/migrations/
  registry.py
  versions/
    v0002_add_asset_column.py
```

Alembic may still be used during development to reason about schema changes, but
`ms-markets` does not ship or maintain separate Alembic/SQL migration files for
the runtime path. Runtime execution goes through the SDK migration registry
workflow. `ms-markets` must not instantiate an Alembic database connection at
runtime.

Each Python migration module should define the revision metadata and affected
models, plus the structured SDK migration operations:

```python
REVISION = "0002_add_asset_column"
EXPECTED_CURRENT_REVISION = "0001_initial"
MIGRATION_NAMESPACE = "markets"
AFFECTED_MODELS = [AssetTable]
OPERATIONS = [
    {
        "op": "add_column",
        "table_identifier": "Asset",
        "column": {"name": "status", "data_type": "str", "nullable": True},
    }
]
OLD_CONTRACT_HASHES = {"Asset": "..."}
```

At `sync` or `upgrade` time, the `ms-markets` migration runner materializes the
SDK manifest/registry-row payload as JSON from this Python metadata and the
package model registry. The SDK may store that JSON in `MarketsMigrationTable`,
but `ms-markets` does not need hand-authored YAML/JSON manifest files as the
source of truth.

The generated SDK manifest payload must include the fields required by
`metatable-migration-manifest.v1`, including upgrade revision metadata,
`expected_current_revision`, structured operation payloads, affected logical
table identifiers, old contract hashes, new contract hashes, and post-migration
contract payloads. The Python migration module is the package source of truth.

### Upgrade-Only Policy

`ms-markets` will support forward migrations only.

The package CLI will not expose a `downgrade` command or a Django-style
`migrations history` command. The SDK registry records migration rows and status
because the backend needs persisted state for idempotency, locking, checksums,
and audit. That registry is not a user-facing reversible migration history for
`ms-markets`.

If a released schema change must be corrected, the correction should be a new
forward migration. Operational rollback belongs to platform/database restore
procedures, not to an `msm` downgrade workflow.

For future migrations, old contract hashes should be stored explicitly in the
Python migration module when the old SQLAlchemy model declaration no longer
exists in the current package. New contract payloads can be computed from current
SQLAlchemy models where practical.

### Migration Scope And Table Discovery

The tables that enter the migration lifecycle are defined by the package
migration registry and migration modules. They are not discovered
opportunistically from the database by `msm migrations current`.

For core `msm`, `MIGRATION_MODEL_REGISTRY` is the managed-table scope. It may be
derived from the existing model resolver, but migration commands need a stable,
explicit registry so they can determine what the package manages without asking
the database to define scope.

For each migration revision, the Python migration module's `AFFECTED_MODELS`
field is the authoritative list of managed SQLAlchemy models touched by that
revision. The runner converts those models to SDK `affected_tables` entries by
using the same identifier/namespace logic as the catalog.

The generated SDK payload should contain entries shaped like:

```json
[
  {"identifier": "Asset", "namespace": "msm"},
  {"identifier": "AssetType", "namespace": "msm"}
]
```

Optional `meta_table_uid` and `physical_table_name` values are hints for
adoption or repair-style migrations. They are not the primary identity. The
primary identity is the logical MetaTable identifier used by the package catalog
and SDK migration registry.

`msm migrations current` should determine its table scope as follows:

1. load `MIGRATION_MODEL_REGISTRY`;
2. load packaged Python migration modules for `(package="msm",
   migration_namespace)`;
3. materialize the expected SDK migration rows in memory;
4. read existing SDK migration registry/status rows for the same package stream;
5. join the managed model registry, expected migration rows, SDK status rows, and
   `MarketsMetaTableCatalogTable`;
6. report missing migration rows, unexpected registry rows, missing catalog rows,
   stale catalog rows, pending revisions, failed revisions, and tables whose
   latest applied revision is not finalized in the catalog.

By default, `msm migrations current` reports the full `msm` migration stream for
the namespace. A `--model` or `--identifier` filter may narrow the displayed
diagnostics to the selected model closure, but it must not create a separate
per-table revision ledger. The revision graph remains package/namespace-level.

The catalog is verification input, not scope authority. A table appearing in the
catalog but not in `MIGRATION_MODEL_REGISTRY` should be reported as unmanaged or
legacy state. A managed model or migration-affected table missing from the
catalog should be reported as pending initialization/finalization state, not
silently registered by `current`.

### Lifecycle Contract

Schema lifecycle and runtime lifecycle are separate.

`msm migrations upgrade` is the only normal path that mutates schema state or
catalog state. `msm.start_engine(...)` is the runtime attachment boundary. It
must verify migration and catalog state, but it must not create tables, apply
migrations, register application MetaTables, or repair catalog drift.

The intended lifecycle is:

1. a developer changes SQLAlchemy MetaTable models;
2. the developer adds packaged Python migration modules under
   `src/msm/migrations/versions/`;
3. an admin runs `msm migrations sync` or `msm migrations upgrade`;
4. the migration runner syncs packaged rows into `MarketsMigrationTable`;
5. the migration runner applies pending rows through the SDK migration engine;
6. TS Manager applies DDL, refreshes affected platform MetaTables, and records
   migration status;
7. the `ms-markets` migration runner finalizes the migration by reconciling
   `MarketsMetaTableCatalogTable`;
8. runtime code calls `msm.start_engine(...)`;
9. `msm.start_engine(...)` verifies the migration stream and catalog are current;
10. `msm.start_engine(...)` attaches the runtime from catalog rows.

The runtime lifecycle is read-only. It may fetch migration status, catalog rows,
and platform MetaTable resources. It must not call `sync_packaged_migration(...)`
or `apply_migration(...)`.

### Admin Migration Lifecycle

The admin migration sequence is:

1. resolve the target model graph for the selected package surface;
2. delegate target data-source handling to the SDK migration API;
3. register or attach `MarketsMigrationTable`;
4. load packaged `msm` Python migration modules;
5. sync packaged migration rows into `MarketsMigrationTable`;
6. call SDK migration status for `(data_source_uid, "msm", migration_namespace)`;
7. apply pending migrations with `apply_migration(...)`;
8. validate SDK apply responses and affected-table introspection;
9. reconcile `MarketsMetaTableCatalogTable` rows for affected identifiers;
10. validate that catalog hashes and platform MetaTable UIDs match the applied
    SDK migration result.

If catalog reconciliation fails after SDK apply succeeds, the migration remains
not finalized from the `ms-markets` perspective. Re-running
`msm migrations upgrade` must be idempotent: it should see that the SDK migration
revision is applied, re-run catalog finalization, and then mark the package
runtime as current only after catalog reconciliation succeeds.

### Runtime Attachment Lifecycle

The runtime sequence is:

1. resolve requested models from the `models` selector;
2. read SDK migration status for `("msm", migration_namespace)`;
3. fail if any migration needed by the requested model graph is pending, failed,
   or not finalized in the catalog;
4. read `MarketsMetaTableCatalogTable` rows for requested identifiers;
5. attach platform MetaTables by cataloged UID;
6. validate catalog contract hashes against local SQLAlchemy models;
7. build and return the repository/runtime context.

`msm.start_engine(...)` should be renamed conceptually from "bootstrap" to
"attach from catalog", even if the public function name remains
`start_engine(...)`. Existing mutating helpers such as
`bootstrap_markets_meta_tables_from_catalog(...)` should be split so the runtime
path can call a non-mutating attachment function.

If the installed SDK does not expose the migration status API, runtime startup
must fail with a clear SDK upgrade error. If the authenticated identity can read
runtime MetaTables but cannot apply migrations, runtime startup may still
succeed only when all migrations and catalog finalization are already current.

### Catalog Finalization

The SDK migration engine refreshes affected platform MetaTable resources, but
`ms-markets` still owns its internal runtime catalog. After a successful SDK
apply response, the `ms-markets` migration runner must update
`MarketsMetaTableCatalogTable` before runtime attachment is allowed.

For every affected logical identifier, the runner should:

1. resolve the current SQLAlchemy model;
2. compare the SDK response `new_contract_hash` with the local authored contract
   hash;
3. resolve the refreshed platform `MetaTable` UID from the apply response or
   platform lookup;
4. upsert the `MarketsMetaTableCatalogTable` row with the new `contract_hash`,
   `sdk_version`, `model_name`, `description`, and platform `meta_table_uid`;
5. record the applied migration revision or finalization status in catalog
   metadata if the catalog table is extended with migration fields.

The catalog is a projection of the applied schema state. It is not the migration
ledger and it must not be manually rotated to accept drift. Catalog changes are
valid only as part of migration finalization backed by SDK migration status and
platform MetaTable introspection.

### Documentation And Skill Contract

This migration lifecycle must become the documented, intended registration and
schema-evolution process for `ms-markets`.

The project documentation and packaged agent skills must teach one scalable
path:

```text
package migration artifacts
-> sync registry rows
-> apply SDK migration
-> finalize catalog
-> runtime attach from catalog
```

They must not present row-class schema creation, catalog rotation, direct
MetaTable registration, or runtime bootstrap side effects as normal ways to
create or evolve library-owned tables.

The docs and skills should cover:

- how to add a new library-owned MetaTable through a packaged Python migration;
- how to evolve an existing MetaTable through a packaged Python migration module
  with structured SDK operations;
- how to use old/new contract hashes;
- how the SDK `MigrationMetaTable` registry differs from
  `MarketsMetaTableCatalogTable`;
- how `msm migrations current`, `sync`, `upgrade`, and `validate` fit into
  release and deployment workflows;
- why `msm.start_engine(...)` is runtime attachment only;
- how extension packages should follow the same pattern instead of creating
  parallel registration systems.

### CLI Contract

The package will expose admin commands:

```bash
msm migrations current
msm migrations sync
msm migrations upgrade
msm migrations validate
```

`msm migrations current` is read-only. It resolves the existing migration
registry, calls SDK migration status, and reports the current revision, latest
successful revision, latest attempted revision, pending packaged migrations, and
affected catalog rows. If the registry is missing, it reports that migrations are
not initialized without creating the registry.

`msm migrations sync` loads the package model registry and Python migration
modules, materializes SDK migration rows, then writes or
updates registry rows without applying migrations.

`msm migrations upgrade` syncs packaged rows, applies pending rows through the
SDK migration engine, finalizes the `ms-markets` catalog, and exits non-zero on
any failed or unfinalized revision.

Admin commands do not accept database URLs and do not open direct database
connections. Runtime startup uses only the read-only verification and attachment
subset of this lifecycle.

### Fresh Install Flow

On a fresh install:

1. An admin runs `msm migrations upgrade`.
2. The migration runner resolves the selected model graph.
3. The runner syncs the packaged Python migration rows into the registry.
4. The runner applies pending rows through `apply_migration(...)`.
5. TS Manager creates/imports/refreshes affected platform MetaTables.
6. The runner writes `MarketsMetaTableCatalogTable` rows.
7. Runtime `msm.start_engine(...)` later verifies status and attaches from the
   catalog without mutating schema or catalog state.

### Existing Install Adoption Flow

Existing installs need an explicit adoption path before ordinary upgrade
migrations:

1. discover currently registered `ms-markets` MetaTables through the catalog or
   platform lookup;
2. build or sync an adoption registry row that records the existing revision and
   affected identifiers;
3. validate physical contracts and contract hashes before accepting the
   adoption;
4. update catalog rows with the accepted adoption revision if the catalog stores
   migration metadata;
5. apply later migrations through the normal SDK registry workflow.

If an existing install has catalog rows but physical storage does not match the
expected adoption contract, the adoption command must fail and require explicit
repair.

## Implementation Tasks

### SDK `4.1.15` Alignment Tasks

- [x] Bump `pyproject.toml` and `uv.lock` from the previous SDK release to the
      SDK release that exposes `MigrationManagedMetaTable`,
      `MigrationManagedTimeIndexMetaData`, `MigrationMetaTable`,
      `PackagedMetaTableMigration.operations_sha256`, and the
      `metatable-migration.v1` helpers. A clean `uv sync` must keep those APIs
      available.
- [x] Change the shared `ms-markets` MetaTable base so managed models inherit
      the SDK `MigrationManagedMetaTable`, not only `PlatformManagedMetaTable`.
- [x] Change the shared `ms-markets` time-index storage base so DataNode storage
      models inherit the SDK `MigrationManagedTimeIndexMetaData`.
- [x] Add a startup/import validation that every model in
      `MIGRATION_MODEL_REGISTRY` is accepted by
      `validate_migration_managed_models(...)` before any sync, upgrade, or
      runtime status check proceeds.
- [x] Stop bypassing SDK migration validation when packaging migrations. The
      package runner must either use the SDK packaged-migration loader or call
      the same SDK validators before constructing/syncing registry rows.
- [x] Package real Python migration revisions under
      `src/msm/migrations/versions/` with non-empty structured `OPERATIONS`.
      Do not add `.sql` files, `SQL_PATH`, `sql_path`, or a separate SQL
      migration directory.
- [x] Ensure packaged rows populate `operations_sha256` from the structured
      operation payload and leave SQL-only fields unused for package-authored
      migrations.
- [x] Make `msm migrations upgrade` fail if the package model registry is
      non-empty but no migration revisions are materialized. It must not report
      a fresh database as current just because both current and expected
      revisions are `None`.
- [x] Make `msm migrations upgrade` re-run catalog finalization for already
      applied SDK revisions when catalog rows are missing, stale, or marked
      unfinalized.
- [x] Make runtime migration verification respect the requested model graph
      instead of checking or blocking on unrelated package tables.
- [x] Stop resolving or validating the active DynamicTable data source UID in
      `msm`; target data-source handling belongs to the SDK migration API and
      users do not pass it through the CLI.
- [x] Validate SDK apply/finalization responses before catalog writes:
      operation status, affected identifiers, refreshed platform MetaTable UID,
      and SDK `new_contract_hash` must match the local SQLAlchemy contract.

### SDK Dependency Tasks

- [x] Update the project SDK dependency to the release or local build that
      exposes `mainsequence.meta_tables.migrations`.
- [x] Add a compatibility check that fails clearly when
      `MetaTable.apply_migration(...)` or SDK migration helpers are missing.
- [ ] Verify the target data source exposes the SDK migration capability before
      applying migrations.

### `ms-markets` Package Tasks

- [x] Add `MarketsMigrationTable` as a `MigrationMetaTable` subclass.
- [x] Add the package migration model registry under `src/msm/migrations/`.
- [x] Add packaged Python migration modules under `src/msm/migrations/versions/`
      for the initial managed table set.
- [x] Ensure migration Python modules are included in built wheels.
- [x] Add `src/msm/maintenance/migrations.py`.
- [x] Implement migration package discovery and ordering.
- [x] Implement migration table-scope resolution from the package model registry,
      Python migration modules, SDK registry rows, and catalog verification.
- [x] Implement migration registry sync by materializing
      `PackagedMetaTableMigration` rows from Python modules,
      validating them with SDK migration validators, then calling
      `sync_packaged_migration(...)`.
- [x] Implement migration status reads using `get_migration_status(...)`.
- [x] Implement migration apply using `apply_migration(...)`.
- [x] Implement migration finalization that reconciles catalog rows for affected
      identifiers after SDK apply succeeds.
- [ ] Split current catalog bootstrap code into mutating migration/admin helpers
      and a read-only runtime attachment path.
- [ ] Make `msm.start_engine(...)` verify migration status and attach from the
      catalog without registering application tables or applying migrations.
- [x] Add `msm migrations current/sync/upgrade/validate`.
- [ ] Add adoption support for existing installs.

### Validation Tasks

- [ ] Test missing SDK migration API fails before runtime attachment or admin
      migration execution.
- [ ] Test registry table registration and packaged row sync.
- [ ] Test `msm migrations current` is read-only.
- [x] Test `msm migrations current` derives managed-table scope from the package
      model registry and affected-table scope from Python migration modules and
      SDK registry rows, not by mutating or discovering database tables directly.
- [ ] Test catalog rows with no package model registry entry are reported as
      unmanaged or legacy state.
- [ ] Test managed or migration-affected tables missing from the catalog are
      reported as pending initialization or finalization state.
- [x] Test `msm.start_engine(...)` is read-only and does not sync, apply,
      register application tables, or reconcile catalog rows.
- [ ] Test fresh install initial migration.
- [ ] Test existing install adoption.
- [ ] Test one additive column migration.
- [ ] Test one index migration.
- [x] Test catalog contract hash update after successful SDK apply.
- [ ] Test applied SDK migration with failed catalog finalization blocks runtime
      until `msm migrations upgrade` finalizes the catalog.
- [ ] Test already-applied SDK revisions with missing/stale catalog rows are
      finalized on the next `msm migrations upgrade`.
- [ ] Test empty materialized migration revisions fail when the managed model
      registry is non-empty.
- [x] Test registered models must inherit SDK migration-managed bases, including
      `MigrationManagedTimeIndexMetaData` for time-indexed storage.
- [x] Test packaged migrations use structured operations and
      `operations_sha256`, without `.sql` files or SQL path metadata.
- [ ] Test runtime migration checks are scoped to the requested model graph and
      SDK migration status response.
- [ ] Test `msm migrations upgrade` fails clearly when migration permission is
      missing.
- [ ] Test migration failure leaves catalog rows unchanged.
- [ ] Test repeated startup is idempotent after migrations are current.
- [x] Test generated SDK manifest payloads and operation checksums match packaged
      Python migration modules.

### Documentation Tasks

- [x] Update `docs/knowledge/msm/platform/meta_table_registration.md` with the
      migration-managed lifecycle.
- [x] Add a dedicated migration lifecycle page that documents the intended
      scalable registration path: packaged migration artifacts, SDK registry
      sync/apply, catalog finalization, and runtime attachment.
- [x] Update tutorials so normal workflows still call `msm.start_engine(...)`
      and do not call row-level schema helpers.
- [x] Add an operational migration page under `docs/`.
- [x] Update CLI reference docs for `msm migrations`.
- [x] Update packaged agent skills so agents treat SDK-managed migrations as the
      only normal process for creating or evolving library-owned MetaTables.
- [x] Add or update a focused migration skill covering the package model
      registry, Python migration modules, SDK registry
      sync/apply, catalog finalization, validation, and runtime attachment.
- [x] Add changelog entries when the implementation lands.

## Consequences

This makes schema lifecycle explicit and auditable while using the SDK migration
engine that already exists. `msm.start_engine(...)` remains the package runtime
entry point, but it is no longer a schema bootstrapper. Schema and catalog
mutation move to admin migration commands; runtime startup verifies and attaches
only after migrations and catalog finalization are current.

The project must align its dependency pin with the SDK release containing
MetaTable migrations. Until that dependency is available in the project
environment, the package runner can be tested with mocked SDK migration helpers,
but live admin migration execution and runtime migration-status verification
cannot be validated against the installed wheel.

The design keeps ordinary row operations narrow. Compiled SQL remains for
governed DML, while DDL lives behind the SDK `metatable-migration.v1` operation
with registry rows, revision checks, locks, checksums, contract rotation, and
catalog reconciliation.

## Non-Goals

- Do not add a direct database executor to `ms-markets`.
- Do not expose arbitrary user SQL execution through `msm` APIs.
- Do not widen `compiled-sql.v1` to include DDL operations.
- Do not propose a new SDK migration API from this ADR.
- Do not add a separate `MarketsSchemaMigrationTable`; use the SDK
  `MigrationMetaTable` registry.
- Do not make row classes such as `Asset` or `Portfolio` own schema creation.
- Do not treat catalog rotation as a substitute for migrations.
