# ADR 0015: TimescaleDB compression and retention policies

Date: 2026-10-02

Status: Accepted.

Implementation status: Implemented on the `timescale-policies` branches of the API
and the Admin, with focused tests. TimescaleDB container verification is pending.

Owner: MetaTables API. The Admin owns the screens described here.

Related decisions: [ADR 0002: Table ownership](0002-application-administration-and-table-ownership.md),
[ADR 0007: Database-enforced access](0007-database-enforced-table-access.md) (amended
below), [ADR 0012: Safe retries](0012-bounded-data-transfer-and-safe-retries.md) and
[ADR 0013: Application-owned migrations](0013-application-owned-migrations.md).

## Context

Time-index tables on `timescale_db` DataSources grow without bound. Users need to
compress older data and drop expired data on a schedule, without database access.

Source inspection on 2026-10-02 found:

- The Admin's Timescale Policies tab calls `GET/PATCH meta-tables/{uid}/policies`
  and appears only when a table reports `capabilities.timescale_policies`. The API
  provides neither, so the tab never appears.
- No current path creates hypertables. `storage_layout.partitioning.strategy`
  accepts `timescale_hypertable`, but only the legacy
  `create_multi_index_table_for_metadata` calls `create_hypertable`. Timescale
  policies require hypertables.
- The legacy policy helpers in `adapters/maintenance/timescaledb.py` have no route
  callers. They sleep between steps, remove and re-add policies in separate
  commits, and some build SQL with f-strings.
- TimescaleDB creates a policy job owned by the hypertable owner and refuses to
  create it when that role lacks `LOGIN`. ADR 0007 makes `mt_owner`, a `NOLOGIN`
  role, the owner of every managed table.

## Decision

### Core model

**TimescaleDB stores the policy; MetaTables keeps no copy.** A policy is a
Timescale background job. Timescale already schedules and runs it, so MetaTables
adds no scheduler and no policy table. The API authorizes in the catalog, reads
jobs from `timescaledb_information`, and writes with Timescale's policy functions.

Policies are set only through the API and the Admin. An application that wants
its policies in code runs a Job at bootstrap that calls the client method. Table
contracts and application migrations carry no policy fields.

| Policy | User sets | MetaTables derives |
| --- | --- | --- |
| Compression | `after`; optional `schedule_interval`, `initial_start`, `timezone` | `segmentby` = identity dimensions; `orderby` = time index `DESC` |
| Retention | `after`; optional `schedule_interval`, `initial_start`, `timezone` | — |

- `after: null` removes that policy. Removing compression leaves already
  compressed chunks compressed.
- If both are set, retention `after` must be longer than compression `after`.
- Each change runs in one transaction with parameterized SQL and no sleeps.
- Dropping a table removes its jobs.
- TimescaleDB 2.11 or later is required, since it accepts inserts, updates,
  deletes and upserts on compressed chunks. Uploads and tail deletes therefore
  need no decompression step.

### Eligible tables

A table can have policies when:

1. its DataSource is `timescale_db`;
2. it is a time-index table and not `external_registered`;
3. its physical table is a hypertable; and
4. the installed TimescaleDB version is supported.

Conditions 1–2 are catalog facts. They set `capabilities.timescale_policies` on
the table response without opening a database connection. Conditions 3–4 are
checked live when policies are read or written. Saving additionally requires a
`read_write` DataSource. Tables on any other engine never show policies.

### Hypertables

On a `timescale_db` DataSource, managed finalization converts each new time-index
table into a hypertable on its time index (`create_hypertable`, `if_not_exists`,
`migrate_data`). Strategy `backend_default` means hypertable there; `none` opts
out. `partitioning.strategy` is the only switch, so the duplicate
`backend_hints.timescale.partitioning` hint and `time_index_table.partition_strategy`
are removed. Chunk interval stays at Timescale's default. Every unique constraint
must include the time index; the storage layout's `uniqueness` already does.

### Authorization and ownership

Writer on the table is the only permission check: a Writer can finalize the
hypertable and set or remove both policies. Readers can view policies and job
status. Organization admins also see every job on the DataSource.

