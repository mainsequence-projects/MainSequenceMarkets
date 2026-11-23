# ADR 0026: Atomic statement lists

Status: Accepted.

Implementation status: implemented on development for 0.1.60. SQLite is tested in
process, both on a source's own connection and on the local runtime's borrowed request
transaction. The PostgreSQL path has not been run: its end-to-end test is written but
skips without the disposable cluster of `scripts/test_postgresql.py`. MySQL and SQL
Server refuse statement lists. The amendment on time-index statistics (2026-11-19) is
implemented for 0.1.69 and tested the same way: SQLite in process, PostgreSQL not run.
The amendment on SQLite parameters (2026-11-19) is implemented for 0.1.71 and tested in
process and through the local API. The amendment on MySQL and SQL Server statistics
(2026-11-23) is implemented for 0.1.76 and tested in process with stand-ins for both
engines; neither engine has been run.

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

### Writes keep time-index statistics (amended 2026-11-19)

Issue: [MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117).

A time-index table's stored statistics (`index_stats`) tell its updaters where to
resume: each coordinate's latest time. The chunk insert and `delete-after-date`
replace them with a rebuild from the table's rows. Compiled SQL left them alone, so a
list that deleted every row of a coordinate kept that coordinate's progress; when the
coordinate was written again, its updater resumed after the deleted rows and never
wrote the history before them.

Now every compiled write, a statement list or a write through `execute-operation`,
rebuilds the statistics of each time-index table it changed, with the function the
chunk insert and the tail delete use. Inserts and updates are covered with deletes.

**Which tables.** A request names no tables (ADR 0007), so the API asks the engine,
before the commit, what the transaction wrote; it never reads the SQL:

- **PostgreSQL:** the relations the transaction holds in `ROW EXCLUSIVE` mode, from
  `pg_locks`. `INSERT`, `UPDATE`, `DELETE` and `MERGE` take that lock on their target,
  a hypertable's statement on the hypertable itself, and a foreign key's action on
  the table it changes. One query per write.
- **SQLite:** the engine authorizer, which SQLite asks about every table a statement
  writes as it compiles it, foreign-key actions included.
- **MySQL and SQL Server** cannot tell; the API counts every table the caller may
  write (amended 2026-11-23, below).

Both report the tables a write could change, so a table can be rebuilt when no row
of it changed. The API keeps those that are active time-index tables of the DataSource
and skips a table whose stored statistics are empty: nothing stored can be stale, and
its first chunk insert builds them. A table written only through compiled SQL usually
keeps none, so its writes pay no rebuild. Reads ask nothing.

**When.** On the local runtime the tables and the catalog share the request's SQLite
transaction: the rebuild reads the uncommitted rows and commits with them.

On PostgreSQL the rebuild runs after the physical commit, as the caller's database
identity in a read-only transaction, while it holds the table's catalog row lock; each
table commits on its own. Inside the physical transaction a rebuild would need the
`SHARE ROW EXCLUSIVE` lock the chunk insert takes before it writes. A list can only
take it after its statements hold `ROW EXCLUSIVE`, so two lists writing one table
would deadlock; without it, the rebuild can miss a concurrent list's commit and then
overwrite newer statistics. Every statistics writer holds the catalog row lock while
it rebuilds and stores, so a rebuild after the commit sees every commit before it.
Until it finishes, the stored statistics still describe the rows before the write.

**A rebuild never fails the write.** A write's response carries `index_statistics`:
each rebuilt table's UID with `rebuilt`, or with why its statistics stayed as they were:

- `too_many_index_coordinates`: more than 10,000 coordinates, the limit of every
  rebuild. The chunk insert refuses its whole write instead. A compiled write does
  not, because tables written only through compiled SQL grow past the limit, one
  coordinate per account and asset or per position set, and refusing would break
  writes that work today.
- `not_readable`: the caller cannot read the table, which only a foreign key's action
  lets it write.
- `reconciliation_required`: the rebuild or the catalog write failed after the write
  committed. The chunk insert answers 503 here, because its receipt makes a retry
  safe; a list has no receipt, and an error would invite running its statements twice.

