# ADR 0025: Application-encrypted columns

Status: Accepted.

Implementation status: implemented on development. `metatables.EncryptedString`,
contract extraction and the compiled-SQL, frame and row paths in the client; the
catalog's column contract, finalization, the plaintext guard on uploads, table
responses, search documents and `describe_table` in the API; the `metatables
encryption` commands; the Analyst skills. Verified on the SQLite runtime
(`tests/e2e/test_encrypted_columns.py`) and in unit tests; the container engine
matrix, the Admin's lock mark and a hosted deployment are pending.

Owner: MetaTables client, which encrypts and decrypts. The API records the column's
protection in the catalog and never holds a key. The Analyst and the Admin show the
protection and never show plaintext.

Related decisions: [ADR 0007](../api/0007-database-enforced-table-access.md) (the
database enforces grants; the API never parses SQL), [ADR 0009](../api/0009-shared-credential-store.md)
(hosted credentials are SDK Secrets, with no second encryption layer),
[ADR 0013](../api/0013-application-owned-migrations.md) (applications own their models
and migrations), [ADR 0020](../agent/0020-analyst-reads-as-its-requester.md) (the Analyst
reads only as its requester) and [ADR 0024](../api/0024-namespace-and-table-access-roles.md)
(roles; admins hold every action, data included).

## Context

Applications keep passwords, API keys, tokens and similar values in MetaTables tables:
a column of an account table, a credential of an external system an updater talks to.
Today such a column is plaintext in the database, so its value reaches everyone the
access model lets read the table:

- every person, Team or workload with `data_viewer` or above on the table or its
  namespace, through `read_rows`, `run_query`, compiled SQL and the Admin's data grid;
- every Organization admin, who holds every action on every table (ADR 0024);
- every person who asks the Analyst about the table, since it reads as them (ADR 0020);
- whoever operates the database or holds its backups, since the `metatables` login
  owns the tables (ADR 0007).

MetaTables access is deliberately coarse: `data_viewer` reads the whole row, and an
admin reads everything. That is right for data and wrong for a password. A password
should be readable by the application that stores it and by nothing else, and sharing
the table, which is normal, must not share the password.

The platform already has the right primitive. A Main Sequence Secret lives in an
Environment, is granted to a workload in its workflow file (`access.secrets`, policy
`value_reader`) and is read by name with `Secret.get(name=...)`, exactly as the API
reads its runtime database URI. Which workloads may read a Secret is decided by the
people who manage it, outside MetaTables. The requirement is therefore: a column type
whose values are encrypted with a key that is one Secret per application.

## Decision

### The core model: two gates, two owners

A protected value is readable only by a caller who passes both gates:

| Gate | Decided by | Question it answers |
| --- | --- | --- |
| The table grant | MetaTables (ADR 0024) | May this caller read the ciphertext? |
| The Secret grant | The platform, through the application's workflow | May this caller turn it into plaintext? |

MetaTables keeps deciding the first gate and never touches the second. The key is a
Secret the application owns; MetaTables stores a name, never a value. The API, the
Admin, the Analyst and the database see ciphertext only. An Organization admin of
MetaTables reads the ciphertext like anyone else. Sharing a table shares nothing
protected; granting the Secret to a second workload is a separate, visible decision of
the people who manage it.

### Encryption happens in the application process

The client encrypts a value before it leaves the application and decrypts it after it
arrives, with the key resolved from the Secret in that same process. Nothing between
the application and the database can decrypt, because nothing between them holds the
key.

The three places this could happen were weighed:

| Where | Why not |
| --- | --- |
| **The API** | It would have to read every application's Secret, so the API workload becomes the one identity that decrypts everything, which is the opposite of one key per application. It also cannot decrypt SQL results without knowing which result columns came from which table column, and ADR 0007 forbids parsing SQL. |
| **The database** (`pgcrypto`) | The key travels inside SQL text, so it appears in statement logs and `pg_stat_statements`; it exists on PostgreSQL only, while MetaTables supports five engines; and the database is one of the parties the value should be hidden from. |
| **The application process** (chosen) | The key stays where the Secret is granted. Every other party sees an opaque string. Works on every engine, since the column is text. |

