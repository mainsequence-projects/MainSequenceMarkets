# ADR 0005: Shared run logs with local file capture

Date: 2026-09-29

Status: Accepted.

Implementation status: Implemented with local file/HTTP tests and isolated hosted
SDK/provider tests. Live hosted workload collection verification remains pending.
See [operational limits](../../operations/run-logs.md).

Owner: MetaTables API. The Python client supplies correlated log records and
attaches the local file handler; the API owns the storage binding and read contract.

Related decisions: [API ADR 0001: Unified API storage](0001-unified-api-storage-and-local-sqlite.md),
[API ADR 0002: Administration and table ownership](0002-application-administration-and-table-ownership.md),
and [client ADR 0003: API endpoint resolution](../client/0003-api-endpoint-resolution.md).

## Context

MetaTables already records updater runs in its catalog and uses the Main Sequence
SDK's structured logger. Existing context includes table identities, update hashes
and an execution UUID shared with dependencies. It does not consistently bind the
exact catalog run UID, restore nested logging context, or associate a run with its
platform execution for subsequent log retrieval.

Before implementation, the API exposed run records through `/table-update-runs/`
but had no run-log reader. Admin requested update-specific runs and logs routes that do not
exist, and its run fields differed from the API response. A visible Logs tab does
not establish an implemented logging capability.

Hosted workloads already have platform log collection and SDK retrieval. Local
development needs durable logs without a platform collector. The SDK already
supports structured file logging, but its process-wide file is not a MetaTables
workspace/run store. Storing every local log record in SQLite would introduce
database writes and contention for data that naturally fits append-only files.

## Decision

### One emission path and one read contract

Updater code emits through the existing SDK logger in both modes. MetaTables adds
the same scoped correlation fields before emission. Local capture is an additional
file handler on that logging path; hosted capture uses the existing platform
collector. Producers do not choose a separate logging API for each runtime.

All log reads go through the MetaTables API. Its shared log service checks access,
validates the query and normalizes the result. Only the reader differs:

| Active API runtime | Capture | API reader |
| --- | --- | --- |
| Local | Structured file handler in the emitting process, writing to the bound workspace | Read that workspace's run files |
| Hosted | Existing platform workload collector | Existing platform log operations through `mainsequence-sdk` |

The active API runtime binding selects this behavior. A loopback API URL, a client
running on a laptop, or a Git branch name does not independently select local log
storage. No new logging-mode environment variable is introduced.

Catalog run metadata remains in the runtime's database. Log bodies are not stored
in a new catalog table in either mode. Local file capture requires no log-ingestion
endpoint, queue service or direct client access to SQLite.

### Shared correlation fields

| Field | Meaning |
| --- | --- |
| `operation_uid` | Exact MetaTables `UpdateRun.uid`; one updater attempt |
| `data.metatables.update_uid` | Updater identity in the catalog |
| `data.metatables.output_table_uid` | The updater's output table |
| `data.metatables.update_hash` | Updater configuration hash; not a run identity |
| `data.metatables.execution_uid` | Shared execution identity for the root and its dependency runs |
| `trace_id`, `span_id` | Actual tracing context, when present |
| `job_run_uid` or another supported platform execution reference | Platform-supplied workload identity, when present |

Business fields live under `data.metatables` so the platform can preserve them
through its generic structured-data contract. Merge existing `data` members rather
than replacing unrelated application context. Do not overwrite platform workload
identity or confuse the runner's existing execution UUID with an OpenTelemetry
trace ID. The current catalog `trace_id` field carries that execution UUID;
its interpretation must remain explicit when adapting existing run responses.

Bind the run UID after the API creates the run and retain it through completion
or failure logging. Dependency runs replace the current `operation_uid` with their
own run UID and restore the parent context afterwards. Restore previous context
in `finally`, including exceptions, and propagate it explicitly into worker
threads or processes that emit run logs. Correct existing discarded `logger.bind()`
results as part of implementing this contract. Events before a run exists remain
ordinary process/execution logs; do not invent a catalog run for them.

### Local files belong to the selected runtime

The API determines a dedicated logs directory from the selected local database
and its workspace binding. An explicitly selected SQLite file receives its own
associated directory; another database in the same workspace must not share it.
The existing runtime/run response flow supplies the local client with the capture
descriptor. The client does not infer a directory from its own working directory
or configure a second independent storage target.

The local client and API must share that filesystem location and have the required
OS access. This is a prerequisite for local file capture. A client outside that
filesystem reports capture as unavailable; it must not write to an unrelated
fallback directory and present those logs as API-readable. The shared local
filesystem is a development trust boundary, not a new isolation mechanism between
mutually untrusted OS users.

Write UTF-8 JSON Lines under a run-specific directory, with separate writer files
when multiple processes emit for the same run. Reuse the SDK's structured
formatting and file-handler support where suitable, without changing its global
file target for every updater. Attach handlers idempotently, filter to the bound
MetaTables run, and avoid duplicate records on repeated setup or nested execution.
Rotation must not let independent writers rename or overwrite each other's files.

The implementation must define and document finite file-size, retained-byte/file
and read-work limits. Reads are bounded to the requested runs and window, never a
scan of the global SDK log file. Flush completed records promptly and at normal run
completion. Readers tolerate an unfinished final line during a write and report
damaged records or missing segments without treating the entire run as empty.

Files survive API and client restarts. A run keeps its original capture binding;
changing Settings must not redirect an active handler or an old cursor into the
new runtime. Reset/destruction must invalidate old writers before removing their
store, so they cannot recreate a destroyed workspace's logs. Extend the existing
explicit local destruction operation to remove only the selected runtime's owned
log files, with the same ownership validation as its database. Ordinary restart
and runtime switching do not delete logs. Retention removes expired files without
deleting catalog run history.

