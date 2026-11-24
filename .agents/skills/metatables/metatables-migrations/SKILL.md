---
name: metatables-migrations
description: "Create and evolve managed application tables through Alembic migration providers with the installed MetaTables Python client. Covers provider scope and placement, scaffolding, revision authoring, local execution, the deployment-workflow migration Job for hosted runtimes, the namespace and roles that give the Job access in each Environment, and reservation or finalization failures. Excludes API catalog migrations, client-library implementation, API/server changes and repository tooling."
---

# MetaTables client application migrations

## Client scope

Apply this skill to applications that consume the installed `metatables` Python
client. It covers application-facing models and workflows. Client-library
implementation, this repository's development/release tooling, and API internals
have separate ownership.

The `metatables/examples/` files named in this skill ship inside the installed package;
`python -c "import metatables.examples as e; print(e.__path__[0])"` prints their folder.

For application development and mutation tests, use the
[local development skill](../metatables-local-development/SKILL.md) to select and
verify local SQLite before writing, then return to the intended environment after
verification within the requested scope.

Read [Define and migrate managed tables](https://potential-doodle-wn39mnm.pages.github.io/client/define-and-migrate-tables/),
[Table contracts and lifecycle](https://potential-doodle-wn39mnm.pages.github.io/concepts/table-contracts-and-lifecycle/), and the tested
`metatables/examples/tables.py`. Managed authoring is migration-first: define SQLAlchemy
models, select a provider, author and apply a revision with the client, then
finalize catalog bindings through the API. Use the
[table skill](../metatables-meta-tables/SKILL.md) for contract design. The catalog
sync in `metatables migrations upgrade` also copies changed table descriptions,
labels and column metadata to existing tables; a metadata-only change needs no
revision (see the [table discovery skill](../metatables-table-discovery/SKILL.md)).

Check [Supported capabilities](https://potential-doodle-wn39mnm.pages.github.io/reference/capabilities/) and `metatables migrations --help` before
promising a command. The API's own catalog migrations are a separate history: a
hosted API's deployment applies them before it rolls out, and Local mode runs them
from Settings; see [Initialize and upgrade the runtime database](https://potential-doodle-wn39mnm.pages.github.io/operations/catalog-migrations/). They are not
application-provider revisions.

## Recommended workflow

Follow this sequence, which mirrors how the MetaTables API deploys its own system
migrations. Read [Migrate in the deployment workflow](https://potential-doodle-wn39mnm.pages.github.io/client/deploy-application-migrations/).

1. **Develop locally.** Author the revision and apply it to verified local SQLite
   with the [local development skill](../metatables-local-development/SKILL.md).
2. **Commit the revision with the code that needs it.**
3. **Deploy.** The application's `.mainsequence/workflows/` file declares a
   migration Job that calls `upgrade_application` for each provider, in
   dependency order, from the candidate image. The Job and every resource that
   uses MetaTables declare `access.branches: [{repository: MetaTables, policy: reader}]`
   (workflow API `3.0.0`; the platform refuses `2.3.0` files and `level:` entries).
   Every deployed resource that reads or writes the tables (FastAPI,
   `harness_agent` and others) has a deploy step with `needs: [migrate]`. A failed
   migration blocks the rollout. Pushing the file creates the Job's and the other
   resources' workload Users before any step runs. The first migration in an
   Environment registers the provider's tables; a namespace they name that does not
   exist yet is created by that registration, and the Job gets `editor` on it.
   Nothing is created by hand and no Organization admin is needed: do not tell the
   user to create the namespace before the push.
4. **Give the other workloads their roles through the branch.** Declare
   `branch_access` on the provider, one role per namespace the application's
   resources use (ADR 0029). In a scaffolded provider it is an argument of the
   builder call (client 0.1.70 and later; 0.1.69 accepts it only on
   `AlembicMetaTableMigration`):

   ```python
   # ledger/migrations/access.py: one constant for every provider of the repository
   BRANCH_ACCESS = {"orders": "editor"}

   # ledger/migrations/__init__.py
   migration = build_metatable_migration_provider(
       ...,
       branch_access=BRANCH_ACCESS,
   )
   ```

   A new provider gets it from `metatables migrations scaffold --branch-access
   orders=editor`. Never set `migration.branch_access` after construction: that skips
   the checks that refuse `owner` and unknown roles before anything is sent.

   After each finalization the Job declares those roles for every workload of its own
   code repository branch: the FastAPI, Agents and other Jobs deployed from the same
   workflow file. They have the role on their first request in every Environment, and
   a renamed or recreated Job or release keeps it. Nobody grants anything. Each role is
   at most the Job's own (`editor` on a namespace it created) and never `owner`. The
   declaration replaces the previous one, so a namespace removed from `branch_access`
   loses the branch's role at the next migration. With several providers in one
   repository, give each the same `branch_access` from one constant: a provider whose
   mapping differs from one an earlier provider sent in the same run fails with
   `BranchAccessConflict` before sending, because it would remove the other's
   namespaces. A refused namespace fails the Job with `BranchAccessRefused` after
   finalization; its message says who to ask. A local run by a developer declares
   nothing and continues.

   Every workload of a branch gets the same role. When one resource of the branch must
   not hold another's role, leave that namespace out of `branch_access` and use hand
   grants instead.

5. **Grant an owner, and anyone outside the branch.** This is a person's action in
   MetaTables, in each Environment; follow "Give the Job access" in
   [Migrate in the deployment workflow](https://potential-doodle-wn39mnm.pages.github.io/client/deploy-application-migrations/). A person who manages the Job in the
   platform manages the namespace's access: they grant `owner` to themselves or to a
   Team they belong to, so the namespace keeps an owner when the Job is recreated:
   their authority follows the workload User that created the namespace, and a
   recreated Job runs as a new one. Managing the Job gives no access to the
   namespace's tables until they grant themselves a role. People, Teams and another
   repository's workloads get roles only this way: an owner grants another
   repository's branch with `grant_role(<branch_uid>, "data_viewer",
   principal_kind="branch")`, once per Environment, and its workloads keep the role
   through renames. A grant takes effect on the next request, with no redeployment.

   Tell the user step 5; with their explicit go-ahead you may run `grant_role` from
   their session against the target Environment. Never put `grant_role` calls in the
   migration Job: workloads are refused by the access routes. If the namespace name is already taken, the first run stops
   with `namespace_access_required`; an owner grants the Job `editor`, or the
   application uses another namespace. A namespace created before ADR 0024 has no
   owner until an Organization admin grants one. Recommend one namespace per
   application; it is not required (see "Namespaces and applications" in
   [Ownership, roles, and inheritance](https://potential-doodle-wn39mnm.pages.github.io/security/ownership-and-sharing/)). To share part of the application's
   tables, add a namespace to those tables; see
   [Namespaces of a table](#namespaces-of-a-table).

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
- Tables belong to their namespace's roles, never to one workload User. A table
  created in a namespace gets no binding of its own. Workloads cannot create tables
  outside a namespace (`namespace_required`). Workload Users change with each
  Environment and each recreated Job: a direct role needs granting again, a Team
  only membership. Do not run the Job as an Organization admin to get around a
  refusal.
- The Job needs `editor` on every namespace the provider's tables declare; resources
  that only read and write rows need `data_writer`. `branch_access` gives them that
  role through the branch.

## Namespaces of a table

A table can be in several namespaces (ADR 0028). A role on a namespace applies to every
table in it; a table's role for a caller is the strongest across its namespaces.

- `__metatable_namespace__` is the application's namespace: one name. A subclass that
  sets it replaces what its base set.
- `__metatable_namespaces__` lists further namespaces and only adds. A table is in
  every name that it or any of its base classes lists there. Put the attribute on a
  mixin and give that base to the tables of the subset:

  ```python
  class LedgerTable(PlatformManagedMetaTable):
      __abstract__ = True
      __metatable_namespace__ = "ledger"

  class Reporting:
      __metatable_namespaces__ = ("ledger-reporting",)

  class Statement(Reporting, LedgerTable, Base): ...   # ledger and ledger-reporting
  class Posting(LedgerTable, Base): ...                # ledger only
  ```

- To share some tables of an application with a Team, declare a second namespace on
  those tables and have an owner grant the Team a role on it once. Do not grant table
  by table, do not split the application's namespace in two, and do not move tables.
- A namespace is not a schema change. Do not create a revision, a versions folder or a
  second provider for it, and do not list a model in two providers' registries: a table
  belongs to one provider. `upgrade head` applies the declaration at finalization, also
  when no revision is pending.
- The migration adds the namespaces the code declares, creating a missing one (the Job
  gets `editor` and is its creating workload), and removes the declared ones the code
  no longer lists. Removing a name therefore removes access for that namespace's
  principals at the next deployment. A namespace a person added by hand is never
  removed by a migration.
- A subset restricts only principals that hold no role on the application's namespace:
  roles add up and there is no deny. Tell the user this when they design a subset.
- The owners of every namespace a table is in are owners of the table.
- Never change `__metatable_namespace__` of the Alembic version table; the migration
  stops if the version table is not in the namespace its provider gives it.

## Source and runtime context

- The API selects its active runtime DataSource. Upgrade and downgrade use that
  environment connection. An explicit `--sqlalchemy-url` is available for revision
  authoring; use it only when that authoring target is intended.
- Git source facts come from the current checkout through the SDK. Do not ask the
  user to choose a branch or environment for a migration.
- An explicit `METATABLES_API_URL` selects an API endpoint, not a branch or a
  storage binding. See [Install and connect](https://potential-doodle-wn39mnm.pages.github.io/client/installation-and-connection/).
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
   `public.alembic_version` table. Pass `--branch-access NAMESPACE=ROLE` for each
   namespace the application's workloads use (step 4 of the recommended workflow);
   without it the provider carries a comment showing where `branch_access` goes.

   `--namespace` names the provider: its migration namespace, its revisions folder
   `versions/<namespace>/` and the catalog namespace of its Alembic version table.
   It does not decide which namespaces the tables are in; the models do (see
   [Namespaces of a table](#namespaces-of-a-table)).
6. Edit the generated `registry.py` so it returns exactly the models owned by
   that migration stream. Scaffolding alone selects no models and creates no
   tables.
7. Create and review an Alembic revision (defaults to autogeneration):

   ```bash
   metatables migrations revision \
     --provider ledger.migrations:migration \
     --message "create ledger"
   ```

   Autogenerate compares only the target's tables, by schema and name, and never
   proposes dropping a table. Write a table's drop by hand in a revision created with
   `--no-autogenerate`. Do not set `include_name_hook` to get drops generated: the
   hook replaces that protection, and one that admits another owner's table lets a
   revision delete it.

   After the first revision, upgrade to the script heads before authoring the next:
   autogenerate refuses a baseline that is not applied or whose active tables the
   connection cannot see, and reserves no table. Adding tables is not a reason for
   that refusal. If models are already ahead of the history, the upgrade applies the
   existing revisions and reports `physical_table_missing` for the tables still to
   author; run `revision` again to create them.

Do not call `commit()` or `rollback()` on the connection inside a revision. Its own
commit cannot be undone when the run later fails, and its own rollback fails the
migration without recording the revision. Use `op.get_bind().begin_nested()` to
recover from an error.

Use `--source-root` and `--code-repository-root` when the application does not
use the default `src/` layout. Keep applied revisions immutable; add a new
revision for every later schema change.

A column that holds a secret (password, API key, token) is declared with
`EncryptedString(secret=...)`; autogenerate renders it as `sa.Text()` and the
migration never needs the Secret. Changing a column between `String` and
`EncryptedString` needs no DDL: the next upgrade's finalization updates the
catalog's mark, and the application re-encrypts or decrypts existing rows itself.
See the [contracts skill](../metatables-meta-tables/SKILL.md#secrets-in-columns-application-encrypted-columns).

## Retire a table

A plain `delete()` of an Alembic-managed table answers 409. Retire it through its
provider: remove the model from the registry and the metadata, write the
`op.drop_table` in a `--no-autogenerate` revision, and upgrade. Use
`delete_with_cascade(confirm_cascade_delete=True, override_schema_management_protection=True)`
only for a teardown the user confirmed, after
`get_impact(action="drop_table", override_schema_management_protection=True)`: it
also deletes the referencing tables, changes one runtime only and writes no revision.
See "Retire a table" in [Define and migrate managed tables](https://potential-doodle-wn39mnm.pages.github.io/client/define-and-migrate-tables/).

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

A SQLite rebuild that fails with "cannot rebuild ... without losing" names what batch
mode cannot keep. Write that table's change as SQL, branched on the dialect; never
remove the clause to get the migration through.

In SQL given to `sa.text()`, a server default, check or computed column, escape a colon
before a word (`'{"a"\:1}'`), and keep that backslash in generated revisions.
Unescaped, SQLAlchemy writes `NULL` in its place, on PostgreSQL too.

A revision autogenerated on SQLite (client 0.1.75 and later) carries PostgreSQL's
types and SQL: keep its `op.get_context().dialect.name` conditionals. Autogenerate
takes the previous state from the provider's revisions, replayed offline, so a
revision must have no effect outside the database. Review every warning it prints:

- **cannot compare the PostgreSQL type:** a change such as `JSON` to `JSONB` was not
  detected. Write it by hand or autogenerate on PostgreSQL.
- **does not record the PostgreSQL definition:** the downgrade starts with a check
  that raises outside SQLite. Write the real previous types, defaults or index
  options from the revisions that created them, then remove the check. Never remove
  the check alone, and never accept SQLite's `JSON`, `DATETIME` or `CHAR(32)` there.

With client 0.1.74 or earlier, do not upgrade a local SQLite database that holds data
worth keeping: a batch rebuild destroys `UUID` values and drops indexes and constraints.
Upgrade the client first.

See "Autogenerate on SQLite" in [Define and migrate managed tables](https://potential-doodle-wn39mnm.pages.github.io/client/define-and-migrate-tables/).

The client imports and executes application revisions, using the connection
resolved for the selected environment. Environment operators supply the database
login's DDL privileges. MetaTables does not mint migration roles or sandbox DDL.
API `tables.migrate` checks govern connection admission and provider catalog operations.
The client reserves catalog entries, runs Alembic, closes its physical connection,
and finalizes contracts through the API. Treat connection material as private.

Applications and consuming libraries use the same public Python entry point in
an explicit setup function or deployment migration Job:

```python
from metatables import upgrade_application

result = upgrade_application("ledger.migrations:migration")
```

`metatables/examples/scripts/setup_metatables.py` shows the pattern. Keep
migration execution out of a library's import-time side effects. Remove the retired
`application_migration_providers` setting and use Python references instead of aliases.
Application migration histories remain separate from API system migrations.

## Repeated runs and migration performance

Use the shared `upgrade_application` path for every provider. Table-inventory and
physical-inspection batching are automatic in the client/API implementation; no
separate batching import, private backend helper or opt-in flag is needed.
An unchanged Alembic revision still reconciles physical contracts and refreshes
table descriptions, labels and column metadata. Do not skip finalization based
only on `migrated=False` or equal revision heads: missing/unreadable tables must
still fail, and only explicit removals may delete a catalog binding.

For a slow migration, read the "Migration timings" section in
[Migrate in the deployment workflow](https://potential-doodle-wn39mnm.pages.github.io/client/deploy-application-migrations/). Enable INFO logging for
`metatables.migrations.runner` to see preparation, database setup, table checks,
Alembic, finalization and total duration. The API logs inspection and total time
per finalization batch. Measure these separately from platform job scheduling
and workflow coordination before attributing the delay to schema validation.

Check the installed client and deployed API versions. Client optimizations need
a package update and application image rebuild; API batching needs a shared API
deployment. After installing a release containing the changes, refresh copied
skills with `metatables copy-metatables-skills --path /path/to/application`.
This command copies guidance; Python imports alone do not refresh it.

## Lifecycle invariants

- Provider tables and the Alembic registry are `platform_managed` +
  `alembic_managed`.
- Reservation precedes physical migration; reconciliation moves catalog rows
  from `reserved` to `active`.
- The registry is the provider root and has no parent. Provider tables bind to
  that registry.
- Physical identity is DataSource UID + physical schema + physical table name.
  A logical identifier or contract hash does not replace it. See
  [Identity and scope](https://potential-doodle-wn39mnm.pages.github.io/concepts/identity-and-scope/).
- Repeated setup reuses compatible bindings and applied revision history.
- `.register()` is lifecycle plumbing, not the ordinary way to create an
  application table. External registration cannot stand in for a managed
  migration registry.

## Failure handling

Read [Recovery, deletion, and observability](https://potential-doodle-wn39mnm.pages.github.io/operations/recovery-and-observability/).

- If provider loading fails, verify the import path, model registry, metadata,
  version-table binding, and installed `metatables` version.
- If `revision` refuses because `target_metadata` holds no table, the models are not
  defined or imported yet, or they use another declarative base than the target.
  Target their base's metadata or `metadata_for_models(models)`; listing them in the
  registry alone does not add them. Use `--no-autogenerate` only for a revision meant
  to be written by hand.
- If a revision generated before client 0.1.73 holds a `drop_table`, confirm the table
  is this provider's before applying it: those versions could generate drops of other
  owners' tables. If it is not, remove the drop and its downgrade counterpart from a
  revision that was never applied; if it was applied somewhere, tell the user.
- If the provider loads another package's code or revisions, find the file that
  its module resolves to with
  `python -c "import importlib.util as u; print(u.find_spec('migrations').origin)"`,
  replacing `migrations` with the provider module. A shared module name means
  another install overwrote it. Move the provider under an application-owned
  module (see [Provider placement](#provider-placement)), preserving its provider
  identity and applied revision history. Do not edit files in `site-packages`.
- If reservation fails with `namespace_access_required` (403), the namespace already
  exists: it is taken, or the Job was recreated with a new workload User. An owner the
  error lists, or a manager of the workload that created the namespace, grants the
  `caller_user_uid` `editor`, or adds it to a Team that holds it, then the Job is
  re-run. With `namespace_required`, set the table's namespace. With
  `table_not_editable`, an owner of the table or of one of its namespaces grants
  `editor`. Do not change code or physical names to get around it.
- If finalization reports `namespace_access_required` for a table, the code declares a
  namespace that exists and the Job lacks `tables.create` on it. The table keeps its
  namespaces and the other tables are finalized. An owner of that namespace grants the
  Job `editor`, then the Job is re-run. With `last_namespace`, the code no longer
  declares the only namespace the table is in: keep one on the model.
- If a Job or FastAPI of the application suddenly sees no tables after a deploy, and
  the application does not declare `branch_access`, a Job or release key was probably
  renamed in the workflow file: the platform recreated it with a new workload User
  that holds no role. A Job that reads "no table" as "nothing to do" then reports
  success and does nothing. Check with the namespace's explain,
  `GET /namespaces/<uid>/access/explain/?action=tables.get_data&user_uid=<workload_user_uid>`:
  no source applies. Fix: declare `branch_access` (step 4) and run the migration; a
  person grants the new workload User only as a stopgap.
- If the Job fails with `BranchAccessRefused`, finalization succeeded and only the
  declaration was refused. `namespace_access_required`: the Job lacks `tables.create`
  on that namespace; an owner grants the Job `editor` once, and the branch binding
  then covers its replacements. `role_above_caller`: declare a role at most the Job's
  own. `namespace_not_found`: no table registered into that name yet; fix the name.
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
that in each Environment the Job's workload User holds `editor` on its namespaces, the
other resources hold the roles they need, and a person or Team holds `owner`. Report
separately what was checked offline and what was exercised against a configured API.
