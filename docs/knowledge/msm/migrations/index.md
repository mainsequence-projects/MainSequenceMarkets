# Migrations

`msm` schema creation and schema evolution are admin workflows. Runtime code
attaches to already-registered `MetaTable` and `TimeIndexMetaTable` resources
through direct backend lookups keyed by SQLAlchemy table name; it does not
create tables, apply DDL, or repair schema drift.

The package exposes one application-owned MetaTables Alembic provider:

```text
msm_migrations:migration
```

That single provider covers core `msm`, `msm_portfolios`, and `msm_pricing`
MetaTables. Do not create separate migration configurations for those packages.

`msm.migrations:migration` remains a compatibility alias for the same provider
object. The top-level `migrations` package shipped by `ms-markets` 2.0.x is no
longer installed, because generic top-level package names collide with other
distributions and shadow application-owned `migrations` packages. The rename
does not change the provider key `msm:<namespace>` or the
`ms_markets__alembic_version` table. See
[ADR 0044](../../../ADR/0044-namespaced-migration-provider-package.md).

Since 2.1.0 the history starts at `0018_initial_schema`, which replaces
`0001`–`0017` without reusing their IDs. A database left at any of those
revisions fails with an unknown-revision error: downgrade it to `base` with
2.0.x installed, then apply 2.1.0 from empty. See
[ADR 0045](../../../ADR/0045-squashed-initial-schema-and-namespaced-packages.md).

Revision `0019_ledger_hypertable_uniqueness` removes the event ledger's extra
unique constraint that omitted the TimescaleDB partition key. The full-grain
unique index and existing rows remain intact; the accounting engine validates
cross-time economic identities. This is a forward repair, including when `0018`
committed but hypertable/catalog finalization failed. Do not rewrite or stamp
the applied revision. Once the ledger is a hypertable, TimescaleDB rejects a
downgrade restoring the old non-time constraint; use a forward repair instead.

## Admin Commands

Use the `metatables` CLI from the `mainsequence-metatable` client directly:

```bash
metatables --json migrations current --provider msm_migrations:migration
metatables migrations revision --provider msm_migrations:migration -m "describe change"
metatables --local migrations upgrade --provider msm_migrations:migration head
metatables --local migrations downgrade --provider msm_migrations:migration <revision>
```

`revision` autogenerates by default. The retired `mainsequence migrations`
commands are not available in Main Sequence SDK 9.

There is no `msm migrations ...` command group. The `msm` package integration is
the provider object.

Run `upgrade` and `downgrade` yourself only against a local runtime
(`metatables --local migrations ...`). Hosted environments are migrated by the
deployment workflow, described next.

## Hosted Deployments

Hosted runtimes are migrated only by a Job in the deployment workflow, which
runs from the candidate image before anything that uses the tables rolls out.
This repository's `.mainsequence/workflows/ms-markets-api.yaml` builds the image, runs
`jobs/migrate_markets.py`, and deploys the Markets API with
`needs: [migrate]`. The Job calls
`metatables.upgrade_application("msm_migrations:migration")`; a database already
at head is left unchanged, and a failure blocks the API rollout while the
previous release keeps serving.

### Migration diagnostics and repeated runs

The minimum client is MetaTables 0.1.33. `upgrade_application()` automatically
uses fresh table inventories and batched physical inspections; PostgreSQL
reflection is batched by schema. Finalization requests remain bounded to ten
tables each, with the version table first. No batching option or project-specific
runner is required.

Discovery during a migration waits up to 300 seconds for MetaTables to wake or
finish replacing its pods. Ordinary client calls retain a 30-second discovery
budget. A discovery failure still fails the Job and blocks deployment.

`jobs/migrate_markets.py` enables INFO logging for `metatables.migrations.runner`.
Its logs separate preparation, database setup, table checks, Alembic execution,
catalog finalization, and total time. Measure these separately from platform
scheduling and workflow coordination; do not log migration connection responses
or credentials.

An already-current revision **still runs catalog reconciliation**, including
missing-table checks and description, label, and column metadata refresh. Do not
skip the Job or finalization because `migrated=False`. If DDL committed but
finalization failed, inspect the actual schema and per-table errors, then rerun
the same migration through a new deployment. Do not stamp, rewrite applied
revisions, or downgrade to recover catalog state.

The runner carries changed, non-empty authored table descriptions, labels, and
column descriptions, labels, and logical names in each finalization batch. An
unchanged revision can therefore refresh catalog metadata without new DDL.
Empty or absent metadata preserves existing values; fresh physical inspection
still owns types, keys, indexes, and nullability. Equal-valued reruns avoid
catalog writes. This payload requires the matching MetaTables API update, which
also corrects SQLite schema reflection for multi-batch downgrades.

