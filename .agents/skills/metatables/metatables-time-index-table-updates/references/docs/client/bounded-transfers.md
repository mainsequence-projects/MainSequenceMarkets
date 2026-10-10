# Bounded reads, uploads, and recovery

All data continues through the Main Sequence MetaTables API. No Artifact, storage
URL, bucket, Job, or client database connection is required. Small reads retain
their existing return types. Large reads can now stop with an explicit limit
error instead of collecting indefinitely, and uncertain writes stop for recovery.

## Discover limits

The version 1 contract is available from
`GET /runtime-context/?transfer_contract=1` in `transfer_limits` and from the
updated client's `get_runtime_context().transfer_limits`. Responses are not
permanently cached. Uploads refresh capabilities for each call. The query parameter
keeps the new field out of descriptors consumed by older strict clients.

| Budget | Default |
| --- | --- |
| Read page / upload chunk | 10,000 rows maximum; time reads request 500 by default |
| Request body | 12,100,000 received bytes, including requests without Content-Length |
| Upload base64 / gzip / decoded JSON | 12,000,000 / 8,000,000 / 24,000,000 bytes |
| Individual serialized row | 1 MiB |
| Response | 8 MiB including its JSON envelope; pages reserve 64 KiB for metadata |
| Client collection | 100,000 rows and 64 MiB of counted JSON bytes |
| Transfer deadline | 60 seconds by default |
| Concurrent data requests | 8 per API process; queue wait up to 1 second |
| Receipt retention | Indefinite, including after table deletion |

MiB means 1,048,576 bytes. Limits bound serialization and retained batches, not
exact pandas or process memory. A driver must decode an individual field before
its size can be checked. Python objects, conversion, native buffers, and concurrent
requests add overhead. A large SQL statement also remains subject to its existing
statement-length limit. Server limits cannot be raised by client options.

## Consume batches

```python
from metatables import TimeIndexTableRef

reference = TimeIndexTableRef.from_uid(table_uid)
for frame in reference.iter_batches(
    start_date=start, end_date=end, columns=["balance"],
    page_size=500, max_rows=1_000_000, max_bytes=256 * 1024 * 1024,
    deadline_seconds=300,
):
    process(frame)
```

`TimeIndexMetaTable.iter_batches()` and `TimeIndexTableRef.iter_batches()` yield
typed DataFrames with the existing UTC nanosecond time index and dimension index.
Updater outputs expose the same reader. No page is prefetched: breaking the loop
stops further requests. Each page still has its own server deadline. Iterator
budgets include time spent processing already yielded pages. Use `iterator.close()`
when explicitly retaining an iterator you no longer need.

`MetaTable.iter_rows(columns=..., filters=..., order_by=..., page_size=100)` yields
lists of relation row dictionaries. It accepts the same `max_rows`, `max_bytes`,
and `deadline_seconds` collection options. `read_rows()` and SQL calls remain
explicit previews with truncation metadata. A byte-limited page can be shorter
than its requested row count; continuation advances by the rows actually returned.
SQL full pages conservatively indicate that more rows may exist.

`get_df_between_dates()`, `get_data_between_dates_from_api()`, and
`get_data_between_dates_from_table_update()` accept these collection options and
`page_size`. They return the complete selection or raise `TransferLimitError` or
`TransferDeadlineError`; they do not return a partial DataFrame as success. The
lower-level date methods retain their previous raw-column DataFrame return shape.
Latest-observation calls fail if the complete coordinate set exceeds a budget;
narrow the dimension filters.

Pages use offsets, capped at 1,000,000. Concurrent changes can move rows between
pages. Ordering helps traversal but is not a consistent snapshot or export.
See the executable [batch reader](../examples/bounded_reader.py).

## Upload and recover

`TimeIndexTableUpdate.post_data_frame_in_chunks()` defaults to 10,000 rows and
also checks serialized, compressed, encoded, and outer request bytes. It sends
one chunk at a time, omits client statistics, and splits HTTP 413 responses as a
compatibility fallback. A single oversized row raises a local limit error.
The API computes authoritative statistics.

