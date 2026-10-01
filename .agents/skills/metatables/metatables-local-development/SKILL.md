---
name: metatables-local-development
description: "Develop and test applications using the installed MetaTables client against local SQLite before returning to the intended environment database. Covers project/API/Admin setup, runtime verification, isolated fixtures, application-owned migrations and switching back after verification. Excludes MetaTables client/API implementation and hosted frontend deployment."
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
- `metatables serve --local` starts the API in Local mode. Add `--admin` to run
  the existing Vite development frontend. Admin Settings can subsequently switch
  that running API to Hosted without changing its loopback address.
- Global `metatables --local ...` and `configure_local_client()` select the
  project's running API connection. They do not force its database back to Local.

Before migrations or a batch of test writes, inspect the API's actual runtime.
A loopback URL, a local token, a test namespace or an updater hash is not proof of
storage isolation. Require `local_mode: true`; after initialization also require
`dialect: sqlite` and the expected local runtime DataSource. If these disagree,
stop the mutating work and select Local in Settings or restart with `serve --local`.
Do not retry against automatic hosted discovery when a local connection fails.

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
before seeding again. Recheck runtime state after any restart or mode/source change;
do not switch modes while tests or producers are running.

Local storage persists across launches and Git branches of the checkout. A new
branch does not create a fresh test database. Use identifiable fixtures and clean
up only the rows owned by the test. When a fresh database is necessary, select a
separate temporary SQLite file through Settings and initialize it explicitly;
restore the previous selection afterwards. Do not delete or replace a developer's
existing database just to obtain a clean test run.

SQLite verifies portable application behavior, not PostgreSQL/MySQL/MSSQL-specific
SQL, Timescale features, database roles or every concurrency behavior. Report that
limit and use the intended engine in an isolated test database when the task
requires those checks. Do not use the shared environment database as the default
integration-test fixture.

## Finish verification and switch back

Record what passed, the runtime/DataSource used, and any engine-specific work still
unverified. Carry forward the reviewed application code and migration revisions;
local rows, catalog UIDs, credentials and fixture data are not promoted by a switch.

When returning to the environment is part of the requested workflow:

1. Finish local tests and stop active writers. In Admin **Settings → Runtime mode**,
   inspect the displayed hosted environment and choose the intended registered
   DataSource. Use **Switch to Hosted**. This changes the API worker and selected
   database; it does not copy or merge the local database. Leave local capability
   enabled if the developer needs to switch back later.
2. Re-read runtime status and verify `local_mode: false`, the intended verified
   hosted environment, the expected DataSource and readiness. The same local
   connection command still reaches this supervised API; its `--local` flag alone
   does not prove SQLite. If the switch fails and the old worker is restored,
   report the actual mode instead of claiming the switch succeeded.
3. Restart application/test client processes and resolve catalog bindings again.
   Do not reuse local table UIDs or already-bound updater instances against the
   environment database. Apply reviewed revisions or perform environment writes
   only within the user's requested scope; passing local tests is not itself a
   request to seed fixtures, run backfills or migrate that database.

If the user instead wants to connect to a separately deployed API, follow the
installation guide's hosted endpoint selection. Restore prior connection settings
and start a fresh client process without `configure_local_client()`; remove only
transport overrides introduced for local work. Do not redirect the SDK platform
endpoint, invent `serve --hosted`, or use an environment-variable runtime toggle.
A task limited to local development can finish with verified local results and
clear remaining steps, without switching the runtime or modifying hosted data.
