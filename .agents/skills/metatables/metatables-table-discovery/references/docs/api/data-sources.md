# DataSource management API

The API owns one injected [CredentialStore](../adr/api/0009-shared-credential-store.md).
Hosted mode uses Main Sequence SDK Secrets with their existing managed protection.
Local mode uses encrypted credential records in the MetaTables catalog and a native
keyring or protected-file key provider. It requires no hosted Secret context.

The Python client and Admin site use the same registration endpoints. A write-only
`password` is persisted by the selected store; only its opaque UUID is saved in
`configuration.password_secret_uid`. That existing field name stays compatible.
The API resolves the credential through the same store when opening a connection.

PostgreSQL, TimescaleDB, MySQL and Microsoft SQL Server (MSSQL) support this
management lifecycle and the complete table workflow on the selected runtime source. See the [engine support matrix](../concepts/data-sources.md#supported-engines-and-operations).
The caller selects `class_type`; the API does not infer an engine from the host
name or inspect a database server to choose one. Validation connects with the
selected driver and runs `SELECT 1`. For `timescale_db`, that probe does not
verify that the TimescaleDB extension is installed in the target database.

The **Data Sources** section and `/data-sources/` expose one registration workflow.
Registrations live only in the active runtime's catalog. Before the runtime is
active, the list is empty and registration is refused: Hosted answers 409 until the
deployment has initialized its runtime database, and Local requires system migrations
in Settings first. The runtime DataSource appears in the same list and remains
runtime-managed with `can_manage: false`. Its storage and access cannot be changed
through this API.

External registration, editing, validation and removal require Organization admin
access but do not depend on the runtime database's SQL permission initialization.
These operations do not reconcile runtime table grants. If database permissions
need repair in Security, caller queries remain blocked while external DataSource
management remains available.

Each runtime mode lists only its own catalog's registrations. The hosted runtime
DataSource is declared by the API's deployment, not chosen from this list; see
[hosted runtime](../operations/hosted-runtime.md).

The active runtime DataSource hosts the system catalog and default application
tables. It exposes `can_manage: false`; its configuration belongs to the deployment
declaration in Hosted and to Settings in Local. Other registrations cannot replace
it by setting `is_default`.
Hosted mode rejects injected SQLite catalog records with
`hosted_runtime_rejects_local_storage`. Execution remains bound to the selected
runtime DataSource; registering another database does not enable its table operations.

## Install drivers on the API server

PostgreSQL/TimescaleDB use the included psycopg2 driver. The package also includes
pyodbc for MSSQL; SQLite is built in. For MySQL, install its optional extra in
the environment running the API, using the same package revision as the API:

```sh
python -m pip install 'mainsequence-metatable[mysql]'
# From a source checkout instead:
python -m pip install -e '.[mysql]'
```

MSSQL also requires **Microsoft ODBC Driver 18 for SQL Server** and the operating
system's ODBC driver manager. Follow Microsoft's installation instructions for
[Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
or [macOS](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos).
The API uses the installed driver name `ODBC Driver 18 for SQL Server`.
The Admin browser and Python HTTP client do not connect to databases directly.

The API host must reach the database. Hosted UUIDs resolve through the ordinary SDK
Secret context. Local UUIDs resolve in the catalog and require its original encryption
keys; local saves and validation make no platform Secret calls. See
[local credential configuration and recovery](../operations/local-runtime.md#local-credentials).

## Routes

| Method and path | Behavior |
| --- | --- |
| `GET /data-sources/` | List public metadata; `search` matches display names, `limit` is 1–500 and `offset` starts at zero. |
| `POST /data-sources/` | Create a registration; returns `201`. Does not connect to the database. |
| `GET /data-sources/{uid}/` | Read one registration. |
| `GET /data-sources/{source_uid}/relations/` | Admin-only discovery of visible table/view names in the default or requested `physical_schema`, with existing import status; performs no writes. |
| `PATCH /data-sources/{uid}/` | Change display name, access mode, default, or replace the complete connection configuration. |
| `POST /data-sources/{uid}/validate/` | Resolve credentials, connect using the selected engine, run `SELECT 1`, and close the connection. |
| `DELETE /data-sources/{uid}/` | Remove an unused, nondefault registration; returns `204`. Preserves physical data and Secrets. |

Responses include `uid`, `display_name`, `class_type`, `status`,
`storage_access_mode`, `is_default`, `can_manage`, `created_at`, and `configuration`. Only Organization admins receive configuration and Secret UIDs;
others receive `configuration: null` and `can_manage: false`. SQLite configuration
is always hidden and its file path is controlled by the launcher.

Creation requires `display_name`, `class_type`, and `configuration`. The Admin
form asks for a password; users do not need to create a Secret first. API clients
may instead supply an existing `configuration.password_secret_uid`.
`PATCH` accepts a new write-only `password` to replace that reference. Omitting
the password preserves the existing reference. Password whitespace is preserved,
and plaintext never appears in registration responses or saved registrations.
`storage_access_mode` defaults to `read_write`; `is_default` defaults to `false`.
Use `read_only` to block table writes and `disabled` to block connections and
credential resolution. A configured `AVAILABLE` status is not a continuous health
check: explicitly validate after registration or a configuration change.

## Connection configuration

All remote engines require `host`, `database_name`, and `database_user`.
`password_secret_uid` is an opaque CredentialStore UUID: a local encrypted record
or a hosted SDK Secret. For the hosted runtime it is the UID of the URI Secret,
whose login password is required even where the database permits passwordless
administrator connections: caller credentials are derived from it.
The write-only password is a top-level request field, separate from persistent
`configuration`. Plaintext passwords inside configuration, connection strings,
arbitrary driver options, and unknown fields are rejected. Ports must be between
1 and 65535. The API fails without saving a DataSource if it cannot create its
credential. Local credentials roll back with their DataSource transaction. Hosted
failures attempt compensation for newly created SDK Secrets only. Successful
replacement preserves the previous credential; cleanup is explicit.

| Engine | Options and defaults |
| --- | --- |
| `postgresql`, `timescale_db` | `port: 5432`, `default_schema: "public"`, `ssl_mode: "require"`; TLS modes: `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`. |
| `mysql` | `port: 3306`, `default_schema` equal to `database_name`, `default_charset: "utf8mb4"`, `ssl_mode: "verify-full"`; TLS modes: `disable`, `require`, `verify-ca`, `verify-full`. Character sets: `utf8mb4`, `utf8`, `latin1`, `ascii`. |
| `mssql` | `port: 1433`, `default_schema: "dbo"`, `encrypt: true`, `trust_server_certificate: false`. Uses SQL Server username/password credentials. |

PostgreSQL and MySQL accept optional `tls_ca_secret_uid`,
`tls_certificate_secret_uid`, and `tls_key_secret_uid`. Supply client certificate
and key together. The API also accepts write-only top-level `tls_ca`,
`tls_certificate` and `tls_key` fields to create or replace those references. These reference PEM credentials resolved through the selected store; temporary private files are
removed when the connection closes. `verify-full` verifies certificate identity;
`require` requests encryption without certificate identity verification. MySQL
validation also checks the negotiated TLS cipher and rejects an unencrypted session.

MSSQL uses the API server's certificate trust store. `encrypt: true` and
`trust_server_certificate: false` require encrypted, certificate-verified
connections. MSSQL does not accept PostgreSQL TLS fields. See Microsoft's
[connection string documentation](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/connection-string-keywords-and-data-source-names-dsns)
and the [PyMySQL connection options](https://pymysql.readthedocs.io/en/latest/modules/connections.html).

## Examples and Admin workflow

The [DataSource guide](../concepts/data-sources.md) includes Python registrations
for each engine. The [examples folder](../examples/data_sources/README.md) supplies
JSON bodies and a small client script. Those same bodies can be submitted to
`POST /data-sources/` using the deployment's normal ingress credentials.

In MetaTables Admin, open **Data Sources → Register source**, choose an engine,
fill in connection settings and Secret UIDs, and save. The form supplies the
engine's defaults and only its supported TLS options. Open the saved source to
validate, edit, disable, or remove it. The hosted runtime DataSource is declared by the deployment, not registered here. All hosted engines use the same bootstrap and table APIs.

For a configuration edit, submit the complete configuration rather than a nested
partial patch. The registration's engine cannot change; create another registration
for a different engine. The default schema of a referenced source cannot change.

## Failures and protections

- `403`: another caller tried to manage the registration or replace its default.
- `404`: the registration does not exist.
- `409`: a source is disabled during validation, referenced/default during deletion,
  has a protected schema, the
  operation conflicts with the runtime's fixed storage binding, or a Hosted
  registration arrives before the runtime is active.
- `422`: invalid engine, configuration, field type, or Secret UID.
- `503`: connection or credential storage failed, including unavailable drivers,
  keys, catalog initialization or hosted Secrets. Runtime-context reports the
  nonsecret credential-store provider, status and actionable error.
  Driver diagnostics and credentials are not returned. Validation failure records
  `FAILED`; a later successful validation records `AVAILABLE`.

Remote probes use ten-second connection/query timeouts. Default replacement and
deletion protections are checked by the API, including pending physical operations.
Removing a registration never provisions, drops or deletes a database or Secret.

## Database privileges and SQL behavior

The runtime database must already exist. Its API database user needs permission
to create and alter system tables, constraints and indexes during explicit setup,
and the corresponding privileges for approved application migrations. MySQL 8.4
uses the selected database as its SQL schema. SQL Server 2022 uses `dbo` for the
system schema; application providers may use approved schemas in that database.

The API database login manages native caller identities as well as schema. PostgreSQL
requires `CREATEROLE`, permission to create the `metatables` schema in the runtime
database and tables in its default schema, and management rights on `mt_owner` if
it already exists. It does not need to own the database. It stores the catalog in the private `metatables`
schema. MySQL requires account/role administration, privilege disclosure and grant
rights on the selected database, `TRIGGER` visibility, and permission to cancel
other caller sessions. SQL Server requires login/user/role administration,
`VIEW DEFINITION` and grant management. Managed database services must provide
these capabilities; missing permissions leave caller SQL disabled.

Preparing the database, its login and these privileges is the database
administrator's responsibility. On every deployment, the hosted migration Job checks
the PostgreSQL requirements before any migration runs: `CREATEROLE`, `CREATE` on the
database or ownership of the `metatables` schema, and `CREATE` on the default schema.
A missing one fails the Job with the reason, for example `metatables lacks
CREATEROLE`; nothing is written and the API does not roll out. The hosted login is
always `metatables`, one per database server; see
[Set up a hosted runtime database](../operations/hosted-runtime.md#set-up-a-hosted-runtime-database).

The database may be shared with other applications. Setup revokes `PUBLIC` access
only on objects MetaTables owns: its `metatables` schema, the tables it manages and
the roles it creates. Database-wide defaults and other owners' objects, including
extensions such as TimescaleDB and pgvector, are the database administrator's
responsibility.

Hosted sources require a password Secret to derive per-User database credentials.
MySQL global mandatory roles are unsupported. Registration admits ordinary tables
only; it does not transfer external ownership. Privileged routines and triggers
must not provide owner access. Setup and schema changes verify these safeguards,
while the database checks permissions during each query. See
[security](../security/index.md).

Registered foreign keys may use any referential action, including `CASCADE`,
`SET NULL` and `SET DEFAULT`. The database runs a cascade as the table owner,
authorized by the referencing table's own foreign key, so writing a referenced
table needs no access to the tables that reference it. Local SQLite runtimes are
the exception: SQLite's authorizer cannot tell a foreign-key action from the
caller's own statement, so a local delete or key update on a referenced table
fails unless the caller can access every referencing table. See
[ADR 0007](../adr/api/0007-database-enforced-table-access.md#sqlite) and
[ADR 0016](../adr/api/0016-impact-preflight.md).

MySQL uses `pyformat` parameters and SQL Server uses ordered `qmark` parameters.
Both share the normal compiled SQL endpoint and limits. SQL Server upserts use a
parameterized `MERGE` with `HOLDLOCK`; MySQL uses `ON DUPLICATE KEY UPDATE`.
Timescale extension operations check the installed extension in the selected
PostgreSQL database at invocation. Registering `timescale_db` does not establish
that the extension exists. User roles and grants authorize operations; database
features are resolved by the bound backend. Responses contain no static
`supports_*` list and the Admin detail view has no capability table. Time-index
tables on `timescale_db` are hypertables owned by the API's login and can carry
[compression and retention policies](time-index-and-updates.md#timescaledb-policies).