A table left unchanged is corrected by its next rebuild: a chunk insert, a
`delete-after-date`, or a later compiled write.

### SQLite statements bind by position (amended 2026-11-19)

Issue: [MetaTables#121](https://github.com/mainsequence-projects/MetaTables/issues/121).

A statement list near SQLite's 32,766-value limit ran past its deadline before it read a
row. SQLite numbers each named parameter by searching the names before it, so preparing a
statement takes time quadratic in its values, and CPython's `sqlite3` searches again to
bind a dict. A 26,212-value statement took 6.4 s of CPU to prepare; with `?` it took
milliseconds.

SQLite uses the `qmark` paramstyle, as SQL Server does. The client compiles plain `?`
placeholders and sends the values as a list in order, repeating a value wherever the
statement uses its parameter again, and the API binds them by position. The runtime
context reports `qmark` for SQLite, and the API refuses a SQLite statement in any other
paramstyle with `compiled_sql_dialect_mismatch`.

- Numbered placeholders (`?NNN`, `:1`) are not enough: on CPython 3.12 and later,
  binding by position still looks up each parameter's name, and a numbered parameter has
  one.
- Rewriting named placeholders to `?` in the API was rejected. The API submits caller
  SQL unchanged (ADR 0007), and a rewrite needs a scanner that skips string literals,
  quoted identifiers and comments.
- A client and an API of different versions disagree on SQLite's paramstyle. A SQLite
  runtime is always local and normally runs from the client's own installation, so they
  differ only when a local API runs from another one. The client then says to install
  the API's version; an older client gets `compiled_sql_dialect_mismatch`.

### MySQL and SQL Server rebuild what the caller may write (amended 2026-11-23)

Issue: [MetaTables#141](https://github.com/mainsequence-projects/MetaTables/issues/141).

MySQL and SQL Server cannot report what a transaction wrote, so a compiled write there
left every table's statistics as they were: #117 on those engines. When an engine cannot
tell, the API now counts every time-index table the caller's database identity may
write. It rebuilds each one that keeps statistics after the commit, as on PostgreSQL:
as the caller, in a read-only transaction, with the table built from the catalog's
column types.

- It needs no privilege beyond the caller's own. Each engine's lock view would name
  exactly the tables written, but SQL Server's, `sys.dm_tran_locks`, needs a
  server-level permission that callers' logins do not hold.
- Each compiled write rebuilds those tables whether or not it changed them. An
  organization admin may write every table, so an admin's write rebuilds every
  time-index table of the DataSource that keeps statistics.
- A table changed only through a foreign key's action that the caller cannot write
  keeps its statistics until its next rebuild.

## Alternatives

- **Several statements in one SQL string.** The API would have to split the text,
  which is the parsing ADR 0007 removed.
- **Separate operations in sequence.** Not atomic.
- **A route for each client's write.** Ties the API to one client's tables.
- **Guards as SQL that raises.** SQLite raises only inside triggers, and the caller
  could not tell the failure from a database error.
- **The client names the tables a list writes.** The compiler could read them from
  the SQLAlchemy objects, but not from text SQL or a foreign key's action, and a
  client that names none leaves the statistics stale again.
- **A statistics refresh the client calls after the commit.** That is what clients
  did with `delete-after-date`: one more request per table, and a failure between
  the two requests leaves the statistics stale.

## Consequences

- Clients write several tables atomically on the local runtime with the same code
  path they use on PostgreSQL, sending a list where PostgreSQL takes one statement.
- A PostgreSQL client that puts `COMMIT` in a list loses its own atomicity and gets
  `compiled_sql_transaction_ended`.
- The API holds one write transaction for up to the whole time limit, as a long single
  statement already can.
- A compiled write that changes a time-index table with stored statistics pays one
  whole-table `GROUP BY` per such table, as each chunk insert does; on PostgreSQL it
  runs after the commit, within the request's deadline.
- Clients no longer refresh statistics after a compiled write. One that must not go
  on with stale statistics checks `index_statistics` for an outcome other than
  `rebuilt`.
- MySQL and SQL Server cannot report what a write changed: a compiled write there
  rebuilds every time-index table the caller may write that keeps statistics.
