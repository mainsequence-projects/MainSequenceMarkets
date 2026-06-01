# Migrations

`msm` schema creation and schema evolution are admin workflows. They are not
runtime API behavior and are not row-operation side effects.

Run migrations before application startup:

```bash
msm migrations current --json
msm migrations sync
msm migrations upgrade
msm migrations validate
```

These commands do not resolve a data-source UID in `msm` and users do not pass
one. Target data-source handling belongs to the Main Sequence SDK migration
API. SQL execution is owned by the SDK/TS Manager migration endpoint.

## Lifecycle

1. Add or change SQLAlchemy model declarations.
2. Keep package-owned models in `MIGRATION_MODEL_REGISTRY`.
3. Add a Python migration module under `src/msm/migrations/versions/`.
4. Define structured SDK migration operations in that Python module.
5. Run `msm migrations sync` to write SDK migration registry rows.
6. Run `msm migrations upgrade` to apply pending migrations and finalize
   `MarketsMetaTableCatalogTable`.
7. Start runtime code with `msm.start_engine(...)`.

`msm.start_engine(...)` only verifies migration status and attaches from the
finalized catalog. It must not sync migration rows, apply migrations, register
application tables, or repair catalog drift.

## Registry

`src/msm/migrations/registry.py` defines the package-owned table universe. It is
the `msm` equivalent of an installed-app registry, not migration history.

Python migration modules define revision metadata, affected models, and
structured SDK operation payloads. The runner materializes SDK manifest JSON at
`sync` or `upgrade` time; hand-authored YAML/JSON manifests and SQL migration
folders are not the source of truth.

Managed models must inherit SDK migration-managed bases. Plain MetaTables use
`MigrationManagedMetaTable` through `MarketsMetaTableMixin`; time-indexed
DataNode storage uses `MigrationManagedTimeIndexMetaData` through
`MarketsTimeIndexMetaTableMixin`.

Human-readable `msm migrations current` output groups catalog status by model
kind:

- Domain MetaTables such as `OrderManager` and `Asset`.
- Time-index Storage MetaTables such as `OrdersTS` and `AssetSnapshotsTS`.

See the platform-focused migration reference for the lower-level catalog and
SDK apply details:
[MetaTable Migrations](../platform/metatable_migrations.md).
