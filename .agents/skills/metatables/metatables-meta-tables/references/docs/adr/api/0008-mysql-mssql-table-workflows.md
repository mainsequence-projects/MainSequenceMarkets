# ADR 0008: Implement MySQL and MSSQL table workflows

> Amendment (2026-10-01): [ADR 0013](0013-application-owned-migrations.md) establishes application-owned
> client Alembic execution using the configured environment connection. Its DDL
> privileges belong to the environment database role. It supersedes this ADR's
> conflicting application-migration execution and credential restrictions;
> governed API operations and MetaTables system migrations remain separate.


Date: 2026-09-29

Status: Accepted.

Clarified 2026-10-01 (MetaTables #9): the compiler obtains the runtime DataSource
UID, dialect and parameter style together, with no caller configuration. The
default path covers PostgreSQL/TimescaleDB, SQLite, MySQL and MSSQL. An explicit
different source must not inherit the runtime source's dialect. Offline explicit
UID/dialect compilation remains supported but does not relax API execution
binding. Optional external bounded reads retain ADR 0010's source selection.

Amended 2026-09-29: one selected execution DataSource, explicit workflow and
transaction ownership, first-bootstrap recovery, and a Compose database test suite.

Amended 2026-09-30: remove the generic DataSource feature flag layer; resolve
optional database features at runtime and retain existing roles/grants for authorization.

Amended 2026-09-30: backend verification is manual and local. The Compose runner
starts engines sequentially; GitHub Actions and merge gates exclude runtime tests.

Implementation status: implemented behind the shared backend contract. The
[database contract suite](../../contributing/database-backends.md) exercises all
five engines using the repository's Compose runner. MySQL and MSSQL use the same
Settings bootstrap, approved-provider, table and compiled SQL APIs.

Owner: MetaTables API. The Python client and MetaTables Admin must consume the
same API contract and support the new engine dialects.

Related decisions: [API ADR 0001: Unified API storage](0001-unified-api-storage-and-local-sqlite.md),
[API ADR 0004: Approved application migrations](0004-approved-application-migrations.md),
and [API ADR 0007: Database-enforced table access](0007-database-enforced-table-access.md).
This decision replaces ADR 0001's connection-only *end state* for MySQL and
MSSQL and its wording allowing execution against additional registered sources.
ADR 0001's one-API execution path, explicit Settings bootstrap and Secret ownership
still apply. ADR 0007 remains a separate proposed security change; it does not
block implementing this decision under the current authorization model.

Accepted follow-up, 2026-09-30: [ADR 0012](0012-bounded-data-transfer-and-safe-retries.md)
extends the backend execution and recovery contract to incremental reads and data
chunk receipts. Its concurrency changes retain explicit transaction
ownership and unknown-outcome reconciliation. Local verification is complete; hosted verification of the new transfer behavior remains pending.

## Context

`POST /data-sources/` accepts `mysql` and `mssql`, and validation opens their
connections and runs `SELECT 1`. At the time of the original decision, the
static feature registry declared no table support for either. The physical operations in `src/metatables/api/backend/integrations/`
use PostgreSQL or SQLite connections, SQL and introspection; they cannot act on
the registered MySQL or MSSQL source.

The gap extends beyond those operations. Hosted bootstrap and catalog engine
creation accept PostgreSQL/TimescaleDB only. Application migrations accept
PostgreSQL or SQLite. The compiled SQL request and runtime context know only
`postgresql` and `sqlite`; governed SQL assumes their parsing and database
scope rules. The client and Admin settings mirror those limits. A successful
registration therefore cannot be followed by the normal MetaTables table
lifecycle.

## Decision

### Complete the existing DataSource lifecycle

Implement MySQL and Microsoft SQL Server as fully interactive MetaTables
DataSources. Keep the existing registration, Secret references, validation and
DataSource UIDs. Extend the same API resources and application services used by
PostgreSQL, TimescaleDB and SQLite. Do not create engine-specific HTTP routes,
client database connections or a parallel catalog. Engine selection binds one
database backend under the shared authorization, contracts, operation journal
and recovery flow.

Both engines must support the ordinary table workflow: hosted Settings bootstrap
and catalog migrations; approved application migrations; managed table creation
and existing-table registration; physical introspection; governed SQL and
compiled select, insert, update, upsert and delete; queries and statistics;
time-index reads, chunk writes and update runs; and protected table deletion.
Namespace, grant, label, update and run-history API behavior stays the same for
all engines. Timescale-specific hypertables and policies remain specific to
TimescaleDB and do not define ordinary table parity.

### One selected DataSource and explicit table ownership

One API runtime binds one selected DataSource. Its system schema and managed
application tables reside in that database, and table operations use that same
binding. PostgreSQL, TimescaleDB, MySQL and MSSQL are hosted engine choices;
local mode continues to bind one SQLite file. Supporting an engine includes
creating MetaTables' complete system schema and constraints on a fresh database,
upgrading that schema, and supporting the full table lifecycle there.

Saved connection registrations may be candidates for explicit Settings selection;
they do not create additional execution bindings. An explicit DataSource UID or
table reference must match the active binding before physical access. Selecting
another initialized runtime follows the existing quiescent Settings transition;
it does not copy or migrate the previous runtime's catalog or table data. Catalog
transfer, cross-DataSource migrations and mixed-engine operations are outside scope.

Registering an existing table or view records and validates an externally owned
object in the selected DataSource. It retains `external_registered` ownership;
registration does not create, alter, adopt into managed migrations or delete that
physical object. Object type, grants and existing external-resource lifecycle
rules still govern supported operations. Managed creation and external registration
remain distinct workflows in shared services, using the same backend for physical
operations. Importing a definition is not a second runtime or a database-copy feature.

### One backend contract and one dispatch point

Introduce one internal `DatabaseBackend` contract and one registry keyed by
`DataSource.class_type`. The registry resolves an engine once when binding a
configured source, or once from a Settings candidate before its DataSource row
exists. Every API route and application service then calls the bound contract.
They must never choose an engine with their own `if class_type`, dialect fallback,
or PostgreSQL-by-default branch. Every operation receives the backend for the
active runtime binding; neither its engine nor its connection target can change
during the operation. That backend supplies all three facets for the selected
DataSource, including physical access to externally registered objects.

The contract is composed of three required facets, rather than one enormous
method list:

| Facet | Required operations | Owned by shared code |
| --- | --- | --- |
| `catalog` | Open the selected engine, implement catalog/bootstrap locks, inspect system objects and revision state, provide system-schema DDL and migration connections, and persist/read bootstrap progress. | Bootstrap state machine, Alembic orchestration, migration admission, runtime registration, journal transitions, reconciliation decisions and catalog models. |
| `tables` | Execute bounded physical operations: create and introspect objects; query, mutate and delete rows; time-index reads, writes and statistics; permitted physical table deletion. | Managed creation and external registration workflows, table identity and ownership, grants, limits, updater coordination and API responses. |
| `sql` | Report wire dialect and parameter style; bind/decode values and execute through restricted sessions as specified by ADR 0007. | Client SQLAlchemy compilation and the published compiled-operation contract. |
| `access` | Establish native permissions, mirror catalog grants, verify safeguards during setup/schema changes, and admit restricted caller sessions (ADR 0007). | Catalog grant authority, trusted caller facts and lifecycle admission. |

These are interface obligations for each supported backend. Engine-specific
implementations decide SQL syntax, driver calls and transaction mechanics within
the explicit ownership contract below. Shared services admit, orchestrate and
finalize operations, and represent their results. An adapter never chooses a
workflow state transition or marks a runtime ready. Both an existing
`RuntimeDataSource` and a pre-registration candidate use the existing validation
and Secret-resolution boundary; neither path accepts arbitrary connection
material from table-operation callers. Errors are mapped to shared, secret-safe
outcome codes at the contract boundary.

Conceptually, callers use the contract like this:

```python
backend = backend_for(source)  # bind the selected runtime source once
result = backend.sql.execute(identity=caller_identity, sql_text=sql, max_rows=100, offset=0)

# Before the runtime DataSource row exists; candidate is already validated:
backend = backend_for_engine(candidate)
bootstrap_runtime(candidate=candidate, backend=backend)  # shared service
```

`backend_for()` and `backend_for_engine()` are the only engine dispatch
functions over the same registry. The candidate entry point selects by its
`class_type` and binds its validated connection without requiring a catalog row.
Each returns the same typed `DatabaseBackend` interface. An unknown or incomplete
engine fails at binding; it does not fall through to PostgreSQL. The bound backend
carries the selected source and exposes engine-neutral result objects and safe
error codes. Table/SQL operations receive resolved identities and bounded commands, never
an unchecked relation name or a caller-supplied database URI.

Provide `SQLiteBackend`, `PostgreSQLBackend`, `MySQLBackend` and `MSSQLBackend`.
`TimescaleBackend` composes PostgreSQL's core implementation and adds its
optional extension operations. Shared code must not call a PostgreSQL helper
for MySQL or MSSQL by making a feature flag true. All backends satisfy the
same core contract. Remove the generic DataSource `supports_*` declarations,
response fields, admission checks and Admin capability table. Existing actor
roles and table/namespace grants authorize operations; `storage_access_mode`
remains an independent read-only/disabled connection constraint. Optional
database features, such as Timescale hypertables and policies, are resolved
at invocation against the selected DataSource through its backend. A registered
engine name cannot prove that an extension is installed. The backend registry is
authoritative for engine metadata exposed in `/runtime-context/`,
`/data-sources/`, OpenAPI and the client. Do not maintain separate hand-written
engine matrices in routes, Admin and documentation.

Refactor the current SQLite and PostgreSQL paths into this contract before
adding MySQL and MSSQL implementations. In particular, remove engine decisions
from `src/metatables/api/app/bootstrap.py`, `src/metatables/api/app/routes/application_migrations.py`,
`src/metatables/api/app/routes/table_sql.py`, `src/metatables/api/app/routes/runtime_context.py`, and
`src/metatables/api/backend/integrations/source_validation.py`; route existing SQLite and
PostgreSQL work through the bound backend in this first step, before implementing
MySQL or MSSQL table support. During the refactor, retain the existing MySQL/MSSQL
connection probes without pretending they satisfy the full backend contract.
Move the branches in `postgresql_*`
physical helpers and `src/metatables/api/backend/database_operations/runtime.py` into adapter
implementations or shared engine-neutral helpers. This refactor must preserve
current SQLite and PostgreSQL behavior under the existing contract tests. It
prevents the new engines from multiplying conditionals across every endpoint.

Enforce this boundary in repository checks: API routes and application services
may import the backend contract and registry, but may not import `psycopg2`,
`pymysql`, `pyodbc`, or an engine-specific physical module. Database-type
conditionals belong only in registration/configuration parsing and the backend
registry or its implementations. One parameterized contract test suite must
exercise the same facet methods for every supported engine; no adapter may leave
a required core method as `NotImplementedError` or silently substitute another
engine's SQL.

### Transaction and resource ownership

Shared services own operation admission, journal transitions, finalization and
retry/reconciliation decisions. Each physical call receives an explicit operation
context tied to the active binding. It identifies the connection owner, transaction
scope, held locks and execution limits; ownership is never inferred from a driver
type or an optional attribute hidden in the source configuration.

- A borrowed catalog connection stays owned by the request/service. An adapter
  may use a savepoint where supported, but cannot commit, roll back or close the
  outer transaction. SQLite retains this path. Savepoint release is not durable
  completion; final success depends on the outer commit.
- For a separately owned physical connection, the backend implements its bounded
  begin/commit/rollback/close lifecycle. It reports durable completion only after
  commit is confirmed. For existing journaled lifecycle mutations, the shared
  service records intent before physical work and finalizes the catalog afterward.
  A shared database does not imply an atomic commit across separate connections.
- DDL that can commit independently cannot run on a borrowed transaction carrying
  pending catalog changes. The shared migration workflow uses a dedicated
  connection and durable progress, with engine-specific DDL mechanics underneath.
- The backend acquires and releases each lock on its owning connection. The
  contract declares whether it survives commits; the bootstrap lock covers the
  whole inspection, migration and registration sequence, including separate DDL
  commits. Losing that lock/connection interrupts the operation and requires fresh
  inspection before retry. Timeouts, cancellation and exceptions release owned
  resources without changing caller-owned transaction state.

The contract distinguishes confirmed application, confirmed non-application, and
unknown outcome. A failed multi-step migration can have confirmed completed steps
without being complete as a whole. Connection loss during commit is an unknown
outcome, not a retryable claim that nothing happened. Shared recovery inspects the
physical postconditions and persisted progress before deciding to resume or finalize;
it never blindly replays a possibly committed mutation.

### Database and migration boundary

Extend `create_catalog_engine()` and hosted bootstrap to build supported,
Secret-backed SQLAlchemy connections for MySQL and MSSQL, while preserving the
one selected runtime database for system and application tables. Keep the
logical system catalog and Alembic revision history shared across engines.
Replace PostgreSQL/SQLite-only DDL assumptions in the catalog schema with
dialect implementations that preserve the same constraints, uniqueness,
foreign-key behavior, UID/JSON/timestamp semantics and migration checks.

Implement catalog mutation locking and bootstrap locking for each engine under
the ownership contract above. PostgreSQL advisory locks and SQLite
`BEGIN IMMEDIATE` are engine implementations, not shared workflow assumptions.
Never report a migrated or created table before physical and catalog state agree.
Existing PostgreSQL and SQLite stores keep their data and migration history;
this work must not require recreation or transfer them to another DataSource.

### First-bootstrap and migration recovery

The shared bootstrap service operates before a DataSource row or the full operation
journal exists. Startup and Settings inspection remain read-only. Only the explicit
**Run MetaTables migrations** action may initialize or upgrade the selected database.
All engines use the following protocol:

1. Bind the validated candidate, acquire its bootstrap lock, and re-inspect the
   selected database. Reject an unrelated or incompatible system schema before DDL.
2. Initialize or validate a minimal, reserved bootstrap progress table in that same
   database. It has a stable, versioned shape independent of the full catalog and
   is not a second catalog or an external database. Its own creation is restartable:
   under the lock, inspect and accept only the exact expected shape if creation
   succeeded before the API lost its connection. An empty progress table never
   authorizes adoption of existing, unversioned system tables.
3. Before migration DDL, durably record the operation identity, source binding
   fingerprint, starting and target Alembic revisions, and the migration plan
   fingerprint. Record each resumable step's intent and verified postcondition.
   Store no resolved credentials in progress records. This mechanism also covers
   an upgrade's progress before its full catalog is safe to use.
4. Shared Alembic orchestration applies the plan using the selected backend's
   migration connection and DDL primitives. MySQL and MSSQL must create the full
   required system schema and constraints. Advance revision/progress state only
   after the corresponding physical postconditions are verified.
5. After schema verification, register the selected runtime DataSource using the
   normal shared registration logic. On retry, a matching row is reused; a
   conflicting row blocks activation. Mark bootstrap complete only after both
   schema and registration agree, then activate the runtime.

An interruption keeps the runtime inactive and Settings available. On explicit
retry, reacquire the lock and reconcile the recorded plan with physical objects:
skip steps whose exact postconditions are satisfied, execute steps proven not to
have applied, and resume only remaining verified work. Changed plan fingerprints,
unknown schema changes or ambiguous effects require repair and a safe diagnostic;
they cannot be bypassed by stamping Alembic history or recreating the database.
A restart may inspect progress but must not automatically resume DDL.

Migration plans must supply the step boundaries and pre/postcondition inspection
needed for this protocol. Wrapping a multi-statement revision in a transaction is
not sufficient for an engine whose DDL commits independently. The backend supplies
inspection and execution mechanics; it does not implement a separate recovery
state machine. Already-current PostgreSQL/SQLite stores remain readable without
new DDL; the next explicit migration action can establish progress metadata.

### Approved application migrations

Approved application migrations run inside the API against the selected engine,
using that engine's Alembic connection and schema conventions. Validate a
provider's table contracts and resulting physical objects before finalizing
catalog registration. A provider that uses engine-specific SQL must declare
support for that engine and fail clearly when selected on another engine.
The full operation journal owns these application migration records after bootstrap.
The same transaction/outcome rules apply; uninspectable partial provider effects
require reconciliation instead of automatic replay. External registrations are not
adopted into a provider's managed migration history.

### Engine implementations

Implement the `catalog`, `tables` and `sql` facets for MySQL and MSSQL. The
`tables` facet implements physical connection/transaction mechanics, type conversion,
DDL, introspection, reads and writes, time-index operations, and physical
deletion. The SQL and access facets implement database-enforced access under ADR 0007.
Application services do not change when an engine is added.

Use MySQL and MSSQL syntax and driver behavior where they differ: schema/database
identity, generated keys, pagination, upsert, JSON, UUID, booleans, temporal
precision, row counts, batching, indexes, constraint discovery and locks. Do not
route either engine through the PostgreSQL connection adapter. Verify each
operation through its implementation and end-to-end tests; a connection probe
alone does not establish table workflow support.

### Compiled and governed SQL

Extend `/runtime-context/` and the compiled SQL contract with explicit `mysql`
and `mssql` dialects and the actual driver parameter style. The Python client
compiles SQLAlchemy statements for the single selected runtime's dialect, and the
API checks the declared dialect, parameter style and source/table identities
against that binding before execution. There is no per-request selection of an
additional source or mixed-engine compilation path.
ADR 0007 supersedes SQL authorization analysis: the API submits caller SQL unchanged
through a restricted backend session. Initialization and schema management establish
native permissions and object safeguards. Requests declare only the DataSource;
there is no statement parser, declared table scope, function allowlist or query
rewriting. Error responses remain credential-safe. ADR 0007 specifies each engine's
protocol, cancellation and transaction limits.

### Client and Admin

Keep MySQL and MSSQL in the DataSource registration UI. Once each engine's table
workflow is verified, remove its connection-only notice and expose the same
table and Settings actions as other hosted engines. Update the client dialect
types, statement compiler, runtime context, capability inventory, OpenAPI and
examples together. Until then, show the current limitation accurately; do not
claim a table operation works based solely on registration or validation.

## Implementation sequence and acceptance

1. Define the backend contract and registry, bind the existing SQLite,
   PostgreSQL and TimescaleDB implementations, and move engine dispatch out of
   routes and application services. Establish shared workflow/resource ownership
   and enforce the single execution binding. Retain existing behavior tests;
   update only assertions explicitly superseded by this decision.
2. Supply the Docker Compose environment below and the manual local runner.
   During implementation, explicit engine subsets allow focused testing without
   claiming full support. The completed implementation must pass the full matrix.
3. Implement MySQL and MSSQL catalog facets: schema, Alembic history,
   locking and runtime context on fresh databases. Use the shared bootstrap and
   recovery protocol for every engine. Verify restart and recovery after a failed
   migration or interrupted bootstrap, plus existing PostgreSQL/SQLite upgrades.
4. Implement each engine's table and SQL facets and approved application
   migrations. Run managed-table, existing-table, compiled SQL, governed SQL
   and time-index flows through the unchanged HTTP routes. Update the Python
   client and Admin to use the backend's dialect and runtime database feature results.
5. Run one parameterized backend contract suite against real MySQL and MSSQL
   instances, alongside PostgreSQL, TimescaleDB and SQLite regression runs.
   The same test cases and assertions must exercise the public API, with
   engine-specific fixtures limited to connection setup, controlled failure
   injection, physical invariant inspection and optional engine features. Cover
   registration, validation, Settings selection, catalog and application migrations,
   CRUD, SQL, time-index updates, introspection, deletion, grants, read-only and
   disabled modes, Secret handling and interruption recovery. Include a fresh
   database and an already registered source. Mocked connection tests and
   installed drivers alone are insufficient. Run this suite manually through local
   Compose services; retain per-engine results before advertising support.

Required failure and ownership cases include interruption between system DDL
steps, after DDL but before revision/progress confirmation, and after migration
but before runtime registration; two concurrent bootstrap requests; uncertain
commit outcomes; a failed borrowed operation preserving its outer transaction;
and restart performing no migrations. Verify that managed creation performs DDL,
external table registration preserves physical objects and ownership; ADR 0007 rejects views, and
every operation rejects a source identity outside the active binding.

### Docker Compose database test environment

Add a repository-owned `compose.database-tests.yml` and a documented single-command
test runner. It provisions separate PostgreSQL, TimescaleDB, MySQL and MSSQL services
with pinned supported image versions, readiness checks, isolated test credentials
and disposable database storage. SQLite runs in the same test runner against a
fresh temporary file; it has no database server service. Thus every supported engine
participates in the test matrix.

The runner initializes a fresh API runtime for each engine, with exactly one selected
DataSource per runtime, and invokes the shared functional suite through the real API
and Python client. The runner starts one engine at a time. Test credentials/Secret fixtures are
isolated from production and require no real platform Secrets. Database services
use the Compose network with no published database ports by default; any optional
host access uses explicitly documented, configurable nonstandard ports.

Document prerequisites for the supported images, including host architecture and
resources, plus startup, full-suite execution, an explicitly selected engine subset,
diagnostic logs and cleanup of only the disposable test resources. The full-suite
command waits for readiness and fails on an unavailable engine or a required skipped
test. An explicit subset is useful during development but cannot count as full parity.
Manual local runs use the Compose services sequentially and retain per-engine
test results and service logs, then clean up their test resources. All four database
services and the SQLite cases are required to verify full support locally.

An engine is complete only when a user can register it, select it as the hosted
runtime source, migrate it, create or register a table, read and write it through
the client and Admin, run a time-index update, and remove a permitted table using
the documented API. Remove the current limitation only when this acceptance
path passes for that engine. Engine development can
progress independently; completing this ADR requires the full engine matrix above.

## Consequences

The work spans API persistence and physical integrations, Python client SQL
compilation, Admin runtime setup and database-backed testing. Existing MySQL and
MSSQL registrations are retained as Settings candidates and become usable as the
selected runtime when their engine adapter is released; this decision does not
delete them or stop accepting new ones. The single API workflow and authorization
boundary continue to govern every engine.

## Alternatives considered

- Remove MySQL and MSSQL registration until table support exists. Rejected:
  registration and validation are already implemented, and the requested outcome
  is to complete interaction with those sources.
- Keep connection-only registrations as the final feature. Rejected because a
  DataSource that cannot host MetaTables tables does not satisfy the table product.
- Add a separate MySQL/MSSQL service or direct client connections. Rejected
  because it would bypass the shared runtime binding, grants, journal and API
  contract.
