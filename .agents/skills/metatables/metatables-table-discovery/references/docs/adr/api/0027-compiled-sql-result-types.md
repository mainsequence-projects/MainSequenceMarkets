# ADR 0027: Compiled SQL declares its Uuid result columns

Status: Accepted.

Implementation status: implemented on development for 0.1.62. SQLite is tested in
process and through the local API. PostgreSQL, MySQL and SQL Server have not been run.

Owner: MetaTables API, with the Python client.

Related decisions: [ADR 0007](0007-database-enforced-table-access.md) (the API runs
caller SQL as it is and does not parse it) and
[ADR 0026](0026-atomic-statement-lists.md) (statement lists).
Issue: [MetaTables#103](https://github.com/mainsequence-projects/MetaTables/issues/103).

## Context

SQLAlchemy stores a `Uuid` column as `uuid` on PostgreSQL and as 32 hex characters
(`CHAR(32)`) on SQLite and MySQL. PostgreSQL returns a uuid, which the API renders as
dashed text. SQLite returns the stored hex, and the API passed it on unchanged. The
same compiled statement therefore returned `95dcdfeb-f8c0-…` on a hosted runtime and
`95dcdfebf8c0…` on the local one. SQLAlchemy's own result processor would convert the
hex, but compiled SQL runs without it.

The API cannot tell a `Uuid` column from any other `CHAR(32)`, and an expression such
as a `CAST` has no declared type in the database. Converting every 32-character value,
or every value that looks like a UUID, would change text that is not one.

## Decision

The compiled statement names its `Uuid` result columns, and the API renders them.

- `compile_sqlalchemy_statement` and `compile_sqlalchemy_statements` record each
  result column whose SQLAlchemy type is `Uuid` in the statement's `result_types`,
  under the name the database returns it as: `{"uid": "uuid"}`. That covers
  `SELECT`, `RETURNING` and `text(...).columns(...)`, and names such as `uid_1` for a
  second `uid`. The type is the one the dialect runs: a `TypeDecorator` over `Uuid` is
  a `Uuid`, and a `with_variant` type counts on the dialects where its variant is one.
- The API returns each `"uuid"` column as lowercase dashed text, `str(uuid.UUID(value))`,
  on every engine. Text that is not a UUID and `NULL` return unchanged. In a statement
  list, the last statement's `result_types` apply to the rows returned.
- `"uuid"` is the only result type. The API refuses others with 422, as it refuses
  any unknown field.
- Only the compiler's types decide. A `CAST` to text, SQL sent to `run_query` and
  other SQL without SQLAlchemy types return what the database returns.

A statement with no `Uuid` result columns sends no `result_types`, so its request body
is unchanged.

## Alternatives

- **A `CHAR(32)` converter in SQLite.** Converts every such column, `Uuid` or not.
- **Converting text that looks like a UUID.** Guesses from the data.
- **Converting in the client.** Raw HTTP callers and the API's own response would
  still differ by engine.

## Consequences

- A `Uuid` column returns the same text from the local runtime as from a hosted
  PostgreSQL runtime.
- An API before 0.1.62 refuses a request that carries `result_types` with 422. Deploy
  the API before clients send `Uuid` result columns to it.
