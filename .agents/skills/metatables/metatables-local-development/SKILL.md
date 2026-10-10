---
name: metatables-local-development
description: "Develop and test applications using the installed MetaTables client against local SQLite before returning to the intended environment database. Covers project/API/Admin setup, runtime verification, isolated fixtures, application-owned migrations and returning to the environment after verification. Excludes MetaTables client/API implementation and hosted frontend deployment."
---

# Local-first MetaTables application development

Use local SQLite by default when building or changing a consuming application's
tables, migration providers, queries or producers. Exercise the application
through the same MetaTables API/client used with the environment database. Keep
development fixtures and test writes in the local runtime, then return to the
intended environment as part of the requested workflow. Respect an explicitly
requested target or backend-specific test scope.

In a copied skill, resolve the `docs/` and `src/metatables/examples/` paths below relative to
this skill's `references/` directory. In the MetaTables source checkout, resolve
them from the repository root. Read `docs/operations/local-runtime.md` for runtime
selection and persistence, and `docs/client/installation-and-connection.md` when
installing or troubleshooting. `src/metatables/examples/local_app/README.md` provides a complete
installed-package migration/write/read example.

## Select local storage deliberately

Three controls have different meanings:

- `local_mode_available: true` permits local development; it does not select the
  current database. `metatables init --local` prepares this configuration.
- `metatables serve --local` starts the laptop's one local API, always in Local
  mode. Add `--admin` to run the existing Vite development frontend. Running it in
  another project while the API is up reports the running API and exits.
- Global `metatables --local ...` and `configure_local_client()` select that
  running API from any checkout.

Before migrations or a batch of test writes, inspect the API's actual runtime.
A loopback URL, a local token, a test namespace or an updater hash is not proof of
storage isolation. Require `local_mode: true`; after initialization also require
`dialect: sqlite` and the expected local runtime DataSource. If these disagree,
stop the mutating work and restart with `serve --local`.
Do not retry against automatic hosted discovery when a local connection fails.

## One local runtime per laptop

The local runtime is a single SQLite file, `~/.local/share/metatables/metatables.sqlite`
by default, shared by every project, checkout and branch on the machine. Each project
records it under `local` in its `.local/runtime-data-sources.json`.

- A checkout that ran an earlier MetaTables release may still have its own
  per-checkout file saved there; upgrading does not move it. To join the shared
  runtime, select the shared file in Settings. The old file's tables are not copied:
  run the application's migrations and fixtures again, and leave the old file in place.
- The shared runtime is at the newest system migration any project applied. If
  status reports an unsupported revision, upgrade the application's
  `mainsequence-metatable` instead of selecting another database.

## Establish the development loop

1. Work in the consuming application's Git checkout, with its commit and origin
   remote. Use the Python environment containing MetaTables and the application's
   installed provider code. Reuse its existing configuration and SDK login.
2. For initial setup, run:

   ```bash
   mainsequence login
   metatables init --local
   metatables serve --local --admin
   ```

   Omit `--admin` for CLI-only work. The API is included in the Python package;
   a MetaTables source checkout is unnecessary. Admin runs through Vite. Its
   pinned source downloads only when missing, and ready dependencies are reused.
   Use `--admin-path` for an already prepared checkout. Follow the installation
   guide for Node/npm requirements and repository access; do not clone on each run.
3. In another terminal in the same project, inspect `metatables --local runtime
   status`. Confirm Local and review the selected SQLite candidate before any
   initialization. If system migrations are needed, explicitly run
   `metatables --local runtime initialize`, then inspect status again.
   Starting the API does not initialize or migrate a database.
4. Author and review application migrations using the
   [migrations skill](../metatables-migrations/SKILL.md). Run the application-local
   provider against the verified local runtime:

   ```bash
   metatables --local migrations upgrade --provider ledger.migrations:migration
   ```

   Substitute the application's own module. Provider code and revisions are
   installed in the application process; the API requires no provider approval
   or installation. System initialization and application histories remain separate.
   Running the provider yourself is for the local runtime only; hosted runtimes
   receive the same revisions from the deployment workflow's migration Job.
5. Build application contracts/queries with the
   [table skill](../metatables-meta-tables/SKILL.md), or producers/readers with the
   [updater skill](../metatables-time-index-table-updates/SKILL.md). Use small,
   deterministic local inputs, run the relevant application checks, and inspect
   actual rows and update results through the API.

