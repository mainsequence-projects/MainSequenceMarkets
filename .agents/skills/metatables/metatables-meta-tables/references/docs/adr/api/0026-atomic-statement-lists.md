# ADR 0026: Atomic statement lists

Status: Accepted.

Implementation status: implemented on development for 0.1.60. SQLite is tested in
process, both on a source's own connection and on the local runtime's borrowed request
transaction. The PostgreSQL path has not been run: its end-to-end test is written but
skips without the disposable cluster of `scripts/test_postgresql.py`. MySQL and SQL
Server refuse statement lists.

Owner: MetaTables API, with the Python client.

Related decisions: [ADR 0007](0007-database-enforced-table-access.md) (the database
enforces table access; one statement per request),
[ADR 0012](0012-bounded-data-transfer-and-safe-retries.md) (bounded transfers) and
[ADR 0022](0022-concurrent-requests-and-connection-reuse.md) (connection reuse).
Issue: [MetaTables#98](https://github.com/mainsequence-projects/MetaTables/issues/98).

## Context

Some client writes change several tables and must commit together. ms-markets writes
an account snapshot as one PostgreSQL statement: data-modifying CTEs upsert the
parents, delete the old rows and insert the new ones, after a check that every named
portfolio is still live
([MainSequenceMarkets#53](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/53)).

SQLite, the local runtime, allows only `SELECT` inside `WITH`. On SQLite the write
must be several statements, but a compiled operation carries one statement and each
request is its own transaction. Sending the statements as separate operations would
leave half-written history after a failure, and the portfolio check would no longer
share the write's transaction.

## Decision

### A write may carry an ordered list of statements

`POST /meta-tables/execute-transaction/` accepts `compiled-sql.v1` with `statements`,
a list of 1 to 32 compiled statements, and a write operation (`insert`, `update`,
`delete` or `upsert`). The API opens one write transaction as the caller's own write
identity and sends the statements in order. It commits after the last statement and
rolls back on any error. The response has the shape of `execute-operation` and holds
the last statement's rows.

Statements do not pass values to each other. A later statement finds what an earlier
one wrote by its key, in the same transaction.

The client compiles the list with `compile_sqlalchemy_statements` and sends it with
`MetaTable.execute_transaction`.

### A statement may expect a row count

A statement may carry `expect_rows`: an exact count, or `"at_least_one"`. The count is
the statement's result rows, or the rows it changed when it returns none. When a
statement misses its expectation, the API rolls back the whole transaction and answers
409 with code `compiled_sql_guard_failed`, the statement's index and its optional
`label`. The client raises `MetaTableTransactionGuardError`.

A single PostgreSQL statement can hold such a check in a `WHERE`. Separate statements
cannot abort a later one from SQL in a way that works on every engine and that the
caller can tell from a database error, so the check is part of the request.

### ADR 0007's boundary holds without reading the SQL

ADR 0007 sends one statement per request so caller SQL cannot end the API's
transaction and go on outside it, as in `COMMIT; DELETE …`. A statement list keeps
that rule for each statement: each goes to the driver alone, through the same
restricted path as `execute-operation`, so PostgreSQL's extended query protocol and
Python's `sqlite3` still reject a second statement in one string.

Between statements, the API asks the driver whether its transaction is still open:

- **SQLite:** `sqlite3.Connection.in_transaction`. The engine authorizer already
  denies `BEGIN`, `COMMIT`, `ROLLBACK` and savepoints, so this check is a second line.
- **PostgreSQL:** the connection's transaction status must be "in transaction", and
  the statement's command tag must not be transaction control (`BEGIN`, `COMMIT`,
  `ROLLBACK`, `SAVEPOINT`, `RELEASE`, `PREPARE TRANSACTION` and the prepared forms).
  The tag is needed because `COMMIT AND CHAIN` leaves a new transaction open, without
  the API's settings.

Both answers come from the driver and the server, not from the SQL text. When the
check fails, the API stops before the next statement, rolls back what is still open
and answers 400 with `compiled_sql_transaction_ended`. On PostgreSQL a caller's
`COMMIT` has already committed the statements before it; the API cannot undo that.
The caller loses only its own atomicity: no statement runs after the API's
transaction ended.

Lists are refused for reads, so ADR 0007's `READ ONLY` transaction for reads is
unchanged.

Inside one transaction, a setting one statement makes, such as `SET LOCAL` or
`set_config('role', …, true)`, applies to the next. This gives no new access: the
login role is the caller's own and inherits all its memberships (ADR 0007), the API
enforces the time limit with its own cancellation, and `DISCARD ALL` resets the
connection before reuse (ADR 0022).

### Limits cover the whole list

- One time limit, `statement_timeout_ms` (at most 60 seconds), covers every statement:
  SQLite's progress handler and the API's cancellation timer each start once.
- `max_rows` and `offset` apply to the last statement's rows. Earlier statements'
  rows are counted for their expectations and never returned.
- A list holds at most 32 statements, and the request body stays within the transfer
  limits of ADR 0012.

### Engines

SQLite and PostgreSQL, including TimescaleDB, run statement lists. On SQLite a source
either opens its own connection, with `BEGIN IMMEDIATE` and a commit at the end, or
borrows the request's catalog transaction, as the local runtime does; there the
request's commit or rollback decides.

MySQL and SQL Server refuse a list with 422 and `compiled_sql_statement_list_unsupported`.
DDL in MySQL commits implicitly, and a SQL Server batch can commit before a later
error, so each needs its own design.

### The compiler refuses CTEs SQLite cannot run

`compile_sqlalchemy_statement` raises `ValueError` when a CTE wraps `INSERT`, `UPDATE`
or `DELETE` and the dialect is SQLite, MySQL or SQL Server. It inspects the SQLAlchemy
object, so the error comes at compile time instead of a syntax error from the database.

## Alternatives

- **Several statements in one SQL string.** The API would have to split the text,
  which is the parsing ADR 0007 removed.
- **Separate operations in sequence.** Not atomic.
- **A route for each client's write.** Ties the API to one client's tables.
- **Guards as SQL that raises.** SQLite raises only inside triggers, and the caller
  could not tell the failure from a database error.

## Consequences

- Clients write several tables atomically on the local runtime with the same code
  path they use on PostgreSQL, sending a list where PostgreSQL takes one statement.
- A PostgreSQL client that puts `COMMIT` in a list loses its own atomicity and gets
  `compiled_sql_transaction_ended`.
- The API holds one write transaction for up to the whole time limit, as a long single
  statement already can.