Client improvements require an updated application image. API-side batching,
unchanged-contract write avoidance, and startup optimizations require the shared
MetaTables API to be deployed with that release too. Update matching guidance
with `metatables copy-metatables-skills --path .` after updating the client.

!!! warning "Required: MetaTables access for the deployment"
    The migration Job runs as its own workload User, which has no MetaTables
    grants until an Organization admin runs `scripts/bootstrap_metatables_access.py`
    for that Environment. Until then every hosted migration fails and the API is not
    deployed; see
    [MetaTables access in each Environment](../../../releasing.md#metatables-access-in-each-environment).

The ms-markets schema is owned and migrated only by this repository's
deployment. An application that installs ms-markets to read or write its tables
does not apply `msm_migrations:migration`; its own migration Job, if it has one,
applies only its own providers, and it runs against the schema the ms-markets
deployment has applied.

Do not run migrations at application startup, and do not run
`metatables migrations upgrade` or `downgrade` against a hosted API from a
developer or agent session.

Each revision must stay usable by the release that is still deployed, because
it keeps serving during the rollout and after a failed one: add tables and
nullable or defaulted columns first, and drop or rename in a later release.
Redeploying an older image does not roll back the schema.

`revision` creates normal Alembic revision files at the provider's
namespace version location. Revision files and namespace-specific revision
directories are generated authoring output; documentation must not treat them
as pre-existing checkout state. Revisions are generated by Alembic; they are not
hand-authored operation manifests.

The package migration environment stays on the standard MetaTables scaffold
path:

- `src/msm_migrations/env.py`;
- `src/msm_migrations/script.py.mako`;
- namespace version locations calculated by `metatables.migrations`.

`env.py`, provider construction, provider model registry, version-table class
construction, metadata extraction, namespace version-location calculation, and
the revision template should stay on the `metatables.migrations` helper path
instead of local boilerplate.

## Default Schema Rule

PostgreSQL `public` is the default schema. In this provider's SQLAlchemy
metadata, default-schema tables must be authored with `schema=None`, not
`schema="public"`.

This matters for Alembic autogenerate. PostgreSQL reflection reports
default-schema foreign keys as `schema=None`. If model metadata says
`schema="public"`, Alembic treats identical foreign keys as changed and emits
false `drop_constraint(...)` / `create_foreign_key(...)` pairs. Reject that
generated revision; the model or migration environment is wrong.

Use explicit schema metadata only for real non-default schemas.

`upgrade` loads the provider in the application process, reserves its catalog
entries through the MetaTables API, applies the Alembic migration with the
environment connection selected by that API, and finalizes the provider
MetaTable resources.

`downgrade` uses the same provider and Alembic revision graph to move the
schema back to an earlier revision.

## Lifecycle

1. Add or change SQLAlchemy model declarations.
2. Ensure the model is returned by the package model graph:
   `markets_sqlalchemy_models()`, `portfolio_sqlalchemy_models()`, or
   `pricing_sqlalchemy_models()`.
3. Let `metatables migrations revision --provider msm_migrations:migration`
   generate a normal Alembic revision.
4. Review the generated Alembic operations. A no-op model state must not produce
   FK drop/create churn, index churn, or `public` versus default-schema churn.
5. Apply and finalize the revision against the local runtime:
   ```bash
   metatables --local migrations upgrade --provider msm_migrations:migration head
   ```
6. Start runtime code with `msm.start_engine(...)`.
7. Commit the revision with the code that needs it. The deployment workflow's
   migration Job applies it to hosted environments before the API rolls out.

`msm.start_engine(...)` is direct and read-only. It resolves selected backend
tables by `model.__table__.name` and fails if required platform `MetaTable` or
`TimeIndexMetaTable` resources are missing.

## Registry

`src/msm_migrations/registry.py` defines the package-owned table universe used
by the MetaTables provider. It is the `msm` equivalent of an installed-app
registry, not migration history.

The registry is derived from:

- `msm.models.markets_sqlalchemy_models()`;
- `msm_portfolios.models.portfolio_sqlalchemy_models()`;
- `msm_pricing.meta_tables.pricing_sqlalchemy_models()`.

Managed models must inherit normal `metatables` authoring bases. Plain MetaTables use
`PlatformManagedMetaTable` through `MarketsMetaTableMixin`; time-indexed
time-index-table output uses `PlatformTimeIndexMetaTable` through
`MarketsTimeIndexMetaTableMixin`.

The registry is built through the `metatables.migrations`
`build_metatable_model_registry(...)` helper so filtering, duplicate identifier
detection, and provider order follow the same rules as other MetaTables
migration providers.

Time-index storage identifiers use the same `CamelCase` style as domain
MetaTables plus a `TS` suffix, for example `OrdersTS` and `AssetSnapshotsTS`.

See the platform-focused migration reference for provider details:
[MetaTable Migrations](../platform/metatable_migrations.md).
