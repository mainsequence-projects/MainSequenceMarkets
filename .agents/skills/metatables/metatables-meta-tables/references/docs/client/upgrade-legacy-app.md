# Upgrade a legacy application

Use this guide when moving an application from the MetaTables interfaces bundled
with MainSequence 8.x, or from an earlier extracted client, to the installed
`metatables` package. Update the application to the current contract. Missing old
scope classes are intentional removals, not missing features to recreate.

Install the target client and its compatible SDK in the application's Python
environment using [installation and connection](installation-and-connection.md).
Refresh the matching agent guidance with `metatables copy-metatables-skills`.
The `metatables-upgrade-legacy-app` skill covers this upgrade; the
`metatables-migrations` skill covers application Alembic schema changes.

## Identify the old interfaces

Inspect dependency pins, imports, the shared repository compiler, runtime setup,
and any application migration provider. Search for `mainsequence.client.metatables`,
`mainsequence.meta_tables`, `MetaTableOperationScopeTable`,
`MetaTableOperationScope`, `scope_tables`, and `application_migration_providers`.
Read the target client's exports and command help before replacing an interface.
Do not globally rename `mainsequence`: identity, login and Git source context
still belong to the SDK.

| Old usage | Current usage |
| --- | --- |
| Table resources imported from `mainsequence.client.metatables` | Public resources such as `MetaTable` and `MetaTableOperationLimits` from `metatables` |
| `mainsequence.meta_tables.compiled_sql.v1` | `metatables.compiled_sql.v1` |
| `MetaTableOperationScopeTable`, `MetaTableOperationScope`, `scope_tables` | Remove them; select the runtime DataSource |
| `operation.scope.data_source_uid` | `operation.data_source_uid` |
| Raw request `scope: {tables: ..., data_source_uid: ...}` | Top-level `data_source_uid`, with the existing statement and limits |
| API-installed provider aliases and `application_migration_providers` | Application-local Python provider references, such as `ledger.migrations:migration` |

Both wire shapes used the `compiled-sql.v1` label. That label alone does not imply
compatibility: the current API rejects the old `scope` field. Regenerate payloads
with the target client rather than adding the removed class back to the application.

## SQL selects a DataSource

Previously, the client sent SQL and a separate list of the tables it said the SQL
used. The API checked those declared catalog entries and could derive a connection
from them. Now the client sends SQL and a DataSource. The API executes with the
authenticated user's database permissions, and the selected engine checks the
tables actually touched. Table permissions remain in force without a second list.
See [ADR 0007](../adr/api/0007-database-enforced-table-access.md).

Remove helpers and parameters whose only purpose was constructing or checking the
old scope. Do not replace them with compatibility classes, SQL parsing, per-query
catalog registration lookups, or local permission checks. Registration and
finalization stay in their table lifecycle workflows. Preserve independent
application business rules and the query's physical table names and behavior.

For example, an old shared repository compiler might contain:

```python
from mainsequence.meta_tables.compiled_sql.v1 import compile_sqlalchemy_statement


def compile_repository_statement(statement, *, context, operation, models, access):
    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        scope_tables=[context.scope_table(model, access=access) for model in models],
        data_source_uid=context.data_source_uid,
        limits=context.limits,
    )
```

Replace that compiler and its callers with the current interface. Remove
`models=` and `access=` from calls when they served only the deleted scope:

```python
from metatables import MetaTable
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement


def compile_repository_statement(statement, *, context, operation, dialect=None):
    return compile_sqlalchemy_statement(
        statement,
        operation=operation,
        data_source_uid=context.data_source_uid,
        dialect=dialect,
        limits=context.limits,
    )


def execute_repository_operation(operation, *, context):
    return MetaTable.execute_operation(operation, timeout=context.timeout)
```

The compiler resolves missing DataSource or dialect values from the selected API
runtime. Leave `context.data_source_uid` as `None` for the automatic path: the
Environment selects the API deployment, and its runtime supplies the source and
dialect together. No application URL or source setting is needed. Missing or
malformed source metadata raises `metatables.DataSourceResolutionError`.
An explicit UID must match that runtime when its dialect is inferred; another
source cannot inherit the runtime dialect. Optional external reads use imported
MetaTables' `read_rows()`/`iter_rows()` under existing grants; arbitrary SQL remains
runtime-bound. See [query and mutate](query-and-mutate.md).

A MetaTable UID is not a DataSource UID. For offline compilation supply
both `data_source_uid` and `dialect`. For example, this exercises the replacement
compiler above without registration, credentials or a running API:

```python
from types import SimpleNamespace

from sqlalchemy import Integer, String, column, select, table

accounts = table("ledger_account", column("uid", Integer), column("name", String))
context = SimpleNamespace(
    data_source_uid="00000000-0000-0000-0000-000000000001",
    limits={"max_rows": 25, "statement_timeout_ms": 2000},
    timeout=10,
)
operation = compile_repository_statement(
    select(accounts).where(accounts.c.name == "Savings"),
    context=context,
    operation="select",
    dialect="sqlite",
)
assert operation.data_source_uid == context.data_source_uid
assert operation.statement.parameters == {"name_1": "Savings"}
assert operation.limits.max_rows == 25
assert operation.limits.statement_timeout_ms == 2000
```

Preserve bound parameters, result handling, offset, row limits, statement deadline
and HTTP timeout. `operation="select"` selects read execution; the other operation
labels select write execution. These labels do not validate the SQL's statement
type. Let the compiler choose the dialect's parameter style. Keep explicit runtime
selection in application setup, rather than guessing it from legacy table scopes.
See [query and mutate](query-and-mutate.md) for engine-specific behavior.

## Keep application migration history

Application providers and Alembic execution belong to the application. Update
provider/bootstrap imports to the target client's public migration interfaces,
and retain the existing provider package, namespace, model registry, version-table
binding, revision IDs and applied history. Do not scaffold a replacement provider
or stamp an existing database merely to make the upgrade pass.

The application loads its provider locally. The API handles authorization,
reservations, connection resolution and finalization. The client runs Alembic
through the selected environment connection; the environment operator supplies
its database DDL privileges. No provider code or allowlist is needed in the API.
Remove the retired `application_migration_providers` setting and replace provider
aliases with the application's Python reference.

Use [define and migrate tables](define-and-migrate-tables.md) and
[ADR 0013](../adr/api/0013-application-owned-migrations.md) for the migration
lifecycle. MetaTables' own catalog initialization is a separate migration history.
Updating client imports does not authorize applying migrations to a hosted database.

## Verify the converted application

Start with imports and offline query compilation against the target package.
Check query parameters, execution mode, limits and output handling. Confirm that
scope-only classes, methods and call arguments have been removed. Review provider
loading and revision history without changing the database.

For requested application execution checks, follow [local development](../operations/local-runtime.md)
and the copied `metatables-local-development` skill. Run the smallest relevant
query or migration workflow against verified local SQLite. Keep application
business behavior covered by its existing tests; do not add tests requiring the
removed scope checks. Report separately what was checked offline and what was
executed through an API. Local SQLite does not verify hosted database roles.