### The column type

`metatables.EncryptedString(secret="LEDGER_DATA_KEY")` is a SQLAlchemy type for
application models (ADR 0013). It is a text column in the database. Declaring it:

```python
class Account(PlatformManagedMetaTable, Base):
    ...
    api_key: Mapped[str | None] = mapped_column(
        EncryptedString(secret="LEDGER_DATA_KEY"),
        info={"label": "API key", "description": "Key the collector presents to the broker."},
    )
```

- `secret` names the Environment Secret that holds the application's key. One
  application declares one Secret and reuses it on every protected column. The
  workflow file grants it to the workloads that need it:

  ```yaml
  access:
    secrets:
      - name: LEDGER_DATA_KEY
        policy: value_reader
  ```

- The column is `TEXT` on every engine; the envelope is ASCII. Autogeneration renders
  the column as `sa.Text()`, so revisions stay plain and reviewable and never import
  the type.
- Only text values are accepted. An application that protects structured data
  serializes it first. `None` stays `NULL`.
- The column cannot be a primary key, a unique key, a foreign key, a time index, a
  grain or index column (`__index_names__`), or carry a server default. Contract
  extraction refuses these: an encrypted value is random on every write, so equality
  on it means nothing.

The catalog records the protection in the column contract: `encryption: {"secret":
"LEDGER_DATA_KEY"}` on `MetaTableColumnContract`, carried into `ColumnMetaData` and
`describe_table`. The name of the Secret is not sensitive; it tells a reader which
Secret to ask for.

### What is stored

Each value is an envelope string, `mt1.<key id>.<base64url(nonce ‖ ciphertext ‖ tag)>`,
produced by AES-256-GCM with a fresh 96-bit nonce per write, the same primitive and
library ADR 0009 chose. The associated data is the physical table name and column
name, which the platform mixins set on the type when the model's table is built
(`__table_cls__`), so a ciphertext decrypts only in the column it was written to.
A tampered or moved value fails to decrypt and returns no partial plaintext.

The envelope is self-describing: a reader needs only the Secret the catalog names.

### The key Secret

The Secret's value is a keyring, so rotation never needs a migration:

```json
{"active": "2026-10", "keys": {"2026-10": "<base64, 32 bytes>"}}
```

- Writes use `active`; reads use the key id in the envelope. A value written under an
  older key still reads while that key is in the ring.
- `metatables encryption new-keyring` prints a fresh keyring and
  `metatables encryption rotate` prints the same ring with a new active key. The
  person creates or updates the Secret themselves, in Command Center or with
  `mainsequence secrets create`; the client never creates or changes a Secret, as the
  Analyst skills already rule for a person's Secret.
- `metatables encryption re-encrypt --table <uid>` rewrites every row under the
  active key, in bounded batches, as a Job of the application. After it completes the
  old key can be dropped from the ring.
- The Secret need not exist when the column is migrated. Alembic emits a text column
  and finalization records the Secret's name without resolving it, so migrations and
  the migration Job need no access to it. The key is first needed when a row is
  written or read, including by a data migration that backfills the column.
- The client reads the Secret once per process and keeps it in memory only. A missing
  Secret, or one the caller may not read, fails the write or the read with a clear
  error that names the Secret; it never writes plaintext and never substitutes an
  empty value.

### Client surfaces

