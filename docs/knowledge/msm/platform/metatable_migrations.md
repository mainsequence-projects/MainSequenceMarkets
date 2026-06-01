# MetaTable Migrations

`msm` schema creation and schema evolution are admin operations. Runtime code
attaches to an already-finalized catalog; it does not create tables, apply DDL,
or accept catalog drift.

## Lifecycle

Use this sequence for library-owned MetaTables:

1. Add or change SQLAlchemy model declarations under `src/msm/models/`.
2. Add a Python migration module under `src/msm/migrations/versions/`.
3. Define structured SDK migration operations in that Python module.
4. Run `msm migrations sync` to write SDK migration registry rows.
5. Run `msm migrations upgrade` to apply pending SDK migrations and finalize
   `MarketsMetaTableCatalogTable`.
6. Start application/runtime code with `msm.start_engine(...)`.

The SDK `MigrationMetaTable` registry stores migration rows and status for
idempotency, locking, checksums, and audit. `MarketsMetaTableCatalogTable` is a
runtime projection that maps logical `msm` model identifiers to current platform
`MetaTable` UIDs and local contract hashes.

## Package Registry

The table universe is defined in code by `MIGRATION_MODEL_REGISTRY` under
`src/msm/migrations/registry.py`. It is the `msm` equivalent of an installed-app
registry: migration commands use it to decide which package-owned models belong
to the managed schema lifecycle.

The registry is not migration history. Individual Python migration modules
define revision metadata and `affected_models()` or `AFFECTED_MODELS`; the
runner materializes SDK manifest JSON at `sync` or `upgrade` time.

Models in the registry must use SDK migration-managed bases. Plain MetaTables
inherit `MigrationManagedMetaTable` through `MarketsMetaTableMixin`; time-indexed
DataNode storage inherits `MigrationManagedTimeIndexMetaData` through
`MarketsTimeIndexMetaTableMixin`.

## Commands

```bash
msm migrations current --json
msm migrations sync
msm migrations upgrade
msm migrations validate
```

`current` is read-only. It reports package revisions, SDK migration status, and
catalog finalization state. Human-readable output groups catalog rows into
Domain MetaTables and Time-index Storage MetaTables so row-oriented contracts
and DataNode storage contracts are not shown as one flat list.
Time-index storage identifiers use the same `CamelCase` style as domain
MetaTables plus a `TS` suffix, for example `OrdersTS`.

`sync` registers or attaches the package migration registry and upserts packaged
migration rows. It does not apply migrations.

`upgrade` syncs rows, applies pending migrations through the SDK migration
engine, and finalizes catalog rows for affected identifiers.

`validate` fails unless SDK status and catalog finalization match the package
code.

See `examples/msm/platform/metatable_migration_lifecycle.py` for a small
inspection example that lists packaged revisions and prints the intended admin
command sequence.

The commands do not resolve a data-source UID in `msm` and do not ask users for
one. Target data-source handling belongs to the Main Sequence SDK migration API.
They do not accept database URLs and do not connect directly to the database.
SQL execution is owned by the SDK/TS Manager `metatable-migration.v1` endpoint.

## Runtime Contract

`msm.start_engine(...)` verifies migration status, reads finalized catalog rows,
resolves platform `MetaTable` resources by UID, validates local contract hashes,
and binds the runtime context. It must fail if migrations or catalog
finalization are not current.

Runtime startup may read:

- SDK migration status;
- `MarketsMetaTableCatalogTable`;
- affected platform `MetaTable` resources.

Runtime startup must not call:

- `sync_packaged_migration(...)`;
- `apply_migration(...)`;
- normal model `register()` for application tables;
- catalog reconciliation for application tables.

## Adding A Migration

Each migration revision should have:

- a Python module under `src/msm/migrations/versions/`;
- structured SDK migration operations in that Python module;
- explicit old contract hashes when the previous SQLAlchemy declaration no
  longer exists in the current package;
- affected model classes listed by the Python module.

Example shape:

```python
REVISION = "0002_add_asset_status"
EXPECTED_CURRENT_REVISION = "0001_initial"
MIGRATION_NAMESPACE = None
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

Forward migrations are the only supported package workflow. If a released
schema change needs correction, add another forward migration.

## SDK Requirement

The implementation requires a Main Sequence SDK version that exposes
`mainsequence.meta_tables.migrations`, `MigrationManagedMetaTable`,
`MigrationManagedTimeIndexMetaData`, `MetaTable.apply_migration(...)`, and
`MetaTable.get_migration_status(...)`. `ms-markets` currently targets SDK
`4.1.15` or newer. Older SDK versions fail clearly before admin migration
execution or runtime attachment.