## Keep verification local and reproducible

Make local integration-test setup select the connection before constructing
clients, resolving table bindings, or creating updaters. Fail before writes when
the selected runtime is wrong. A consuming application's test setup can use:

```python
from metatables import configure_local_client, get_runtime_status

configure_local_client()
state = get_runtime_status()
source = state.get("data_source") or {}
bootstrap = state.get("bootstrap") or {}
if not (
    state.get("local_mode") is True
    and state.get("dialect") == "sqlite"
    and source.get("class_type") == "sqlite"
    and source.get("uid")
    and bootstrap.get("active") is True
    and bootstrap.get("status") == "ready"
    and not state.get("data_source_error")
):
    raise RuntimeError("Tests require an initialized local SQLite runtime.")
local_source_uid = source["uid"]
```

Resolve each test output in that runtime and check its DataSource UID against
`local_source_uid`. Keep fixtures, migration providers and writable dependencies
there too. Local mode does not isolate unrelated HTTP calls, external connections,
or writes explicitly targeting another registered DataSource: replace those
side effects with fixtures or controlled test dependencies. SDK identity checks
still use the configured platform session.

Run pure contract/frame checks first, then the smallest useful API integration
case: apply the reviewed provider, seed a small fixture, execute the query or
producer, read and assert its output, and repeat to verify the intended incremental
or idempotent behavior. For a persistence claim, restart and read existing rows
before seeding again. Recheck runtime state after any restart or source change;
do not change the runtime source while tests or producers are running.

Local storage persists across launches, and other projects' tables and fixtures share
the same runtime. A new branch or project does not create a fresh test database. Use
identifiable fixtures in the application's own namespace and clean up only the rows
owned by the test. When a fresh database is necessary, select a
separate temporary SQLite file through Settings and initialize it explicitly;
restore the previous selection afterwards. Do not delete or replace a developer's
existing database just to obtain a clean test run.

SQLite verifies portable application behavior, not PostgreSQL/MySQL/MSSQL-specific
SQL, Timescale features, database roles or every concurrency behavior. Report that
limit and use the intended engine in an isolated test database when the task
requires those checks. Application models keep their hosted column types: a
PostgreSQL `JSONB` column runs as JSON, and `Numeric` runs as a SQLite number exact
to about 15 significant digits, the precision the client's float64 frames carry on
every engine. Unsigned 64-bit integers and arrays are rejected, naming the column.
Revisions need no SQLite variants: column and constraint changes run through Alembic
batch mode. Only raw PostgreSQL SQL must check `op.get_bind().dialect.name`. Do not use the shared environment database as the default
integration-test fixture.

## Finish verification and return to the environment

Record what passed, the runtime/DataSource used, and any engine-specific work still
unverified. Commit the reviewed application code and its migration revisions together;
local rows, catalog UIDs, credentials and fixture data are never promoted.
The application's deployment workflow applies those revisions to the hosted runtime
before the code rolls out; see the [migrations skill](../metatables-migrations/SKILL.md)
and `docs/client/deploy-application-migrations.md`. Add the migration Job if the
workflow lacks one.

When returning to the environment is part of the requested workflow:

1. Finish local tests and stop active writers. The local API stays Local; it has
   no switch to Hosted. Reach the environment through its deployed API: start a
   fresh client process without `--local` or `configure_local_client()`, following
   the installation guide's hosted endpoint selection, and use the deployed Admin
   for hosted data. Remove only transport overrides introduced for local work.
2. Re-read runtime status and verify `local_mode: false`, the intended verified
   hosted environment, the expected DataSource and readiness. `migration_required`
   means the deployed API's database has pending system migrations; its deployment
   applies them.
3. Restart application/test client processes and resolve catalog bindings again.
   Do not reuse local table UIDs or already-bound updater instances against the
   environment database. Do not apply application revisions from this session;
   the deployment's migration Job does. `migrations current` can confirm the
   deployed revision. Perform other environment writes only within the user's
   requested scope; passing local tests is not itself a request to seed fixtures
   or run backfills.

Do not redirect the SDK platform endpoint, invent `serve --hosted`, or use an
environment-variable runtime toggle. A task limited to local development can finish
with verified local results and clear remaining steps, without modifying hosted data.
