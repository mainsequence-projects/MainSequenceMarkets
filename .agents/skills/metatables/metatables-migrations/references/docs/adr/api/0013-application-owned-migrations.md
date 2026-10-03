# ADR 0013: Application-owned migrations through the client

Date: 2026-10-01

Status: Accepted and implemented.

Owners: MetaTables client and consuming applications; API owns catalog integration.

Supersedes [ADR 0004](0004-approved-application-migrations.md), the direct-connection
blocking amendment in [ADR 0002](0002-application-administration-and-table-ownership.md),
and the application-migration execution portions of API ADRs 0001, 0007, 0008,
0009 and [client ADR 0011](../client/0011-cli-local-development-with-managed-admin.md).
Their other decisions remain in force.

## Context

Application revisions are independent of MetaTables' internal schema. Requiring
application providers to be installed and allowlisted in the API made every new
application or revision depend on a central API deployment. It also disabled
current, autogeneration, revision targeting and downgrade in the client.

The environment supplies a database login with the DDL permissions needed by its
applications. Provisioning and limiting that login is the environment operator's
responsibility. Catalog table grants do not define the privileges of that login.

## Decision

Applications own their provider code, model registry, revision files, version
tables and execution. The client imports the provider from the application's
Python environment and runs Alembic there. The API does not import application
providers or execute their Python revisions. No application code installation,
provider alias, deployment allowlist or API redeployment is required.

The client supports scaffold, handwritten/offline revision, autogeneration,
current, upgrade and downgrade, including explicit revision targets. A shared
client runner supports Python setup code and CLI commands. Alembic commands are
serialized within that client process because Alembic uses global proxies.
Applications/deployment tooling must serialize concurrent migration processes for
the same provider/database; there is no distributed application migration queue.

The selected API runtime determines the environment/DataSource. The existing
migration-connection endpoint authenticates the caller, checks Writer access to
the provider's catalog entries, validates provider identity and source access,
and returns the configured runtime connection with its dialect and TLS settings.
The credential resolver remains responsible for Secret retrieval. It does not
mint per-user or per-provider database roles. The response is not cacheable and
credentials are not written to configuration, printed, or retained after use;
TLS files are private and temporary. Local SQLite returns the selected file.
A supervised runtime is held until the client releases its migration connection.

**Direct migrations execute with the environment login's database privileges.**
They do not run through the API's governed-SQL identities or SQLite authorizer.
Writer checks authorize catalog participation and connection admission; they do
not sandbox DDL or make one provider's database access exclusive. Environment
operators are responsible for database login privileges (including CREATE, ALTER,
DROP and ownership requirements), credential distribution and rotation. Catalog
grant revocation cannot revoke a database connection or a credential already
received. TTL fields retained for request compatibility do not expire the configured
login. Runtime holds coordinate switching, not credential revocation; a crashed
client may require restarting the supervised runtime to clear an orphaned hold.

## Lifecycle and failures

1. Load the application provider and resolve the selected runtime.
2. Reserve the Alembic registry and application catalog bindings.
3. Obtain the configured connection and run the application's Alembic command.
4. Read actual applied revisions; close the database transaction/connection.
5. Finalize catalog contracts through the API, including previously registered
   provider tables removed from the current model registry. Reconcile physical
   columns, indexes, foreign keys and governed-SQL permission projections.
6. Release the runtime hold, including on failure.

Existing compatible catalog identities are reused. Existing unversioned physical
application tables are not silently adopted or stamped. Failed DDL is not finalized.
A committed migration followed by failed finalization can be retried: Alembic reads
its version table and the API retries reconciliation. Partial/nontransactional DDL
requires inspection and application-owned recovery. No server executor journal is
claimed for client DDL. Downgrade to base clears the recorded revision and reconciles
dropped tables. Revision files already applied remain immutable.

## MetaTables system migrations

Hosted system upgrades also run as a deployment prerequisite Job
([ADR 0014](0014-main-sequence-release-jobs-and-production-migrations.md)). Application providers keep their own histories and are not
part of that Job.

The API continues to own `metatables.api.backend.migrations`, `metatables_catalog_version`
and the explicit admin bootstrap/upgrade operation in Settings. Application
migration commands do not invoke that operation. Applications must keep their
physical names and version tables separate from reserved system objects.

## Removal and upgrade instructions

Remove `/application-migrations/upgrade/`, `application_migration_providers`,
`init --provider` approval and the allowlist-derived runtime availability field.
Existing deployments must remove `application_migration_providers` from their
configuration; it is no longer an accepted setting. Replace execution aliases
with local Python provider references, for example:

```bash
metatables migrations upgrade --provider ledger.migrations:migration
```

`upgrade_application()` remains a client convenience function and now takes a
local provider reference and optional revision. The API needs only MetaTables;
the application process needs its own package, revisions and selected database
driver. Existing application Alembic histories and catalog UIDs are reused.

## Verification

Focused tests cover independent application providers, client-only provider loading,
autogeneration and additive revisions, current/upgrade/downgrade/base, repeated
execution, failed DDL and reconciliation recovery, preserved system revision,
connection dialect/TLS options, catalog authorization and runtime hold release.
SQLite integration tests use disposable files. Hosted driver configuration is
checked without starting databases. Container/database-matrix tests are on demand;
backend/runtime tests are not added to required CI checks.
