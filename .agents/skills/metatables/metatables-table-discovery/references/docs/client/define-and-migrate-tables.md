# Define and migrate managed tables

Each application owns its Alembic provider and revision history. The MetaTables
client runs that code in the application's Python environment using the selected
runtime's database connection. The API supplies authorization, catalog reservation,
and finalization. MetaTables system migrations remain separate admin operations.
See [ADR 0013](../adr/api/0013-application-owned-migrations.md).

Managed table authoring is migration-first. Define SQLAlchemy models, select a
provider, create and review an Alembic revision, apply it, and finalize the catalog
bindings. Do not call a managed model's `register()` in ordinary application code.

[The table example](../examples/tables.py) defines an `Account` and a daily
`Balance` table. `Account` uses `PlatformManagedMetaTable`; `Balance` uses
`PlatformTimeIndexMetaTable` with grain `["time_index", "account_uid"]`. Both
carry intention, namespace, identifier, and column descriptions. The balance's
foreign key uses the account's SQLAlchemy `__table__.fullname`, so its target
matches the actual metadata key. Use `MetaData()` for the default schema: the
mixins normalize `public` to an unqualified name, so a default `public` schema on
`MetaData` or a hard-coded `public.` FK prefix would prevent SQLAlchemy from
resolving that target. Non-default schemas should match on both models.

In your own package, include every model needed by the migration stream. Prefix
physical table and Alembic version names with the application/package name.
A contract fingerprint does not replace an authored physical name.

## Scaffold a provider

For an importable package `ledger` with models in `ledger.tables`:

```bash
metatables migrations scaffold \
  --package ledger \
  --module ledger.migrations \
  --namespace ledger \
  --base ledger.tables:Base \
  --metadata ledger.tables:Base.metadata \
  --alembic-version-table-name ledger__alembic_version
```

The scaffold creates a provider, model registry, Alembic environment, revision
template, and versions directory under the chosen source root. Edit its
`registry.py` to return the intended `Account` and `Balance` models. Scaffold
creation alone does not select all imported models or migrate a database.
Use `--source-root` and `--code-repository-root` if your layout differs from `src/`.

### Provider placement

Where the provider lives is the application's choice. Its module name, however,
must be unique in every environment that installs the package. A library's
provider ships in its wheel and runs next to providers from other libraries. If
two packages install the same top-level module, such as `migrations`, the later
install overwrites the earlier one's files and imports load the wrong provider.
Pass `--module` with a module the application owns, such as `ledger.migrations`
or `ledger_migrations`. Without it, the scaffold creates a top-level `migrations`
module. A hand-written `build_metatable_migration_provider` call must set
`script_location` and `version_location_prefix` to that module, because both
default to `migrations:`. Before releasing, list the built wheel with
`python -m zipfile -l <wheel>` and check that every top-level entry belongs to the
application.

Pass `--alembic-version-table-name` as well. The default `public.alembic_version`
would be shared by every provider on the same DataSource that keeps the default.

## Author and execute in the application

Use the same Python provider reference for authoring and execution:

```bash
metatables migrations revision --provider ledger.migrations:migration --message "create ledger"
metatables migrations upgrade --provider ledger.migrations:migration
metatables migrations current --provider ledger.migrations:migration
metatables migrations downgrade 0001 --provider ledger.migrations:migration
```

Revision defaults to autogeneration against the selected environment connection.
Use `--no-autogenerate` for offline authoring, or `--sqlalchemy-url` for an explicit
authoring database. Review generated DDL before applying it. Upgrade and downgrade
accept Alembic revision targets. Applied revision IDs are read from the database.

For local work, initialize the runtime explicitly and select its API connection:

```bash
metatables init --local
metatables --local runtime initialize
metatables --local migrations upgrade --provider ledger.migrations:migration
```

The local API must already be running; `--local` selects its connection, so inspect
runtime status to verify the database actually selected in Settings.

Applications and libraries use the same public import in their migration Job or
explicit setup function:

```python
from metatables import upgrade_application

result = upgrade_application("ledger.migrations:migration")
```

The shared runner automatically uses the installed client's table inventories and
the API's batched finalization. No separate batching import or option is needed.
Keep this call in the explicit migration lifecycle, rather than executing it when
a library is imported. See [migration timings](deploy-application-migrations.md#migration-timings)
for diagnostics and the client/API updates needed to receive these optimizations.

For current and downgrade, use `metatables.migrations.runner.run_migration` with
`operation="current"` or `operation="downgrade", revision="0001"`.

Hosted runtimes are migrated by the application's deployment workflow, not from a
developer machine: a Job applies the providers from the candidate image before
the application rolls out. See
[Migrate in the deployment workflow](deploy-application-migrations.md).

The provider is installed only in the application process. Remove the retired
`application_migration_providers` setting from existing deployment configuration;
replace old aliases with application Python references. No API provider registration,
application code installation, or redeployment is required.

The connection uses the selected DataSource's configured database login. Environment
operators supply its CREATE/ALTER/DROP and ownership privileges. MetaTables does not
provision migration roles or sandbox DDL. API Writer checks continue to protect
catalog operations and connection admission; they do not limit direct database DDL.
Runtime connection credentials are private and must not be logged or persisted.

The client reserves bindings, executes Alembic, closes its database connection,
and finalizes physical contracts through the API. Finalization refreshes catalog
metadata and governed-SQL permissions, including cleanup of dropped provider tables.

## Evolve and recover

Add a new revision for every later schema change. Never rewrite revisions that
may already have been applied. Review autogenerated drops and foreign keys.
A failed finalization can leave physical DDL committed with catalog rows still
reserved; inspect the per-table result and actual schema before retrying.
`downgrade` is a physical schema operation and must be reviewed as carefully as
upgrade. A destructive catalog cascade is not migration reconciliation.

See [catalog migrations](../operations/catalog-migrations.md) for the different
migration stream that belongs to the API itself.