For a restartable upload, retain a UUID before beginning:

```python
from uuid import uuid4
from metatables import TimeIndexTableUpdate
from metatables.transfer import TransferOutcomeUnknown

operation_id = str(uuid4())  # Persist with the input/version and chunk_size.
try:
    TimeIndexTableUpdate.post_data_frame_in_chunks(
        frame, table_update=update, operation_id=operation_id,
        chunk_size=10_000, overwrite=False, deadline_seconds=300,
    )
except TransferOutcomeUnknown as error:
    receipt = update.upload_receipt(error.chunk_key)
    record_for_recovery(error.operation_id, error.chunk_key, receipt)
```

Success returns the operation UUID. Later upload errors carry `operation_id`,
`chunk_key` when assigned, and `completed_chunks`. Keep the same input, row order,
mode, target, operation ID, and chunk settings when resuming. Changing payloads
under an existing key raises `TransferConflictError`. Changed server limits may
change chunk boundaries and cause a conflict; investigate instead of assigning
new keys to already applied rows.

Each chunk commits independently. An interrupted upload can leave earlier chunks
applied; this is not an atomic replacement of an entire DataFrame. A receipt does
not provide exactly-once execution across separate physical/catalog commits.

| Receipt status | Next action |
| --- | --- |
| `applied` | Resubmission with the same key and payload acknowledges it without writing again, after current authorization. |
| `running` | Wait or investigate the request. A crashed process can leave this state; age alone never permits replay. |
| `failed` | Confirmed non-application. Explicit `retry_failed=True` permits a new attempt with the same key. |
| `reconciliation_required` | Inspect the physical rows and catalog state before deciding whether the chunk applied. |

Status lookup requires the original caller and a current table edit grant.
Reconciliation requires a platform administrator with current table access:
after checking data through the platform's read APIs, use
`update.reconcile_upload_receipt(key, outcome="applied" | "not_applied", evidence=...)`.
This records an operator attestation, waits for active database admissions, and
fences earlier attempts that have not started. It does not infer success from
elapsed time. Refresh table statistics after resolving an applied outcome.
Never mark `not_applied` merely to bypass an uncertain outcome.

## Retries and compatibility

Only documented safe reads retry automatically, at most three attempts with
backoff and `Retry-After` inside the deadline. Arbitrary SQL, uploads, deletes,
statistics refresh (even though it uses GET), and receipt reconciliation do not
automatically replay after uncertain failures. SDK authentication and one
credential refresh remain; SDK and HTTP adapter write retry loops are bypassed.

Capacity answers are the exception: 429 `transfer_capacity_exceeded` and 503
`database_connections_busy` mean the API was at capacity and no statement ran.
Retry any request after `Retry-After`, including SQL and writes; the client does
so automatically only for safe reads.

Exceptions are available in `metatables.transfer`: `TransferLimitError`,
`TransferDeadlineError`, `TransferRetryExhausted`, `TransferConflictError`, and
`TransferOutcomeUnknown`. Deterministic authorization/validation errors retain
the existing SDK error translation. An unknown outcome requires investigation,
not a fresh operation ID.

Deploy the API catalog migration `0008_upload_receipts` before updated clients.
Transfer contract version 1, rather than the shared development package version,
identifies receipt support. Older APIs use conservative client limits and receive
legacy payloads without receipt fields; those uploads cannot be safely resumed
after an uncertain failure. Older clients still receive server bounds but retain
their old retry behavior, so upgrade writers as part of rollout. PostgreSQL
streaming currently pins psycopg 3.3.6 because command-result handling specializes
its stream cursor; upgrading that dependency requires protocol and engine tests.

SQLite workflows and focused failure tests are verified locally. PostgreSQL,
TimescaleDB, MySQL, and SQL Server driver cancellation, locking, and native-memory
behavior require the separately authorized engine matrix before production
rollout. No throughput or RSS improvement is claimed from unit tests.
