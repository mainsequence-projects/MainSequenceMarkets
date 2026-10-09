---
name: metatables-migrations
description: "Create and evolve managed application tables through Alembic migration providers with the installed MetaTables Python client. Covers provider scope and placement, scaffolding, revision authoring, local execution, the deployment-workflow migration Job for hosted runtimes, the Team that owns an application's tables in each Environment, and reservation or finalization failures. Excludes API catalog migrations, client-library implementation, API/server changes and repository tooling."
---

# MetaTables client application migrations

## Client scope

Apply this skill to applications that consume the installed `metatables` Python
client. It covers application-facing models and workflows. Client-library
implementation, this repository's development/release tooling, and API internals
have separate ownership.

For upgrading older client imports, SQL scopes or provider integration, use the
[legacy upgrade skill](../metatables-upgrade-legacy-app/SKILL.md). This skill
covers authoring and running application schema revisions.

In a copied skill, resolve the `docs/` and `src/metatables/examples/` paths below relative to
this skill's `references/` directory. The client CLI bundles the matching version's
guides and examples there, including their linked documents. In the MetaTables
source checkout, read the same paths from the repository root.

For application development and mutation tests, use the
[local development skill](../metatables-local-development/SKILL.md) to select and
verify local SQLite before writing, then return to the intended environment after
verification within the requested scope.

Read `docs/client/define-and-migrate-tables.md`,
`docs/concepts/table-contracts-and-lifecycle.md`, and the tested
`src/metatables/examples/tables.py`. Managed authoring is migration-first: define SQLAlchemy
models, select a provider, author and apply a revision with the client, then
finalize catalog bindings through the API. Use the
[table skill](../metatables-meta-tables/SKILL.md) for contract design. The catalog
sync in `metatables migrations upgrade` also copies changed table descriptions,
labels and column metadata to existing tables; a metadata-only change needs no
revision (see the [table discovery skill](../metatables-table-discovery/SKILL.md)).

Check `docs/reference/capabilities.md` and `metatables migrations --help` before
promising a command. The API's own catalog migrations are a separate history: a
hosted API's deployment applies them before it rolls out, and Local mode runs them
from Settings; see `docs/operations/catalog-migrations.md`. They are not
application-provider revisions.

## Recommended workflow

Follow this sequence, which mirrors how the MetaTables API deploys its own system
migrations. Read `docs/client/deploy-application-migrations.md`.

1. **Develop locally.** Author the revision and apply it to verified local SQLite
   with the [local development skill](../metatables-local-development/SKILL.md).
2. **Commit the revision with the code that needs it.**
3. **Give a Team the tables.** Before the first hosted migration in each
   Environment, the application's tables need an owning Team: one platform Team
   per Environment (for example `ledger-development`), whose members are the
   migration Job's workload User and the workload User of every resource that
   reads or writes the tables. An Organization admin creates, in that
   Environment, each namespace the provider registers tables in, and grants the
   Team Writer on it. Recommend one namespace per application, owned by its Team;
   it is not required (see "Namespaces and applications" in
   `docs/security/ownership-and-sharing.md`).
   Tell the user these steps; they are made in the platform and in MetaTables
   Security, not in the repository.
4. **Deploy.** The application's `.mainsequence/workflows/` file declares a
   migration Job that calls `upgrade_application` for each provider, in
   dependency order, from the candidate image. The Job and every resource that
   uses MetaTables declare `access.branches: [{repository: MetaTables, level: view}]`.
   Every deployed resource that reads or writes the tables (FastAPI,
   `harness_agent` and others) has a deploy step with `needs: [migrate]`. A failed
   migration blocks the rollout.

Rules:

- Hosted runtimes are migrated only by that Job. Do not run `migrations upgrade`
  or `downgrade` against a hosted API from a developer or agent session. If the
  user explicitly requests it, do it once and recommend adding the Job.
- When the application has no migration Job yet, add one alongside its first
  managed table or its MetaTables upgrade.
- Do not migrate at application startup: several pods would race, and a failure
  would not stop the rollout.
- Keep each revision usable by the release currently deployed, which keeps serving
  during and after a failed rollout. Add first; drop or rename in a later release.
- Redeploying an older image does not roll back the schema. Downgrade is never a
  deployment step.
