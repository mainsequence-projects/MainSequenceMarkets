# Run logs

For a specific invocation, open **Runs**, choose its saved graph, then select an
updater node. That view reads the exact attempt's logs. Catalog graph history
survives log expiration; see [Run history and graphs](run-history.md).

MetaTables records each updater attempt in its catalog. Its logs remain separate:
local runtimes append JSON Lines files, and hosted runtimes use platform log
collection. The Python client and Admin read both through the MetaTables API.
Run success and failure come from catalog history, not from the presence of logs.

## Emitting records

Updaters use their existing `self.logger` or `mainsequence.logconf.logger`.
The runner binds `operation_uid` to the exact run UID and adds updater, output
table, configuration hash and dependency execution identities under
`data.metatables`. Existing structured fields are preserved. Tracing IDs retain
their tracing meaning; the existing run-history `trace_id` field is the shared
execution UUID, not necessarily an OpenTelemetry trace ID.

```python
from mainsequence.logconf import logger

# Inside the updater's calculation:
logger.info("prices.batch.completed", data={"rows_written": 120})
```

The SDK's logger is initialized if the application has not configured structlog.
Custom logging configuration must keep the SDK's stdlib logging path. The extra
local handler is installed for the run and removed after completion. Nested runs
restore the parent's context. Applications launching their own worker threads
must propagate context with `contextvars.copy_context().run`; separately launched
processes must create their own API run or explicitly carry the capture descriptor
and correlation context. Background work must finish within the run's lifetime.

Do not log passwords, credentials, raw caller assertions, connection responses or
other sensitive payloads. Local capture and API responses redact known sensitive
keys and credential patterns; this cannot identify arbitrary secrets embedded in
free text. A capture failure is reported separately and does not replace the
producer's result or exception.

## Local runtime

The active API binding chooses an adjacent directory named `<database-file>.logs`.
For `metatables.sqlite`, this is `metatables.sqlite.logs/`. Its ownership marker
binds it to the workspace and gives it a generation UID. Each run gets a directory,
and concurrent writers use distinct append-only segments. A small adjacent lock
file serializes rotation and destruction; no log-body SQL writes are made.

The client and API must share this filesystem location. A laptop pointing to a
hosted API does not select local capture. Local files survive restarts and runtime
switches. **Destroy local database** also removes that database's owned logs;
stale writers cannot recreate them. An ordinary updater/table deletion can leave
unreferenced files until retention cleanup; those logs are no longer API-readable.

| Limit | Behavior |
| --- | --- |
| Record | 64 KiB; larger records become an explicit truncation diagnostic |
| Segment | 1 MiB; each writer starts a new segment at the boundary |
| Store retention | Up to 256 segments / 256 MiB and seven days of file age |
| Cleanup | On segment creation, periodic active writes, and reads; no background service |
| Snapshot read | At most 16 MiB of local input, 10,000 matching rows and 8 MiB of response data |
| Page | Default 50 rows; maximum 500 |
| Snapshot lifetime | Ten minutes, up to 32 snapshots per API process; restart/eviction requires refresh |

Rotation/retention can remove part of an older run. The response reports partial
or expired availability. Readers ignore an unfinished active final line and
report damaged completed records. Abrupt process termination can lose buffered
records; these files are diagnostics, not transactional audit storage.

## Reading logs

Python resource methods use the same routes as Admin:

```python
from metatables import TableUpdateRun

run = TableUpdateRun.get(uid="00000000-0000-0000-0000-000000000001")
page = run.get_logs(level="error", limit=50)
for row in page.rows:
    print(row.timestamp, row.message)
if page.next_cursor:
    next_page = run.get_logs(level="error", limit=50, cursor=page.next_cursor)
```

`TimeIndexTableUpdate.get_logs()` selects up to the latest 20 overlapping runs.
The HTTP update route also accepts `run_uid` to select one attempt. The run route
is `/table-update-runs/{run_uid}/logs/`; the update route is
`/time-index-table-updates/{update_uid}/logs/`. The invocation route,
`/table-update-runs/{run_uid}/invocation-logs/`, reads every readable attempt of
that run's invocation in one time-ordered page, and its `run_uid` option narrows
the page to one of those attempts. Admin **Runs** uses it for the run timeline.

Supported query options are `level`, exact `event`, `limit`, `cursor`, and paired
`start_time`/`end_time` timestamps. The default window is the last seven days;
explicit windows must be positive and no longer than seven days. Unknown options,
free-text `search`, offset pagination and repeated query keys return 422. Level
and event filters apply before page limits.

Responses contain `rows`, `next_cursor`, `availability`, per-run `run_statuses`,
`truncated`, and the resolved time window. Each row has its run UID, timestamp,
level, event, message, source and structured context. Empty matches are distinct
from `unavailable` capture, `expired` retention, `damaged` records, `partial`
coverage or a reader `error`. Truncation means a
read/run limit was reached; narrow the window or select one run to inspect more.

Continue with the same filters and page size. Cursors bind to the selected
runtime and runs and hold a stable snapshot; new events appear on refresh.
Expired snapshots or removed source segments return 410. Current table grants
are checked on every page, including after revocation. Run history remains
available via `/table-update-runs/?table_update_uid=...` even after log retention.

## Hosted runtime

Hosted runs retain an opaque JobRun reference and read its logs through
`mainsequence-sdk`, with an exact `operation_uid` filter. The API performs at most
20 platform log-page reads per snapshot and reports truncation when more remain.
The platform controls workload visibility, collection and retention. MetaTables
neither opens cloud log stores directly nor stores hosted log bodies in its database.

Use the published SDK 9.0.1 or newer with the generic
operation-filter change and the matching platform owner-log implementation.
SDK/provider query tests pass; live hosted collector verification remains a
separate deployment check. Existing runs without capture references, and laptop
processes with no platform collection/forwarding path, report unavailable logs.
No new authentication mode or application-specific platform endpoint is required.

Existing catalogs need system revision `0003_run_log_capture`
([catalog migrations](catalog-migrations.md)), which adds nullable run capture metadata. Logs never create a catalog logging table.
The architecture and verification boundaries are recorded in
[ADR 0005](../adr/api/0005-run-logs-and-local-file-capture.md).
