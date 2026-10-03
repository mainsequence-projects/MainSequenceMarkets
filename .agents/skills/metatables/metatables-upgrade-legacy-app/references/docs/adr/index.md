# Architecture decisions

Architecture decision records explain proposed and accepted changes to
MetaTables. **Proposed** and **Accepted** describe decision status, not proof of
implementation. Each record states its implementation status separately. Current
user guides remain the reference for available behavior until the corresponding
implementation is verified.

Records are separated by the component that owns the decision: `client/` for the
installed Python client and its CLI, and `api/` for service behavior, storage and
authorization. A record can describe consequences for the other component without
transferring ownership. ADR numbers remain unique across both directories. SDK
decisions belong in the SDK repository and are linked as dependencies.

## Python client

| ADR | Status | Scope |
| --- | --- | --- |
| [0003: Automatic API endpoint resolution](client/0003-api-endpoint-resolution.md) | Accepted and implemented; live hosted verification pending | Resolve the packaged API name within the SDK-owned Environment, cache per platform/Environment, and reserve URL overrides for local development. |
| [0011: Local CLI workflow with reusable Admin](client/0011-cli-local-development-with-managed-admin.md) | Accepted; implemented | Download missing Admin source once, reuse ready dependencies, launch the installed API with Vite, and expose explicit bootstrap, application-owned migrations and local client connection. |

## API

| ADR | Status | Scope |
| --- | --- | --- |
| [0001: One API execution path with SQLite for local development](api/0001-unified-api-storage-and-local-sqlite.md) | Accepted and implemented; hosted declaration verification pending | Shared execution, API-owned local storage, SDK context dependency, and DuckDB removal; the deployment declares the hosted runtime database in `configuration.yaml` and an Environment Secret, and Settings is read-only in Hosted mode. |
| [0002: Application administration and table ownership](api/0002-application-administration-and-table-ownership.md) | Accepted and implemented | Platform admin facts, table Reader/Writer ownership, User/Team grants, live namespace inheritance, and application-owned access management. |
| [0004: Execute approved application migrations inside the API](api/0004-approved-application-migrations.md) | Superseded by ADR 0013 | Historical API-installed provider execution model. |
| [0005: Shared run logs with local file capture](api/0005-run-logs-and-local-file-capture.md) | Accepted and implemented; live hosted verification pending | Shared run correlation and log API, runtime-bound local JSONL files, and hosted retrieval through the SDK. |
| [0006: Historical run graphs and the Runs menu](api/0006-historical-run-graphs.md) | Accepted and implemented | Saved execution graphs anchored to existing root runs, dependency outcomes and exact logs, with a Runs menu; scheduling remains with Main Sequence Jobs. |
| [0007: Enforce table grants in the database](api/0007-database-enforced-table-access.md) | Accepted; implemented | Reader becomes PostgreSQL `SELECT` and Writer `SELECT`/`INSERT`/`UPDATE`/`DELETE`; each User queries as their own database role, so a query explorer needs no SQL parsing. |
| [0008: Implement MySQL and MSSQL table workflows](api/0008-mysql-mssql-table-workflows.md) | Accepted; implemented | One selected DataSource with complete system-schema and table support, shared workflows, explicit transaction ownership and bootstrap recovery; verify every engine through a Docker Compose functional suite. |
| [0009: Shared CredentialStore and cross-platform keys](api/0009-shared-credential-store.md) | Accepted; implemented | One API-owned credential contract; encrypted local catalog storage and cross-platform keys, hosted SDK Secrets without a second encryption layer, explicit import and rotation. |
| [0010: Import external tables and views](api/0010-import-external-tables-and-views.md) | Accepted; implemented (verification boundaries in ADR) | Shared backend discovery, metadata import/refresh, and bounded reads of external tables and views, preserving one runtime catalog and existing grants. |
| [0012: Bounded data transfer, concurrent execution, and safe retries](api/0012-bounded-data-transfer-and-safe-retries.md) | Accepted; implemented; hosted engine verification pending | API/client row and byte budgets, incremental fetching, concurrent admission, durable chunk receipts, safe recovery, and required user documentation; independent of Artifacts and temporary URLs. |
| [0013: Application-owned migrations](api/0013-application-owned-migrations.md) | Accepted and implemented | Application-side Alembic, environment database authority, API catalog integration and separate system migrations. |
| [0014: System migrations in the deployment workflow](api/0014-main-sequence-release-jobs-and-production-migrations.md) | Accepted; implemented on development; hosted verification pending | A Main Sequence Job verifies, migrates and registers the declared runtime database from the candidate image before each API rollout, including the first. |
| [0015: TimescaleDB compression and retention policies](api/0015-timescale-compression-and-retention-policies.md) | Accepted; implemented on branch; TimescaleDB verification pending | Time-index tables on TimescaleDB become hypertables; Writers set compression and retention through the API/Admin; Timescale keeps the jobs, and the Admin shows their status. |
| [0016: Impact pre-flight for cascades and deletes](api/0016-impact-preflight.md) | Accepted; implemented; container engine verification pending | `get_impact` returns what a row delete, key update or table drop reaches, every blocker and the caller's effective write, from the planner the confirmed delete runs; projects render it in their own UIs. |
