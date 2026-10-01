# Query and mutate

Storage operations use the MetaTables API. The caller needs the appropriate
table grant, the source must be available for the requested read/write mode, and
its storage access mode must permit the operation. Existing roles and grants
authorize the caller; the selected engine backend executes the database operation.

## Parameterized SQL

Use `metatables.compiled_sql.v1.compile_sqlalchemy_statement(...)` to compile a
SQLAlchemy Core statement with bound parameters. A request selects one DataSource;
the database applies your Reader and Writer grants to every table it touches.
[The query example](../examples/query.py) selects account rows by name:

```python
from examples.query import find_accounts

result = find_accounts("runtime-data-source-uuid", "Savings")
```

The compiler can obtain the DataSource and dialect from the API runtime context.
For offline compilation, supply both `data_source_uid=` and `dialect=`. PostgreSQL
and MySQL use `pyformat`, SQL Server uses ordered `qmark`, and SQLite uses named
parameters. The API checks the wire dialect and the runtime binding. There is no
list of declared table scopes and no SQL parser in the API.

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
