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
