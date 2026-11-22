# Repositories

The repositories concept owns compiled database operations for market-domain
models. It provides a stable boundary between application services and
MetaTable-backed persistence.

## Scope

Repositories answer these questions:

- How is a market-domain model created, searched, updated, or deleted?
- Which context is needed to compile and execute a database operation?
- Which queries should be reused by services or application code?
- Which operations should stay close to SQLAlchemy instead of client API models?

## Primary Modules

- `msm.repositories.base`: repository context, statement compilation, and
  operation execution helpers.
- `msm.repositories.crud`: generic CRUD builders and execution helpers.
- `msm.repositories.account_allocation_models`: reusable account allocation
  model operations.
- `msm.repositories.accounts`: account-specific repository operations.
- `msm.repositories.portfolios`: core portfolio identity operations.
- `msm.repositories.virtual_funds`: virtual-fund operations and fund lookup by
  account or portfolio.

## Key Contracts

Repositories should return operation payloads or dictionaries that application
code can use without reaching into SQLAlchemy internals. They should keep query
construction explicit and testable.

Repository functions should accept a `MarketsRepositoryContext` when they need
platform metadata or execution settings.

`compile_markets_statement(statement, *, context, operation, dialect=None)`
compiles SQLAlchemy SQL with `metatables.compiled_sql.v1`. It sends SQL and one
DataSource, never a declared table list: the database enforces the caller's
table permissions on the tables the SQL touches. The context supplies limits
and leaves `data_source_uid` as `None`, so the MetaTables API runtime supplies
the DataSource and dialect; `execute_markets_operation(...)` applies the context
`timeout`. Do not add table-scope parameters, SQL parsing, or local
permission checks to repository helpers. See
[MetaTable Registration](../platform/meta_table_registration.md) for the
DataSource and dialect selection rules.

### Writes That Change Several Tables

The account target, holdings and virtual-fund holdings snapshot writes each change
several tables and must commit together. They resolve the DataSource and dialect once
with `resolve_markets_sql_target(context)`, then compile for it:

- **PostgreSQL:** one statement whose data-modifying CTEs upsert the parents, delete
  the old rows and insert the new ones.
- **SQLite (the local runtime):** SQLite accepts only `SELECT` inside `WITH`, so the
  same steps compile with `compile_markets_statements(...)` into an ordered statement
  list. MetaTables runs the list in one transaction (MetaTables ADR 0026). Later
  statements find what earlier ones wrote by key. Values bind without casts, because
  SQLite casts `DATETIME` and `JSON` to numbers.

`execute_markets_write(write, *, context, refused_by=...)` runs either form. On
PostgreSQL a refused write (an existing snapshot without `overwrite`, a retired
portfolio, a virtual fund of another account) writes nothing and returns no rows. On
SQLite a guard statement with the matching label stops the transaction, so nothing at
all is written, and the call also returns no rows. Services check for that empty
result the same way on both dialects.

### Bulk Upserts Of Any Length

`bulk_upsert_model` returns every input row, in input order, with its
`upsert_status`, whatever the length of the list
([issue 84](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/84)).
It sends the rows in as many statements as these limits need:

| Limit | Constant in `msm.repositories.crud` | Where it comes from |
|---|---|---|
| 1,000,000 characters of SQL text | `MAX_STATEMENT_SQL_CHARACTERS` | The MetaTables API refuses a longer statement. |
| 32,766 bound values | `MAX_STATEMENT_PARAMETERS` | SQLite's default limit. PostgreSQL takes 65,535. |
| 10,000 rows | `MAX_STATEMENT_ROWS` | The most rows the MetaTables API returns from one statement. |
| 2,500,000 bytes of rows, estimated | `MAX_STATEMENT_ROW_BYTES` | The MetaTables API accepts a request of 12,100,000 bytes and answers a statement with at most 8 MiB of rows. |

The SQL text and the bound values of a statement grow by a constant with each
row, so the function measures them on the first 16 rows and fills each statement
to 80% of the limit: about 4,700 `Asset` rows a statement on PostgreSQL. A
statement that still comes out over a limit is split in two before it is sent. Each statement asks
MetaTables for as many rows as it writes, so a list is no longer cut at the
context's `max_rows`, 1,000 by default.

Each statement is its own transaction. A MetaTables transaction returns only the
rows of its last statement, and a row's status comes from the statement that
wrote it, so several statements in one transaction could not report every row.
A list that needs several statements is therefore not written atomically:

- The conflict keys of the whole list are checked first. A key given twice or a
  `NULL` key raises `ValueError` before anything is written.
- When a statement fails, the rows of the statements before it stay written and
  the error is raised.
- Calling again with the same rows finishes the write. The rows already written
  come back `unchanged`.

The byte limit is an estimate made from the values given, so it cannot count a
large stored value that the list does not write. When MetaTables cuts the answer
of a statement at its 8 MiB, those rows were written, they are missing from
`rows`, and `truncated` is `true`.

`build_bulk_upsert_model_operation` builds one write for all its rows. It raises
`ValueError` when a statement of that write is over the first two limits.

### Reads That Answer Every Row

A read whose answer stands for a whole (a holdings or target snapshot, an allocation,
the inputs of a write) does not take a `limit`: a part of it looks like the whole.
`msm.repositories.complete_reads` reads it:

- `read_every_model_row(context, model=..., filters=..., in_filters=...)` for one
  table's rows. An empty `IN` list matches no row, where `search_model` drops it.
- `read_every_row(build_page, context=...)` for a select of its own. `build_page(offset)`
  compiles `page_select(statement, key=..., offset=offset)` with `compile_page`. The
  `key` must make each row unique, or the pages are not stable.

A page holds 10,000 rows. An answer in one statement costs one request. One in several
statements is read again until two reads agree, so a write between pages cannot mix two
states, and `IncompleteReadError` is raised when none agree.

`search_model` and its `limit` remain for lists a caller pages through.

## Extension Notes

Add generic behavior in `crud` only when it applies across models. Add
model-specific query behavior in a dedicated repository module. Promote
repository calls into `services` when application workflows need orchestration
or a simpler public API.

## Related Concepts

- [Models](../models/index.md)
- [Services](../services/index.md)
- [Accounts](../accounts/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
