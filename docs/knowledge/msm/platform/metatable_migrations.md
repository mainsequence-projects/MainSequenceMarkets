# MetaTable Migrations

`msm` uses the application-owned Alembic migration provider interfaces of the
MetaTables client: the `mainsequence-metatable` distribution, imported as
`metatables`. The repository does not maintain its own migration runner,
migration ledger, or `msm migrations` CLI. The Main Sequence SDK 9 no longer
ships MetaTables or the `mainsequence migrations` commands.

## Provider

The provider is exported from `msm_migrations:migration` and contains:

- package: `msm`;
- migration namespace: the active markets namespace;
- script location: `msm_migrations:`;
- version location prefix: `msm_migrations:versions`;
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
collisions in databases that host multiple independent providers. The provider
and its revision graph belong to ms-markets alone. A downstream project that
adds its own tables declares its own provider, module, and version table; it
neither adds revisions to the ms-markets graph nor applies
`msm_migrations:migration`, which only the ms-markets deployment migrates.

Although the physical table is in PostgreSQL `public`, the provider metadata
authors default-schema tables as `schema=None`. `public` is the database
default, not a named provider schema. This keeps Alembic reflection and model
metadata on the same side of the comparison and prevents false FK drop/create
revisions.

## Commands

Use the `metatables` CLI with the application's provider reference:

```bash
metatables --json migrations current --provider msm_migrations:migration
metatables migrations revision --provider msm_migrations:migration -m "describe change"
metatables --local migrations upgrade --provider msm_migrations:migration head
metatables --local migrations downgrade --provider msm_migrations:migration <revision>
```

Run `upgrade` and `downgrade` only against the local runtime; hosted
environments are migrated by the deployment workflow's migration Job.

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
errors. In a hosted environment, the deployment workflow's migration Job
(`jobs/migrate_markets.py`) applies the provider before the API rolls out; fix
a failed Job and deploy again, or perform an explicit platform repair. Locally,
run `metatables --local migrations upgrade`.

## Adding A Table Or Schema Change

1. Define or change the SQLAlchemy model.
2. Add new models to the appropriate package model graph:
   `markets_sqlalchemy_models()`, `portfolio_sqlalchemy_models()`, or
   `pricing_sqlalchemy_models()`.
3. Confirm `metatable_provider_models()` contains the expected model exactly once.
4. Generate an Alembic revision with the `metatables migrations revision` CLI.
5. Review the generated revision. Reject revisions that only drop and recreate
   unchanged foreign keys because one side is `schema=None` and the other is
   `schema="public"`. Write the revision once, for PostgreSQL: on local SQLite,
   MetaTables runs column and constraint changes in Alembic batch mode and
   `JSONB` as JSON. Raw PostgreSQL SQL, such as `ctid`, `::` casts or `jsonb_*`
   functions, must branch on `op.get_bind().dialect.name`.
6. Upgrade the local runtime through `metatables --local migrations upgrade`.
7. Start application code through `msm.start_engine(...)` after the upgrade.
8. Commit the revision. Hosted environments receive it from the deployment
   workflow's migration Job, never from a developer session.

There is no hand-authored YAML, JSON, or operation manifest. Migration
history is the Alembic revision graph plus the provider's version table.

## Client Requirement

The implementation requires `mainsequence-metatable>=0.1.29,<0.2` with
`mainsequence>=9.0.19,<10`. The client exposes `AlembicMetaTableMigration`,
`AlembicVersionMetaTable`, application-owned Alembic execution, and the command
shape where
`metatables --local migrations upgrade --provider msm_migrations:migration head`
applies without `--apply`, `--to`, or `--register-metatables`. Namespace-scoped
revision directories use the Alembic `version_locations` configured by the
provider. Upgrading the client keeps the provider package, namespace, model
registry, version-table binding, revision IDs, and applied revision history.
The 2.1.0 squash into `0018_initial_schema` is a separate, one-time replacement
of the history; see
[ADR 0045](../../../ADR/0045-squashed-initial-schema-and-namespaced-packages.md).
