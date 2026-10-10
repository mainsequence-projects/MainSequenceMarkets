# Initialize and upgrade the runtime database

The runtime database stores MetaTables' system tables, including `data_source`,
alongside user tables. There is no separate catalog connection to configure. API
startup never runs Alembic in either mode.

A hosted API's deployment initializes and upgrades its declared database: before
every rollout, the `migrate-system` Job runs `metatables runtime upgrade` from the
new image, and a failure blocks the rollout. Settings is read-only in Hosted mode.
See [the deployment gate](hosted-runtime.md#deployment-gate) and
[ADR 0014](../adr/api/0014-main-sequence-release-jobs-and-production-migrations.md).

The deployment gate checks revisions and registration during preflight, then
validates the full system schema once inside the migration runner, including when
the database is already current. Registration and permission setup finish under
the same bootstrap lock. Schema reflection is batched across the required tables;
the job logs the number of tables validated and elapsed time. Startup and explicit
activation still perform their own fresh schema validation.

Local mode initializes its SQLite file explicitly in Settings:

1. Open **Settings**. Local mode prefills the single local SQLite runtime file,
   shared across Git branches. Click **Check DataSource**.
2. For an empty or outdated file, click **Run MetaTables migrations**, or run
   `metatables --local runtime initialize`. This explicitly runs the packaged
   Alembic history. After success, the API saves the file as the runtime
   DataSource inside the newly initialized catalog.
3. For an already initialized compatible file, click **Use this DataSource**.
   Selection verifies its schema and registration without executing migrations.

A runtime database reopens on restart only when its migration revision and
required system tables and columns are compatible. Unknown revisions and schema
drift block activation. An existing revision marker alone is insufficient when
required tables are missing. Migration failure keeps normal application routes
unavailable. Local Settings remains accessible for correction and retry; in Hosted,
the next deployment retries. A completed schema with an unfinished source
registration can be retried without recreating tables.

The API owns these endpoints:

| Endpoint | Action |
| --- | --- |
| `GET /runtime-context/` | Read runtime and bootstrap status, including before any catalog exists. |
| `GET/POST /data-sources/` | List or register DataSources in the active runtime's catalog. Before activation the list is empty and registration is refused. |
| `POST /runtime-bootstrap/configure/` | Local: hold and inspect a proposed `{display_name, class_type, configuration}`. |
| `POST /runtime-bootstrap/migrate/` | Local: explicitly migrate, register the runtime source, and activate. |
| `POST /runtime-bootstrap/activate/` | Local: verify and select an already initialized database. |

In Hosted mode, configure, migrate and activate answer 409 and point to the
deployment's `runtime_database` declaration.

Configuration, migration, activation, and destruction require the platform admin
fact before catalog access. Any Organization admin can manage an existing source;
creator attribution does not confer exclusive control. Reconfiguration refuses concurrent requests, open
migration leases, unfinished updates and unresolved operations.

Migrations are packaged under `metatables.api.backend.migrations`; the ORM models live under
`metatables.api.backend.persistence.models`. System revisions use `metatables_catalog_version`.
User tables use their own [migration provider histories](../client/define-and-migrate-tables.md).
System table names cannot be registered as user MetaTables. Never use `create_all`
or stamp a revision to bypass initialization.

The **Migrations** section in Settings shows **Applied in database** and **Latest in
migration files**, plus pending revisions in application order. **Refresh runtime**
reads the database's current Alembic heads and the API's current migration files;
it does not apply migrations. An active DataSource can still have pending system
migrations. Unknown database revisions or failed reads show a comparison error
instead of claiming the database is up to date. Migrations apply only through the
explicit **Run MetaTables migrations** action in Local and the deployment's
migration Job in Hosted.

In Local mode, the selected SQLite file is saved after activation under the `local`
entry of `.local/runtime-data-sources.json`, next to the deployment configuration.
This locates the runtime on restart; resolved credentials are never saved there.
Use one API worker per local runtime instance and persist this private directory
across restarts. Initialization state is process-owned; do not distribute its requests
across independently configured workers. Hosted writes no such file: every pod and
the Job resolve the declaration and its Secret.

## Development schema baseline

The system schema starts at `0001_initial`, followed by `0002_security_model`
for Reader/Writer grants, live namespace inheritance, and audit history, then
`0003_run_log_capture` for nullable run capture references and
`0004_historical_run_graphs` for root membership, idempotent admission and saved
execution graphs. Log bodies remain in
local files or the platform log store. Existing current-chain databases upgrade
through the hosted deployment's migration Job, or **Run MetaTables migrations** in
Local Settings; this does not recreate their data.
The initial revision is an explicit schema snapshot, independent of future ORM
changes. The earlier development migration chain has been removed.

Databases created with that earlier chain require recreation. Select a fresh SQLite
file in Settings and run **MetaTables migrations**, or point the hosted runtime
Secret at an empty database and deploy the API.
Application migrations run through the client against their own revision history.
Preserve existing data or restore a reviewed backup before recreating a runtime.
An existing revision cannot be stamped to this baseline to bypass recreation.
Old databases remain untouched; there is no automatic reset or adoption command.

## Destroy a local development database

In Local mode, Settings offers **Destroy local database**. Review the selected path
and type `DESTROY` to confirm. This permanently removes its system records and user
data, SQLite sidecar files, workspace markers, and saved local selection. An older
adjacent `catalog.sqlite` / `tables.sqlite` pair is also removed when its markers
identify the same workspace. Unmarked files, another workspace's files, and symlinks
are rejected before any deletion.

The API closes its database connections and rejects destruction while requests,
migration connections, updates or unresolved operations are active. Hosted mode
does not offer this action. On success the selected path stays in memory and the
runtime returns to **migration required**. Click **Run MetaTables migrations** to
initialize it again; destruction never runs migrations automatically.

`POST /runtime-bootstrap/destroy-local/` accepts
`{"path": "/absolute/selected/file.sqlite", "confirmation": "DESTROY"}`. The path must
match the API's current candidate. It returns the normal bootstrap descriptor;
wrong mode returns 403, unsafe targets or busy runtimes return 409, and missing
confirmation returns 422.

When adding system schema changes, add a new immutable revision and test fresh and
populated upgrades on both SQLite and PostgreSQL. Back up the selected database before
upgrading; its system and application tables form one runtime backup unit.

## Security schema reconciliation

Revision `0002_security_model` maps direct/namespace view grants to Reader and edit
grants to Writer. It removes local Team-membership records and permanent copied
namespace grants. Each retired copy is logged as `retired_namespace_copy` in
`grant_audit`; current namespace grants supply live inheritance instead. Review
removed contributions and recover access through global Security when needed.
Independent direct grants are retained. Downgrade is refused because discarded
membership and copy history cannot be safely reconstructed; restore a reviewed
backup for rollback. See [the security model](../security/index.md).

## Bootstrap recovery and schema validation

Explicit initialization creates the reserved `metatables_bootstrap_progress` table
in the selected database before the system schema. Its versioned record binds
progress to that database and the packaged migration plan. Startup and selection
only inspect it. Existing current stores remain readable without creating it.

Transactional engines commit schema changes atomically. MySQL records each DDL or
data mutation's intent and acknowledged result on a dedicated connection. A retry
can skip acknowledged steps only after checking their latest schema postconditions.
A lost acknowledgement, changed binding, changed migration plan or schema drift
requires inspection and repair; the API does not stamp an unknown schema or replay
an uncertain write. Keep the runtime inactive until the discrepancy is resolved.
For disposable local development, Settings also provides Destroy local database.

Activation verifies required column types and nullability, primary and foreign
keys, checks, unique constraints and indexes, then verifies the runtime DataSource
record. Catalog identifiers use case-sensitive Unicode storage on MySQL and
SQL Server. SQL Server retains foreign-key checks while the shared catalog unit
of work applies cascading deletion and nullification before deleting parents.
Raw SQL deletion of system records is not an alternative to the API.

Application providers declare `supported_dialects=("sqlite", "postgresql", "mysql",
"mssql")` only after their scripts have been tested on those engines. Existing
providers default to SQLite/PostgreSQL. An unsupported provider is rejected before
reservation or DDL. MySQL holds catalog admission on a separate transaction while
its migration connection performs DDL with implicit commits; an uncertain provider
migration remains in the physical-operation journal for reconciliation.

See [database contract testing](../contributing/database-backends.md) for the
reproducible Compose matrix used locally and in CI.

## Upload receipt revision

Revision `0008_upload_receipts`, after `0007_external_relation_names`, adds durable keys, payload digests, actor/source/table/update identities, fenced attempt IDs, outcome status, timestamps, and operator evidence. It stores no uploaded rows. Receipts intentionally have no cascading table foreign key: deleting a table must not make its keys reusable. Downgrading this revision is irreversible; use a reviewed catalog backup. See [recovery and retention](recovery-and-observability.md#data-upload-receipts).
