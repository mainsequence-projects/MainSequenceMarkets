---
name: metatables-migrations
description: "Create and evolve managed application tables through Alembic migration providers with the installed MetaTables Python client. Covers provider scope, scaffolding, revision authoring, client-side execution, and reservation or finalization failures. Excludes API catalog migrations, client-library implementation, API/server changes and repository tooling."
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

In a copied skill, resolve the `docs/` and `examples/` paths below relative to
this skill's `references/` directory. The client CLI bundles the matching version's
guides and examples there, including their linked documents. In the MetaTables
source checkout, read the same paths from the repository root.

For application development and mutation tests, use the
[local development skill](../metatables-local-development/SKILL.md) to select and
verify local SQLite before writing, then return to the intended environment after
verification within the requested scope.

Read `docs/client/define-and-migrate-tables.md`,
`docs/concepts/table-contracts-and-lifecycle.md`, and the tested
`examples/tables.py`. Managed authoring is migration-first: define SQLAlchemy
models, select a provider, author and apply a revision with the client, then
finalize catalog bindings through the API. Use the
[table skill](../metatables-meta-tables/SKILL.md) for contract design.

Check `docs/reference/capabilities.md` and `metatables migrations --help` before
promising a command. The API's own catalog migrations are a separate history that
an admin runs from Settings; see `docs/operations/catalog-migrations.md`. They
are not application-provider revisions.

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
3. Keep provider scope explicit. Do not scan all imported models or installed
   packages.
4. Scaffold only when the application has no provider yet:

   ```bash
   metatables migrations scaffold \
     --package ledger \
     --module ledger.migrations \
     --namespace ledger \
     --base ledger.tables:Base \
     --metadata ledger.tables:Base.metadata
   ```

5. Edit the generated `registry.py` so it returns exactly the models owned by
   that migration stream. Scaffolding alone selects no models and creates no
   tables.
6. Create and review an Alembic revision (defaults to autogeneration):

   ```bash
   metatables migrations revision \
     --provider ledger.migrations:migration \
     --message "create ledger"
   ```

Use `--source-root` and `--code-repository-root` when the application does not
use the default `src/` layout. Keep applied revisions immutable; add a new
revision for every later schema change.

## Execute with the environment connection

After verifying the intended runtime, use the application's provider reference:

```bash
metatables --local migrations upgrade --provider ledger.migrations:migration
metatables --local migrations current --provider ledger.migrations:migration
metatables --local migrations downgrade 0001 --provider ledger.migrations:migration
```

The global `--local` selects the running project's API connection; inspect runtime
status because Admin can switch that API to Hosted. Upgrade/downgrade accept
Alembic targets. Use `--no-autogenerate` for offline revision authoring.

The client imports and executes application revisions, using the connection
resolved for the selected environment. Environment operators supply the database
login's DDL privileges. MetaTables does not mint migration roles or sandbox DDL.
API Writer checks govern connection admission and provider catalog operations.
The client reserves catalog entries, runs Alembic, closes its physical connection,
and finalizes contracts through the API. Treat connection material as private.

Use the application's setup entry point when available. Python code can call
`metatables.upgrade_application("ledger.migrations:migration")`;
`examples/scripts/setup_metatables.py` shows the pattern. Remove the retired
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
- If reservation fails, compare provider scope and physical identities before
  changing code. Do not create a second catalog row for the same table.
- If Alembic succeeds but finalization fails, physical DDL may already be
  committed. Inspect every per-table result and the actual schema before
  retrying.
- Inspect partial DDL before retrying, especially on engines without transactional
  DDL. A finalization-only failure can be retried without reapplying committed
  revisions. Client DDL has no API executor journal.
- Destructive catalog deletion is not migration recovery and never bypasses
  schema-management protection.

## Validation

Verify provider scope, revision content, the selected environment connection,
repeat execution, and final active bindings. Report separately what was checked
offline and what was exercised against a configured API.
