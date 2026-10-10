# ADR 0014: System migrations in the deployment workflow

Date: 2026-10-02

Status: Accepted. Implemented on `development`; hosted verification pending.
Amended 2026-10-03 ([MetaTables #13](https://github.com/mainsequence-projects/MetaTables/issues/13)): the Job reads the declared runtime database itself
and initializes it on the first deployment.

Owners: MetaTables API. Main Sequence owns Job execution, images, deployment and
platform authentication.

Related: [ADR 0001: Runtime storage and bootstrap](0001-unified-api-storage-and-local-sqlite.md),
[ADR 0008: Database workflows and recovery](0008-mysql-mssql-table-workflows.md) and
[ADR 0013: Application-owned migrations](0013-application-owned-migrations.md).

## Context

Main Sequence deploys the hosted API from `.mainsequence/workflows/metatables-api.yaml`.
Settings runs system migrations inside the running API, and that API can only
apply the revisions it ships. A release's new revisions must be applied before
its API serves.

## Decision

### The Job prepares the declared database (amended 2026-10-03)

The Job no longer reads the running API. `metatables runtime upgrade` loads
`runtime_database` from the candidate image's `configuration.yaml` and the
Environment Secret it names ([ADR 0001](0001-unified-api-storage-and-local-sqlite.md)).
Every run executes the same steps:

1. Check that the login can secure the database (ADR 0007 prerequisites).
2. Apply the system migrations.
3. Register the runtime DataSource, or update its connection to the declaration.
4. Freshly validate access setup and repair changes. Per-User role passwords
   derive from the login password, so a rotated password reaches them on the
   next deployment. The conditional reconciliation amendment below replaces
   unconditional rebuilding on every deployment.

The first deployment therefore initializes the database. A missing declaration
or Secret, an unreachable database or unmet prerequisites fail the Job and block
the rollout. The deployment workflow is the authority, so no admin caller is
required. A new runtime DataSource records the Job's SDK user as its creator.
The Job prints `initialized`, `upgraded` or `up_to_date` with the revisions.

Settings' **Run MetaTables migrations** and `metatables runtime initialize` remain
for Local mode only. The original decision follows. The amendment supersedes
steps 1–2, the skip rules and the Settings initialization paragraph.

### Conditional system bootstrap (2026-10-10 amendment)

An unchanged deployment remains a validation gate, but does not restart completed
work or rewrite an identical catalog/security projection. This concerns the
MetaTables **system** Job, separate from application-provider finalization in
[ADR 0013](0013-application-owned-migrations.md).

```text
resolve declaration and Secret
  -> bootstrap lock
  -> fresh history, recovery and runtime-binding checks
  -> current heads + completed journal?
       yes: fresh physical system-schema validation; preserve journal
       no: existing Alembic execution and durable recovery; validate schema
  -> reconcile runtime registration if changed
  -> security-state lock; fresh native security and login validation
  -> unchanged evidence? fresh table-policy checks; apply only grant differences
       otherwise: full security repair, including credential rotation
  -> commit; fresh registration/reference verification; release bootstrap lock
```

Hosted configuration defers database inspection to the authoritative preflight
inside the bootstrap lock. The local path retains its pre-lock check, so an old
store cannot be replaced or a new file created before compatibility is checked.
Registration/reference validation is read again after commit under the lock;
it does not repeat schema reflection or the already verified migration history.
Startup and explicit activation continue their existing fresh checks.

Matching Alembic heads alone are insufficient. Only a **completed** progress
journal allows skipping Alembic and journal writes, after fresh schema validation.
A missing journal is established through the existing path. An incomplete
journal retains plan/binding checks, acknowledged-step recovery and rejection
of unknown outcomes. A completed journal records its original execution; a
source-code change without new revisions does not reset that history. Schema
drift still blocks deployment and is not silently repaired by replaying Alembic.

On PostgreSQL/TimescaleDB, the existing private `SQLSecurityState.manifest` stores
versioned native-security evidence and a domain-separated credential checksum,
alongside roles, memberships, privileges and routine evidence. No schema revision
is needed. Initialization compares fresh database evidence: role attributes and
memberships; schema, relation, column, routine, database and default ACLs; owners,
routine definitions and row-security policies. Table data and statistics are
excluded. Declared schemas and grant-target tables are included even when the
login has grant authority without owning them. Fresh per-login authentication
uses the configured TLS material and a new connection, never a pooled session
that could conceal a password change.
The security-state row stays locked until commit to serialize with catalog
changes and caller admission.

All registered table policies are freshly checked even on the unchanged path.
Unchanged table owners and `PUBLIC` grants cause no ownership/revoke writes.
Policies and grant differences still apply when a trigger or catalog change
affects access. Native drift, credential rotation, pending/unready state or
missing evidence invokes full repair. Login authentication failures likewise
require repair. Exhausted login connection capacity conservatively falls back
to the existing repair. libpq can omit SQLSTATE on a connection/authentication
failure; these ambiguous driver connection errors also require repair rather
than allowing a skip. Other probe failures fail deployment. An old installation
therefore performs one full repair to establish evidence, then converges.
Explicit admin repair remains a full sweep; MySQL/SQL Server keep their existing
security initialization behavior.

The complete manifest is compared and persisted once, including backend fields;
reconciliation must not remove and then restore the routine fingerprint. Ordinary
incremental changes cannot checkpoint unverified native drift as success. Failed
security work rolls back its catalog checkpoint and remains repairable on retry.

Named timings cover declaration/Secret resolution, bootstrap/security lock waits,
preflight, catalog/Alembic execution, system-schema validation, registration,
native security and login authentication validation, routine repair, table
policies, roles/grants, credential-store setup, commit and final registration
verification. Each timing
reports completion/failure without connection strings, passwords, checksums or
driver exception text. Successful security setup logs the selected path and its
reason, including first-run evidence establishment.

Focused verification uses disposable SQLite catalog transactions and recording
PostgreSQL adapters: unchanged deployments invoke no Alembic or catalog/journal
DML; unchanged native security emits no role/grant DDL or manifest UPDATE;
schema drift, interrupted/ambiguous recovery, credential rotation, permission
drift and failed repair remain checked. Live PostgreSQL/TimescaleDB validation is
separate from these non-container checks.

### Original decision (2026-10-02)

The deployment workflow upgrades the runtime from the candidate image before the
rollout:

```text
candidate image -> migrate-system Job -> API deployment
```

A failed upgrade blocks the rollout.

The Job, `jobs/migrate_system.py`, runs `metatables runtime upgrade`:

1. Find the Environment's MetaTables API the same way the client does.
2. Read `GET /runtime-context/` as an organization admin. For admins,
   `bootstrap.candidate` is the Settings DataSource's public configuration with
   its Secret references; the Secrets are resolved through the SDK.
3. Apply this package's system migrations through the shared bootstrap operation:
   backend lock, progress recovery, runtime registration, access setup and
   verification. A runtime already at the current revision is left untouched.

The command acts only on an active runtime. With no API deployment or no active
runtime yet, it succeeds without DDL. The Environment's DataSource is set
through the deployed API, so if it is set the command migrates when necessary;
if it is not, it skips migrations and the API deploys. An API release that the
workflow created but has never deployed counts as no API deployment, so the
first run deploys the API. A non-admin identity or an unreadable
context fails before DDL. When it registers the runtime DataSource, it records
the Job identity's user UID as the creator.

Settings' **Run MetaTables migrations** and `metatables runtime initialize` keep
initializing a newly selected DataSource: the API serving them is the deployed
revision and runs its own migrations, so there is no version skew. API startup
stays inspection-only.

Both targets declare `automatic_redeployment` with `tag_regex: null`, so every
eligible commit runs the graph. Package publication stays in GitHub Actions.

The upgrade owns only `metatables.api.backend.migrations` and
`metatables_catalog_version`. Application providers keep their own histories
under ADR 0013.

## Consequences

- The previous API keeps serving during the upgrade, so each schema change must
  stay compatible with the previous release. Coordination with its writes is not
  defined yet.
- An upgrade followed by a failed deployment leaves the database upgraded. There
  is no automatic downgrade.
- The workflow runs only when the platform receives the branch's commit.
  Verification in a hosted Environment is pending.