**Amendment to ADR 0007:** on `timescale_db` DataSources, hypertables are owned
by the API's database login instead of `mt_owner`, so their policy jobs run as
that login. Access setup leaves hypertable ownership unchanged instead of handing
the tables to `mt_owner`. The API's login already owns the database and is a member of
`mt_owner`, so this grants it nothing new. Reader/Writer grants, caller SQL roles,
application migrations and other engines are unchanged. If the DataSource later
uses a different login, existing jobs keep running as the old one until the
tables are reassigned.

Each policy change is recorded in the `physical_operation` journal as
`timescale_policy`, with the requesting User. System migration
`0009_timescale_policies` adds that kind, drops `time_index_table.partition_strategy`
and removes the Timescale hint from stored layouts; existing runtimes upgrade
through Settings.

### API

```text
TimescalePolicy        { after, schedule_interval?, initial_start?, timezone? }
TimescaleTablePolicies { compression, retention,
                         eligibility { eligible, reason? },               read-only
                         jobs [TimescaleJob],                             read-only
                         compression_stats { before_bytes, after_bytes,
                                             compressed_chunks, total_chunks } }  read-only
TimescaleJob           { job_id, kind, table_uid?, hypertable, scheduled, status,
                         last_run_status, last_successful_finish, next_start,
                         total_failures, last_error? }
```

Intervals use PostgreSQL interval text such as `30 days`; the database validates them.

| Endpoint | Access | Behavior |
| --- | --- | --- |
| `GET /meta-tables/{uid}/timescale-policies/` | Reader | Policies, eligibility, jobs and compression stats. |
| `PUT /meta-tables/{uid}/timescale-policies/` | Writer | Replaces both policies; idempotent, safe to retry. Returns the GET body. |
| `GET /data-sources/{uid}/timescale-jobs/` | Any User who can see the source | Jobs for tables the caller can read; admins see all. `timescale_db` only. |

Errors: `404 timescale_policies_unavailable` for other engines,
`403 write_access_required`, `409 timescale_not_hypertable`,
`409 timescale_version_unsupported`, `409 timescale_extension_missing`, the existing
DataSource access codes for read-only or disabled sources, and `422` for an invalid
interval or timezone or `timescale_retention_not_after_compression`.

The Python client exposes `get_timescale_policies()` and `set_timescale_policies()`
on time-index tables.

### Admin

- **Table → Timescale Policies** (the existing tab, reworked): Compression and
  Retention cards, each with an on/off switch, an `after` number with a unit
  (days, weeks, months), and an Advanced section for schedule, start and timezone.
  Each card shows its job's status (Scheduled, Running, Failed, Paused), last
  success, next run and failures. Compression shows size before and after.
  Saving retention asks for confirmation, naming the cutoff date and stating that
  older chunks are permanently dropped on every run and that older backfills are
  dropped too. Readers see the tab read-only. An ineligible table shows the reason.
- **DataSource → Jobs** (`timescale_db` only): a table of jobs — table link,
  policy, status, last run, next run, failures — with a failed-only filter and
  Refresh, under Policies and Failed jobs counts.

Screens use Command Center SDK components and theme tokens only.

### Monitoring

Monitoring is read on demand from `jobs`, `job_stats`, `job_errors` and
`hypertable_compression_stats`. MetaTables stores no job history, polls nothing,
and sends no alerts.

## Consequences

- One source of truth: a policy changed directly in the database appears in the
  Admin as it is.
- The legacy Timescale policy, decompression and hypertable helpers and their
  runtime registrations are deleted.
- Retention is destructive and available to every Writer; the confirmation is
  the safeguard.
- Policy jobs belong to the API's login. Rotating its password does not affect
  them; no role gains `LOGIN`.

## Alternatives considered

- **Policies in table contracts or migrations.** Two authorities would overwrite
  each other. A bootstrap Job calling the API covers code-defined policies.
- **A catalog copy with a reconciler.** It duplicates Timescale's job store and
  adds drift handling.
- **A MetaTables scheduler.** Timescale already schedules policy jobs.
- **`mt_owner` with `LOGIN` and no password.** It changes a login setting and
  depends on the server never accepting passwordless authentication for that role.

## Verification

Focused tests cover eligibility, interval validation, authorization, the request
contract and the derived compression settings, using a fake backend. The
TimescaleDB container suite, run only on explicit request, verifies hypertable
conversion, policy add/replace/remove, job ownership by the API's login, Reader and
Writer grants reaching chunks and compressed chunks, and upserts into compressed
chunks. Admin checks cover tab visibility, read-only mode and the retention
confirmation.
