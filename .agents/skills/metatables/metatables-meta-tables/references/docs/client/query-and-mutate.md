# Query and mutate

Storage operations use the MetaTables API. The caller needs the appropriate
table grant, the source must be available for the requested read/write mode, and
its storage access mode must permit the operation. Existing roles and grants
authorize the caller; the selected engine backend executes the database operation.

## Parameterized SQL

Use `metatables.compiled_sql.v1.compile_sqlalchemy_statement(...)` to compile a
SQLAlchemy Core statement with bound parameters. A request selects one DataSource;
the database applies your Reader and Writer grants to every table it touches.
Omit source and dialect configuration for the normal application path:

```python
from sqlalchemy import String, column, select, table

from metatables import MetaTable
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement

accounts = table("ledger_account", column("name", String))
operation = compile_sqlalchemy_statement(
    select(accounts).where(accounts.c.name == "Savings"), operation="select"
)
result = MetaTable.execute_operation(operation)
```

The client discovers the MetaTables deployment in the caller's Environment. The
compiler obtains the DataSource UID, dialect and parameter style together from
that API's fresh runtime context. No URL or DataSource UID is needed in the
application. A hosted API's deployment declares and initializes the runtime;
Local initializes it in Settings.
An absent, unavailable or malformed runtime source raises the public
`metatables.DataSourceResolutionError`; it never selects another source as a fallback.

For offline compilation, supply both `data_source_uid=` and `dialect=`. PostgreSQL
and MySQL use `pyformat`, SQL Server uses ordered `qmark`, and SQLite uses named
parameters. The API checks the wire dialect and the runtime binding. There is no
list of declared table scopes and no SQL parser in the API.

If only a UID is supplied, it must match the runtime source before the compiler
can infer its dialect. A different UID cannot borrow the runtime's dialect.
Supplying a UID and dialect offline creates a payload; it does not authorize
execution against another source. See the explicit [query example](../examples/query.py).

For applications still passing `scope_tables` or importing the removed scope
classes, follow [upgrade a legacy application](upgrade-legacy-app.md). Remove the
scope machinery instead of recreating it as per-query client checks.

Use `dialect_upsert(table, values, key_columns=[...])` for a single-row upsert.
Keys must identify a primary or unique key; MySQL also requires other unique
constraints to identify the same row. Temporal parameters carry type information.
For PostgreSQL inserts, the compiler replaces an explicit `None` UUID primary key
with `DEFAULT`; the database must define that default.

`table.run_query(sql)` submits a read-only request using that table's DataSource.
It can query any table you can read in the same runtime. Compiled operations with
`operation="select"` also use the read identity; insert/update/upsert/delete select
the write identity. The operation label does not classify or rewrite your SQL.
Database permissions prevent writes to Reader tables, reserved tables and provider
version tables. Sharing, schema changes and table deletion remain API operations.

Bind values instead of interpolating user input. Requests have row and time limits.
A full page indicates that more rows may exist. PostgreSQL, SQLite and MySQL reject
multiple statements. SQL Server accepts a batch under the same restricted identity;
an explicit commit inside a write batch can persist writes before a later error.
Use the supported table operations when an operation needs their transaction and
journal guarantees. See [database access](../security/index.md#sql-and-schema-boundary).

## Read another registered source

Keep the same API connection and runtime default. An administrator first
[imports the source's tables or views](register-existing-tables.md); Readers and
Writers then select an imported MetaTable and use its registered source:

```python
from metatables import MetaTable

external_table = MetaTable.get_by_uid("imported-table-uuid")
page = external_table.read_rows(columns=["symbol"], limit=100)
```

Use `iter_rows()` to consume bounded pages incrementally. These operations honor
table and namespace grants, source availability and read-only access. They do
not change the catalog, runtime DataSource selection or write destination.
The current external reader accepts structured columns, predicates and ordering;
it does not accept SQL or joins. `run_query()` and `execute_operation()` against
another source return HTTP 409 with `data_source_not_selected_runtime`, rather
than HTTP 503 suggesting an outage. General external SQL requires a separate
permission model; `operation="select"` alone does not establish that boundary.

## Metadata and search

`MetaTable.filter_by_body(...)` supports catalog filtering and pagination.
`MetaTable.column_search(...)` searches column metadata within visible tables.
Description/vector search and explicit search-index refresh are currently
unavailable. The CLI's `time-index-table search` defaults to column search.

`table.patch(labels=[...], description=...)` updates supported metadata. The
inherited separate add/remove-label and grant-action methods have no public route.
See [capabilities](../reference/capabilities.md) before using generic inherited
resource methods.

## Time-index deletion

For updater output, use `TimeIndexMetaTable.delete_after_date(...)` rather than
arbitrary SQL deletion. The cutoff is inclusive. Dimension filters select values;
`index_coordinates` selects complete coordinate streams. For example:

```python
from metatables import TimeIndexMetaTable

table = TimeIndexMetaTable.get_by_uid("balance-table-uuid")
table.delete_after_date(
    "2026-01-03T00:00:00Z",
    dimension_filters={"account_uid": ["account-uuid"]},
)
```

A `None` cutoff is allowed only with explicit dimension or coordinate scope.
`delete_after_date(None)` without scope is rejected. Physical deletion is followed
by recalculation of progress statistics; partial/uncertain failures require
inspection rather than assuming the previous client statistics remain current.

## Bounded results

SQL previews expose truncation; relation consumers can use `MetaTable.iter_rows()` to process one bounded page at a time. Complete collectors stop on row, byte, or deadline limits. See [bounded transfers](bounded-transfers.md) for options, pagination consistency, and retry behavior.