- Tables belong to the Team, never to one workload User. Workload Users change
  with each Environment and each recreated Job; a new one needs Team membership
  only. Do not ask for direct table grants to a workload User, and do not run the
  Job as an Organization admin to get around a refusal.
- A table registered in a namespace the caller already writes gets no grant of
  its own; the namespace's Writers own it. The Team needs Writer on every
  namespace the provider uses.

## Source and runtime context

- The API selects its active runtime DataSource. Upgrade and downgrade use that
  environment connection. An explicit `--sqlalchemy-url` is available for revision
  authoring; use it only when that authoring target is intended.
- Git source facts come from the current checkout through the SDK. Do not ask the
  user to choose a branch or environment for a migration.
- An explicit `METATABLES_API_URL` selects an API endpoint, not a branch or a
  storage binding. See `docs/client/installation-and-connection.md`.
- Provider references resolve in the application process, for example
  `ledger.migrations:migration`. The API needs no provider code or allowlist.

## Author the migration

1. Define the SQLAlchemy models with stable, application-prefixed physical names.
2. Identify one provider module, migration namespace, target `MetaData`, model
   registry, and prefixed Alembic version-table binding.
3. Choose a provider module name that no other installed package uses (see
   [Provider placement](#provider-placement)).
4. Keep provider scope explicit. Do not scan all imported models or installed
   packages.
5. Scaffold only when the application has no provider yet:

   ```bash
   metatables migrations scaffold \
     --package ledger \
     --module ledger.migrations \
     --namespace ledger \
     --base ledger.tables:Base \
     --metadata ledger.tables:Base.metadata \
     --alembic-version-table-name ledger__alembic_version
   ```

   Always pass `--module` and `--alembic-version-table-name`. Without them the
   scaffold creates a top-level `migrations` module and the shared
   `public.alembic_version` table.
6. Edit the generated `registry.py` so it returns exactly the models owned by
   that migration stream. Scaffolding alone selects no models and creates no
   tables.
7. Create and review an Alembic revision (defaults to autogeneration):

   ```bash
   metatables migrations revision \
     --provider ledger.migrations:migration \
     --message "create ledger"
   ```

Use `--source-root` and `--code-repository-root` when the application does not
use the default `src/` layout. Keep applied revisions immutable; add a new
revision for every later schema change.

## Provider placement

The application decides where its provider lives. The module name, however,
must not collide with any other package installed in the same environment. A
library's provider ships in its wheel and runs inside its consumers'
environments, next to providers from other libraries. When two packages install
the same top-level module, such as `migrations`, the later install overwrites
the earlier one's files. Imports then load the wrong provider, and Alembic reads
the wrong revisions.

- Place the provider under an import package the application owns, for example
  `ledger.migrations`, or give it a name specific to the application, for example
  `ledger_migrations`.
- Point `script_location` and `version_location_prefix` at that module. The
  scaffold derives both from `--module`. A hand-written
  `build_metatable_migration_provider` call must pass both, because the builder
  defaults to `migrations:`.
- Before releasing a package that others install, list the built wheel with
  `python -m zipfile -l <wheel>`. Its top-level entries must be packages the
  application owns.

## Execute with the environment connection

During development, after verifying the local runtime, use the application's
provider reference:

```bash
metatables --local migrations upgrade --provider ledger.migrations:migration
metatables --local migrations current --provider ledger.migrations:migration
metatables --local migrations downgrade 0001 --provider ledger.migrations:migration
```

The global `--local` selects the running project's API connection; inspect runtime
status because Admin can switch that API to Hosted. Upgrade/downgrade accept
Alembic targets. Use `--no-autogenerate` for offline revision authoring.

Write each revision once, for the hosted engine. On local SQLite, MetaTables runs
column and constraint changes through Alembic batch mode, generated revisions use
batch blocks, `JSONB` runs as JSON, and `postgresql_where` predicates also apply to
SQLite. Raw PostgreSQL SQL, such as `ctid`, `::` casts or `jsonb_*` functions, must
branch on `op.get_bind().dialect.name`.

The client imports and executes application revisions, using the connection
resolved for the selected environment. Environment operators supply the database
login's DDL privileges. MetaTables does not mint migration roles or sandbox DDL.
API Writer checks govern connection admission and provider catalog operations.
The client reserves catalog entries, runs Alembic, closes its physical connection,
and finalizes contracts through the API. Treat connection material as private.

Python code can call `metatables.upgrade_application("ledger.migrations:migration")`;
`src/metatables/examples/scripts/setup_metatables.py` shows the pattern, and the
deployment migration Job uses the same call. Remove the retired
`application_migration_providers` setting and use Python references instead of aliases.
Application migration histories remain separate from API system migrations.

## Lifecycle invariants

- Provider tables and the Alembic registry are `platform_managed` +
  `alembic_managed`.
- Reservation precedes physical migration; reconciliation moves catalog rows
  from `reserved` to `active`.
- The registry is the provider root and has no parent. Provider tables bind to
  that registry.
- Physical identity is DataSource UID + physical schema + physical table name.
  A logical identifier or contract hash does not replace it. See
  `docs/concepts/identity-and-scope.md`.
- Repeated setup reuses compatible bindings and applied revision history.
- `.register()` is lifecycle plumbing, not the ordinary way to create an
  application table. External registration cannot stand in for a managed
  migration registry.

## Failure handling

Read `docs/operations/recovery-and-observability.md`.

- If provider loading fails, verify the import path, model registry, metadata,
  version-table binding, and installed `metatables` version.
- If the provider loads another package's code or revisions, find the file that
  its module resolves to with
  `python -c "import importlib.util as u; print(u.find_spec('migrations').origin)"`,
  replacing `migrations` with the provider module. A shared module name means
  another install overwrote it. Move the provider as the
  [legacy upgrade skill](../metatables-upgrade-legacy-app/SKILL.md) describes;
  do not edit files in `site-packages`.
- If reservation fails with `namespace_not_writable` or `table_not_editable`
  (403), the caller lacks Writer through the owning Team. Add the
  `caller_user_uid` from the error to the Team with Writer on the namespace, or,
  when the namespace or Team is missing, set them up as in step 3. A table
  registered before the Team existed may have only a retired workload User as
  Writer; an Organization admin grants the Team Writer on its namespace. Do not
  change code or physical names to get around it.
- If reservation fails otherwise, compare provider scope and physical identities
  before changing code. Do not create a second catalog row for the same table.
- If Alembic succeeds but finalization fails, physical DDL may already be
  committed. Inspect every per-table result and the actual schema before
  retrying.
- Inspect partial DDL before retrying, especially on engines without transactional
  DDL. A finalization-only failure can be retried without reapplying committed
  revisions. Client DDL has no API executor journal.
- Finalization sends at most 10 tables per request, the version table first, and
  reports `Finalizing MetaTables 11-20 of 62.` for larger providers (client 0.1.28
  and later). A run that stops partway leaves earlier batches active; rerun the
  same upgrade to finalize the rest.
- If the migration connection is refused with `provider_tables_misplaced`, provider
  tables sit in the `metatables` catalog schema (MetaTables #50). Don't stamp, rerun or
  hand-edit revisions. An administrator moves or drops those tables, then rerun.
- If it is refused with `provider_tables_owner_unreachable`, the tables belong to a
  retired role, named in `owners`. A database administrator runs
  `REASSIGN OWNED BY <role> TO mt_owner;` in that database, then rerun.
- If the client refuses because the connection "resolves unqualified names" outside the
  default schema, it isn't the connection MetaTables issued. Use that connection, or set
  `search_path` to the default schema.
- If finalization reports `physical_table_missing`, a current table is absent and nothing
  named it as removed. Its catalog binding is kept; check `other_schemas` and where your
  revisions created it. Client 0.1.29 and later name tables removed from the models or
  dropped by the run, such as on downgrade. Older clients fail this way after a removal or
  downgrade, so upgrade the client.
- `physical_table_inaccessible` means the table exists, but the MetaTables login can't
  read all its columns or use its owner. Fix ownership or privileges; the stored contract
  is kept.
- Destructive catalog deletion is not migration recovery and never bypasses
  schema-management protection.

## Validation

Verify provider scope and placement, revision content, the selected environment
connection, repeat execution, and final active bindings. Check that the deployment
workflow runs the migration Job before every resource that uses the tables, and
that each Environment has its owning Team with the Job's workload User. Report
separately what was checked offline and what was exercised against a configured API.