| Path | Behavior |
| --- | --- |
| ORM and compiled SQL through the model's column | The type encrypts bound values and decrypts result columns of that type. The compiler applies the type's bind processing on every dialect, so `where(accounts.c.api_key == x)` encrypts `x` (and matches nothing, by design). |
| Frame writes (`insert_data_into_table`, upserts, updaters) | The client reads the table's column contracts it already fetches, encrypts the protected columns of the frame before upload and refuses a frame that carries a protected column it cannot encrypt. The API's upload route refuses plaintext in an encrypted column, so an older client cannot write one in the clear. |
| Frame and row reads (`read_rows`, `get_data_between_dates`, updater inputs) | Decrypts protected columns when the process can read the Secret; otherwise returns the envelope unchanged and marks the column as undecrypted in the result's metadata, so a reader without the Secret still gets the rest of the row. |
| Raw SQL (`run_query`, `execute_operation`) | Returns envelopes as the API sends them. `metatables.decrypt_values(values, secret=..., table=..., column=...)` decrypts a column of a result by hand. |
| Local mode | The same: the client reads the Secret as the developer through the SDK. Tests inject a keyring without the platform. |

### What the API, the Admin and the Analyst do

- The API validates the contract rules above at finalization and stores the
  protection. It never reads a key Secret and has no decrypting route. Requests for a
  plaintext view in the Admin are refused by design: the Admin shows the column with a
  lock and the Secret's name, and its grid shows envelopes.
- `describe_table` and the table search document mark the column as encrypted and say
  that its values cannot be read, filtered or compared in SQL. The `discover-tables`
  and `analyze-with-sql` skills tell the Analyst to say so rather than query it.
- Statistics, previews and exports treat the column as text and so show envelopes.

## What this protects, and what it does not

Protected against: table readers without the Secret, Organization admins of
MetaTables, Analyst users, the Admin, API logs and error bodies, database operators and
backups, and anyone who obtains a dump of the table.

Not protected against:

- anyone who holds `value_reader` on the Secret and `data_viewer` on the table, which
  is the intended reader;
- compromise of a process that holds the key;
- the people who manage the application's workload, who can change its workflow to
  read the Secret elsewhere. This is the platform's trust boundary for Secrets and is
  not changed here;
- a `data_writer` copying an envelope from one row to another of the same column.
  The envelope is bound to the column, not the row. An application for which this
  matters includes the row's identity inside the plaintext and checks it on read.

Equality lookups on a protected value are impossible by design. An application that
must find a row by a secret value stores a separate keyed hash of it; that is a later
decision, not part of this one.

## Alternatives rejected

- **Column-level database privileges** (`GRANT SELECT (col)`): keeps plaintext in the
  database and so hides nothing from admins, operators or backups; breaks `SELECT *`
  for everyone without the privilege; absent on SQLite.
- **One Secret per table or per column**: multiplies workflow grants and rotation work
  for no isolation gain, since one application reads all of them anyway. The
  application is the deployment and permission unit on the platform, so its key is too.
- **The API decrypts for readers who hold the Secret**: would need the API to read
  Secrets as the requester on every row read and to know result-column provenance for
  SQL. Rejected with API-side encryption above; the Python client is the only
  decrypting surface.
- **Deterministic encryption** to allow equality: leaks equal values and enables
  guessing of low-entropy ones such as PINs. Random nonces, with a separate hash where
  lookup is needed.

## Consequences

- An application protects a column by changing its model and granting itself one
  Secret; no MetaTables administrator is involved and no API deployment is needed.
- A protected column costs about 70 bytes plus the value, and loses indexing, equality
  and SQL inspection. It is for credentials and the like, not for bulk data.
- `cryptography` becomes a client dependency (it is already an API dependency, ADR 0009).
- Reads by applications that hold `data_viewer` but not the Secret keep working and
  receive envelopes; they must not assume the column is plaintext.
- A lost key loses the values. The Secret is the only copy, and the platform's Secret
  backup is the recovery path.

## Verification

The proof is:

- the API, given a protected column, stores the contract and refuses the forbidden
  roles (key, index, grain, default), and no API route or log carries a key;
- the client round-trips values on every engine of the matrix, fails closed without
  the Secret, refuses a frame it cannot encrypt, decrypts only in the column a value
  was written to, and reads old keys after rotation;
- `run_query`, previews, statistics, the Admin grid and `describe_table` show
  envelopes and the protection mark, never plaintext;
- re-encryption rewrites every row under the active key and is resumable.