Logging failures must not replace an updater's original result or exception.
Expose capture failures through a bounded diagnostic outside the failing handler
and log-availability status; avoid recursive logging and silent success claims.
Local capture provides development diagnostics, not a transactional audit trail.

### Hosted capture remains a platform responsibility

Keep hosted log storage, collection and retention in the platform. MetaTables
records the available opaque platform execution reference with its run and reads
through the SDK. It does not import provider clients, query cloud log stores
directly, duplicate hosted log bodies locally, or add platform table/updater models.

The local SDK development branch now exposes the generic exact `operation_uid`
filter on existing owner `get_logs` methods; the platform owner log contract
applies it before pagination and includes it in cursor binding. This requires
the matching SDK/platform changes, not just the MetaTables package.
[SDK ADR 0036](https://github.com/mainsequence-sdk/mainsequence-sdk/blob/metatables_removal/docs/adr/0036-generic-operation-log-filter.md) records the SDK boundary. Structured `data` must survive
collection and serialization. Any later search over business fields must use
bounded, validated generic field filters; it must not add MetaTables-specific
platform routes or accept arbitrary provider query expressions.

Platform execution identity supplies the workload scope; an application-provided
`operation_uid` is correlation, not proof of authorization. Access remains governed
by the existing platform operations and MetaTables table grants. No new SDK
identity checks, Organization policy or authentication mechanism is introduced.
SDK/platform contract decisions and implementation belong in their repositories.

A laptop process targeting a hosted API does not automatically enter platform
collection. If it has no supported collector/forwarding path or execution
reference, report hosted logs as unavailable. A generic forwarding facility would
be a separate platform capability, not an implicit local-runtime fallback.

### API and Admin behavior

Use one run-log query/response contract for both readers: bounded time window,
level and event filters, a page limit, opaque continuation cursor, normalized
structured rows, and explicit availability/truncation information. Filters must
apply before page limits. Unsupported search options must be reported rather than
silently filtering a single fetched page. Bind cursors to the runtime store,
requested runs and filters; append/rotation must not silently skip records, and
an expired segment must produce an explicit expiration result.

The canonical run-level read is `/table-update-runs/{run_uid}/logs/`.
The update Logs tab can use `/time-index-table-updates/{update_uid}/logs/`, backed
by the same service over a bounded selection of that updater's runs. Dependency
execution correlation must not expand a query into other tables without checking
their grants. Both routes use the shared implemented service.

Require the existing table Reader access for the relevant run's output table
before reading local files or invoking the SDK. Resolve paths and platform
references from admitted run/runtime metadata, never caller-supplied filesystem
paths or arbitrary workload UIDs. Local path resolution must remain inside the
owned store and reject traversal and symlink escapes. Apply the same safe-field
and credential-redaction policy to both readers.

An empty matching page, unavailable capture, expired retention and a reader outage
are distinct results. Local file readers and hosted SDK readers normalize those
conditions for the same Admin component. Records and pages must have deterministic
ordering even when timestamps match.

Fix Admin run history to use the existing `/table-update-runs/` query with
`table_update_uid`, and normalize its existing timestamp/result fields. Replace
offset assumptions in the Logs tab with the shared cursor contract. User-facing
guides and the capability inventory may claim support only after implementation
and verification.

## Implementation and acceptance

1. Implement scoped run correlation, context restoration and idempotent local
   handler attachment. Verify nested dependencies, concurrent runs, exceptions
   and repeated initialization without cross-run leakage or duplicate records.
2. Implement the runtime-bound file store and reader. Verify real JSONL writes,
   concurrent writers, restart persistence, bounded rotation, partial writes,
   capture failures, retention, selected-database isolation, runtime switching and
   destruction with stale writers. No log-body database writes are introduced.
3. Complete the generic SDK/platform filtering prerequisite and preserve custom
   structured fields through collection. Remove obsolete platform table-specific
   log readers where superseded; retain generic job capture and observability.
4. Implement the shared API service and Admin integration. Exercise real local
   updater-to-file-to-HTTP-to-Admin behavior, table access checks, unsupported
   filters, cursor continuation, expiration and availability states.
5. Verify hosted emission, collection and retrieval with an actual workload. SDK
   fixtures establish adapter behavior but do not establish live collector support.
   Update documentation with concrete limits and supported query capabilities.

## Consequences

Local logs add filesystem writes without adding SQLite contention. The same
producer instrumentation and API consumer contract serve both runtimes; only
capture and retrieval adapters differ. File retention, concurrent writes and
rotation require explicit handling, and local capture requires a shared filesystem.
Runs can outlive their retained logs, and abrupt process termination can lose
records not yet flushed. Neither log presence nor absence determines run success;
the catalog remains authoritative for run lifecycle metadata.


## Implementation evidence

`tests/e2e/test_run_logs.py` exercises run creation, the client runner and SDK
logger, JSONL capture, both client `get_logs` methods, HTTP filters/cursors,
restart persistence, revocation, destruction and the hosted SDK adapter.
`tests/integrations/test_local_run_logs.py` covers nested/concurrent context,
separate writer files, retention, capture failure and symlink rejection.
The catalog migration adds only nullable capture references to `UpdateRun`.
Existing stores require the explicit Settings migration operation.

Local reads use a bounded snapshot; continuations expire after ten minutes or
API restart, store destruction or deletion of their source segments. New events
appear on refresh. Admin shows cursor navigation and availability, and adapts the
existing catalog run-history fields. These tests do not claim a live cloud
collector canary.
