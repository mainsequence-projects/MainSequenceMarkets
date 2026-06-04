# MetaTable Migrations

`msm` uses the Main Sequence SDK Alembic migration provider API. The repository
does not maintain its own migration runner, migration ledger, or `msm
migrations` CLI.

## Provider

The provider is exported from `msm.migrations:migration` and contains:

- package: `msm`;
- script location: `msm:migrations`;
- target metadata: `MarketsBase.metadata`;
- Alembic version registry: `MarketsAlembicVersion`;
- provider model scope: `metatable_provider_models()`;
- post-registration hook:
  `refresh_markets_catalog_from_registered_metatables`.

`MarketsAlembicVersion` stores Alembic state in
`public.ms_markets__alembic_version`. This package-specific version table avoids
collisions in databases that host multiple independent providers. Downstream
projects that inherit from ms-markets should use this same provider and version
table when they are extending the ms-markets revision graph.

## Commands

Use the SDK CLI:

```bash
mainsequence migrations current --provider msm.migrations:migration --json
mainsequence migrations revision --provider msm.migrations:migration -m "describe change" --autogenerate
mainsequence migrations upgrade --provider msm.migrations:migration head
mainsequence migrations downgrade --provider msm.migrations:migration <revision>
```

`revision` is the authoring entrypoint. It creates normal Alembic revision files
under `src/msm/migrations/versions/`.

`upgrade` runs Alembic through the SDK provider and backend-scoped migration
connection. After a successful apply, the SDK synchronizes the provider
MetaTable catalog and calls the provider hook. The hook refreshes
`MarketsMetaTableCatalogTable` using the registered platform `MetaTable`
objects.

## Runtime Contract

`msm.start_engine(...)` is runtime attachment only. It reads the finalized
catalog, resolves platform `MetaTable` resources by UID, validates local
contract hashes and physical table shape, and binds the runtime context.

Runtime startup must not call:

- Alembic revision generation;
- migration render/apply;
- normal model `register()` for application tables;
- catalog reconciliation for application tables.

Missing catalog rows, stale contract hashes, or missing platform `MetaTable.uid`
resources are deployment errors. Fix them by running the SDK migration upgrade
flow or by performing an explicit platform repair.

## Adding A Table Or Schema Change

1. Define or change the SQLAlchemy model.
2. Add new models to the appropriate package model graph:
   `markets_sqlalchemy_models()`, `portfolio_sqlalchemy_models()`, or
   `pricing_sqlalchemy_models()`.
3. Confirm `metatable_provider_models()` contains the expected model exactly once.
4. Generate an Alembic revision with the SDK CLI.
5. Review the generated revision.
6. Upgrade through the SDK CLI.
7. Let the SDK `upgrade` command refresh the markets catalog automatically.

There is no hand-authored YAML, JSON, or SDK operation manifest. Migration
history is the Alembic revision graph plus the provider's version table.

## SDK Requirement

The implementation requires a Main Sequence SDK version that exposes
`AlembicMetaTableMigration`, `AlembicVersionMetaTable`, backend-scoped Alembic
migration execution, and the current SDK migration command shape where
`mainsequence migrations upgrade --provider msm.migrations:migration head`
applies without `--apply`, `--to`, or `--register-metatables`.
