# MetaTable Migrations

`msm` uses the application-owned Alembic migration provider interfaces of the
MetaTables client: the `mainsequence-metatable` distribution, imported as
`metatables`. The repository does not maintain its own migration runner,
migration ledger, or `msm migrations` CLI. The Main Sequence SDK 9 no longer
ships MetaTables or the `mainsequence migrations` commands.

## Provider

The provider is exported from `migrations:migration` and contains:

- package: `msm`;
- migration namespace: the active markets namespace;
- script location: `migrations:`;
- target metadata: `MarketsBase.metadata`;
- Alembic version registry: `MarketsAlembicVersion`;
- provider model scope: `metatable_provider_models()`.

The provider is constructed with the `metatables.migrations` helpers:

- `build_alembic_version_metatable(...)`;
- `build_metatable_migration_provider(...)`;
- `build_metatable_model_registry(...)`;
- `run_mainsequence_alembic_env(...)`.

`MarketsAlembicVersion` stores Alembic state in
`public.ms_markets__alembic_version`. This package-specific version table avoids
collisions in databases that host multiple independent providers. Downstream
projects that inherit from ms-markets should use this same provider and version
table when they are extending the ms-markets revision graph.

Although the physical table is in PostgreSQL `public`, the provider metadata
authors default-schema tables as `schema=None`. `public` is the database
default, not a named provider schema. This keeps Alembic reflection and model
metadata on the same side of the comparison and prevents false FK drop/create
revisions.

## Commands

Use the `metatables` CLI with the application's provider reference:

```bash
metatables --json migrations current --provider migrations:migration
metatables migrations revision --provider migrations:migration -m "describe change"
metatables migrations upgrade --provider migrations:migration head
metatables migrations downgrade --provider migrations:migration <revision>
```

`revision` is the authoring entrypoint and autogenerates by default; pass
`--no-autogenerate` for offline authoring. It creates normal Alembic revision
files at the provider's namespace version location. Documentation must not
assume that revision files have already been generated or that any revision has
already been applied in a checkout.

`upgrade` loads the provider in the application process, reserves its catalog
entries through the MetaTables API, runs Alembic with the environment connection
selected by that API, and then finalizes the provider `MetaTable` and
`TimeIndexMetaTable` bindings. The API needs no provider code or allowlist; the
retired `application_migration_providers` setting and provider aliases are not
used.

## Runtime Contract

`msm.start_engine(...)` is runtime attachment only. It reads the finalized
backend `MetaTable` and `TimeIndexMetaTable` resources by each model's
SQLAlchemy table name and binds the runtime context. Alembic/provider metadata
owns schema correctness.

Runtime startup must not call:

- Alembic revision generation;
- migration execution;
- normal model `register()` for application tables;
- schema reconciliation for application tables.

Missing backend `MetaTable` or `TimeIndexMetaTable` resources are deployment
errors. Fix them by running the MetaTables migration upgrade flow or by
performing an explicit platform repair.

## Adding A Table Or Schema Change

1. Define or change the SQLAlchemy model.
2. Add new models to the appropriate package model graph:
   `markets_sqlalchemy_models()`, `portfolio_sqlalchemy_models()`, or
   `pricing_sqlalchemy_models()`.
3. Confirm `metatable_provider_models()` contains the expected model exactly once.
4. Generate an Alembic revision with the `metatables migrations revision` CLI.
5. Review the generated revision. Reject revisions that only drop and recreate
   unchanged foreign keys because one side is `schema=None` and the other is
   `schema="public"`.
6. Upgrade through the `metatables migrations upgrade` CLI.
7. Start application code through `msm.start_engine(...)` after the upgrade.

There is no hand-authored YAML, JSON, or operation manifest. Migration
history is the Alembic revision graph plus the provider's version table.

## Client Requirement

The implementation requires `mainsequence-metatable>=0.1.5,<0.2` with
`mainsequence>=9.0.1,<10`. The client exposes `AlembicMetaTableMigration`,
`AlembicVersionMetaTable`, application-owned Alembic execution, and the command
shape where `metatables migrations upgrade --provider migrations:migration head`
applies without `--apply`, `--to`, or `--register-metatables`. Namespace-scoped
revision directories use the Alembic `version_locations` configured by the
provider. Upgrading the client keeps the provider package, namespace, model
registry, version-table binding, revision IDs, and applied revision history.
