# ADR 0012: Bounded data transfer, concurrent execution, and safe retries

Date: 2026-09-30

Status: Accepted.

Implementation status: Implemented with focused contract, API/client, migration,
and local SQLite verification. Hosted engine concurrency, cancellation and RSS
verification remains pending the explicitly authorized database matrix. No measured
throughput improvement is claimed. See the [shipped transfer guide](../../client/bounded-transfers.md).

Owner: MetaTables API. The Python client owns consumption, batching, and its
operation-specific HTTP retry policy; Main Sequence retains platform identity,
authentication, and deployment ownership.

Related decisions: [ADR 0001: Unified API storage](0001-unified-api-storage-and-local-sqlite.md),
[ADR 0003: Client endpoint resolution](../client/0003-api-endpoint-resolution.md),
[ADR 0007: Database-enforced access](0007-database-enforced-table-access.md),
[ADR 0008: Database backend contract](0008-mysql-mssql-table-workflows.md), and
[ADR 0010: External relation reads](0010-import-external-tables-and-views.md).

## Context

Query result sizes and uploaded row widths are not known in advance. The API
performs database I/O, result conversion, compression/decompression, authorization,
and catalog updates in the request path. Its memory, bandwidth, and concurrency
can become constraints even when the physical database has sufficient capacity.

The following findings are from source inspection on 2026-09-30, not production
benchmarks:

- `RestrictedSQL.execute()` uses ordinary cursors before fetching `max_rows`.
  PostgreSQL and MySQL drivers can buffer results before this response limit is
  applied. Limiting returned rows does not itself bound driver memory.
- `DatabaseAccess.admit_committed()` returns with the catalog lock held. SQL and
  time-index operations retain exclusive catalog coordination during physical
  execution, delaying unrelated requests in the same runtime.
- `post_data_frame_in_chunks()` starts with 50,000 rows, while the upload route
  accepts at most 10,000. Recursive splitting after HTTP 413 repeats work that
  the client could avoid before sending.
- Upload decoding allows 12,000,000 base64 characters, 8,000,000 compressed bytes,
  and 24,000,000 decompressed bytes. Outer request parsing precedes these checks,
  and decoded dictionaries and adapted records add further memory overhead.
- SQL reads have row/time limits. Relation reads additionally check an 8 MiB
  result limit after materialization. These paths do not share a byte-budget
  contract covering fetching and serialization.
- Time-range readers fetch pages and collect every row before constructing a
  DataFrame. Server pagination therefore does not bound client collection memory.
- The installed SDK request helper retries exceptions for mutations as well as
  reads. Upload chunk indexes are not durable receipts, so a lost response can
  cause an already committed write to be submitted again.

The existing physical-operation journal distinguishes confirmed failure from
unknown outcome for lifecycle operations. It does not currently implement data
chunk receipts. A new receipt cannot be assumed atomic with a physical write
merely because both connections address the same database.

### Affected public paths

| Path | Work covered by this decision |
| --- | --- |
| `POST /meta-tables/run-query/` | Bounded caller-SQL reads and conservative retry eligibility. |
| `POST /meta-tables/execute-operation/` | Incremental results, deadlines, and mutation outcome handling. |
| `POST /meta-tables/{uid}/read/` | Structured relation pages with incremental byte checks. |
| `POST /time-index-meta-tables/{uid}/get-data-between-dates-from-remote/` | Bounded pages and incremental client consumption. |
| `POST /time-index-meta-tables/get-data-between-dates-from-table-update/` | The same read contract for an update's output. |
| `POST /time-index-meta-tables/{uid}/get-last-observation/` | Byte/row limits for the latest rows across coordinates. |
| `POST /time-index-table-updates/{uid}/insert-data-into-table/` | Upload sizing, decoding, concurrent admission, chunk receipts, and recovery. |
| `POST /time-index-meta-tables/{uid}/delete-after-date/` | Mutation-aware retries, deadlines, and coordinated finalization. |
| `GET /time-index-table-updates/{uid}/set-last-update-index-time/` | Treat physical statistics refresh and catalog mutation as a write for retry policy. |

Inherited SQL actions under `/time-index-meta-tables/` receive the same behavior.
The client changes cover the corresponding methods and their DataFrame/updater
helpers. Ordinary catalog CRUD is not a bulk-transfer protocol; shared admission
changes must nevertheless preserve its permission and lifecycle coordination.

## Decision

### Scope and ownership

Implement bounded transfer and safe recovery through the existing MetaTables
HTTP service and Python client. Hosted traffic continues through Main Sequence;
local execution retains the same API contract and SQLite development workflow.
These data-transfer operations do not give clients database credentials or direct
database connections.

This work has no dependency on Artifacts, temporary storage URLs, a new platform
transfer service, or background Jobs. Those are possible later enhancements.
The first implementation retains bounded JSON requests and responses. It does
not require Arrow, Parquet, long-lived HTTP streams, or an external queue.

Engine-specific fetching, cancellation, and transaction mechanics belong behind
the existing backend contract. Routes do not branch on database drivers. Runtime
operations retain their selected source; external structured reads retain ADR
0010's source and read-only boundaries. The SDK continues to own authentication
and release discovery; MetaTables owns retry decisions for its data operations.

### Common transfer limits

Define a versioned API-owned transfer-limit contract with shared validation and
published defaults. Expose effective limits through the existing runtime-context
surface, without caching them as permanent endpoint properties. Include:

- Maximum rows per read page and upload chunk.
- Request, compressed, decompressed, and serialized response byte limits, with
  explicit units and rules for counting the response envelope.
- Maximum serialized row/value size and client collection budgets.
- An overall operation deadline covering admission, lock waits, connection setup,
  fetching, encoding/decoding, and retries, plus bounded concurrency/queueing.

Client options may request smaller budgets; they cannot enlarge server limits.
Client collection budgets describe counted bytes/rows, not an exact guarantee
about pandas' resident memory. Document conversion overhead separately.

Reject oversized request bodies while receiving them, before full JSON parsing;
count received bytes even when Content-Length is absent. Retain decompression
limits. Check result budgets while constructing a page, accounting for lookahead
and envelope overhead rather than checking only a completed response.

A single decoded field may already occupy driver memory before its size can be
checked. The target is bounded batches plus the largest decoded row; do not claim
an absolute process-memory ceiling from serialization limits alone. Enforce
concurrency limits and document this remaining bound.

### Upload batching

The client defaults to at most the server's current 10,000-row maximum and sizes
chunks by serialized bytes as well as rows. Validate encoded, compressed, and
decompressed sizes before transmission. Detect an oversized single row locally
with an actionable error. Keep HTTP 413 splitting as a compatibility fallback.

Prepare and send one bounded chunk at a time. Keep upload concurrency sequential
initially. Stable chunk identities are assigned to the final payload; splitting
must not reuse an identity with different content. Avoid sending client statistics
that the server deliberately ignores. Any later change to statistics maintenance
must preserve authoritative server-derived progress.

### Incremental database fetching

Extend the backend execution contract to consume results incrementally and close
owned resources explicitly. PostgreSQL/TimescaleDB and MySQL must use actual
streaming or unbuffered retrieval rather than `fetchmany()` over a fully buffered
result. MSSQL and SQLite must satisfy the same observable limits using their
native drivers. Capability checks must cover the installed driver versions.

Preserve caller SQL verbatim, restricted execution identities, parameter binding,
and each engine's supported command behavior. Do not introduce SQL authorization
parsing, table discovery from SQL, or LIMIT rewriting. A cursor implementation
that only accepts SELECT cannot silently replace the wider SQL command contract.

Bound both rows and bytes while assembling each JSON page. Return explicit
truncation and continuation information; preserve ADR 0007's conservative meaning
that a full SQL page may have more rows. Calculate continuation from rows actually
returned when a byte budget shortens a page. Do not consume and lose a row between
pages. An oversized first row must fail clearly rather than produce a zero-progress
continuation loop.

On early termination, deadline, disconnect, or error, cancel/close owned reads
and roll back or release their transactions as appropriate. Do not drain an
unbounded read just to return its connection to a pool. Backend cleanup must
account for drivers that otherwise exhaust remaining results during close.

Write completion is distinct from response truncation. Returning only a few rows
from a mutation must not imply cancellation or successful completion of the
remaining work. Preserve completion/error checks, including later MSSQL batch
errors and explicit commits in caller SQL. ADR 0007's lack of an atomic rollback
promise for such batches remains. An uncertain commit remains an unknown outcome.

### Concurrent admission and catalog finalization

Replace the shared exclusive catalog lock across physical execution with short
exclusive admission/reconciliation transactions and concurrent execution guards.
The guards must coordinate across processes and replicas, using backend-supported
shared/exclusive coordination or equivalent durable admission state. A Python
mutex or expiring lease alone does not establish that a database operation stopped.

Independent data operations may hold shared execution admission concurrently.
Permission publication, schema changes, and runtime changes coordinate exclusively
with affected admissions. Arbitrary SQL retains source-level coordination where
its affected tables are unknown; do not parse SQL to narrow that scope.

The protocol must establish these invariants before reducing existing locks:

1. No operation starts against pending native permission reconciliation or an
   incompatible source, contract, or runtime generation.
2. A revocation completes only after its native changes are published and affected
   earlier admissions have finished or have been cancelled and confirmed stopped.
   Stale admitted work cannot begin after that completed revocation. Existing
   platform membership-cache semantics remain governed by the identity layer.
3. Physical writes to the same target retain required serialization. SQLite
   retains its native single-writer constraint and explicit borrowed-transaction
   ownership; concurrency improvements do not override those guarantees.
4. Physical execution is followed by a short validated catalog finalization.
   Late completions cannot overwrite newer statistics or attach an outcome to a
   different table/source generation. Lock upgrades must not deadlock concurrent
   readers and finalizers.
5. Lock acquisition, cancellation, and cleanup obey bounded deadlines. Exceptions
   cannot leave a global admission block or release a caller-owned transaction.

Move bounded decoding outside exclusive catalog-lock periods and revalidate
authorization and target state before effects. Specify and test the concrete
coordination protocol for each backend before enabling concurrent execution;
simply committing immediately after authorization does not satisfy this decision.

### Retry policy and durable chunk receipts

Add a MetaTables-owned transport helper for affected data methods. Preserve SDK
authentication, single credential refresh, local admission headers, endpoint
pinning, and runtime/source identity. Control both the helper's retry loop and
HTTP adapter retries so the SDK's existing loop cannot replay writes underneath
the new policy. Ordinary platform SDK requests are unaffected.

Classify retry eligibility by the documented operation contract, not HTTP verb
alone: the statistics-refresh GET mutates catalog state. Read-only SQL transaction
mode is not by itself proof that arbitrary caller SQL has no external side effects.
Only explicitly retry-safe reads may retry automatically, before exposing a page,
within a bounded attempt count and overall deadline, with backoff and Retry-After
handling. Do not retry deterministic validation or permission errors.

For mutations without a durable deduplication contract, ambiguous transport
failure stops automatic replay and exposes a typed unknown-outcome error. This
also applies to generic SQL writes; chunk receipts do not make arbitrary SQL
idempotent.

Introduce catalog-backed chunk receipt records, with an explicit migration. Bind
each key to caller, runtime/source, target/update identity, write mode, and a
versioned digest of the exact logical payload. Claim execution atomically across
API processes. Store status and safe outcome metadata, not the dataset. Publish
status lookup and retained-receipt lifetime; keys must not silently become new
writes when their receipt expires. Status/receipt access requires authorization,
and a recorded receipt cannot bypass a later permission revocation.

| Receipt situation | Required behavior |
| --- | --- |
| Same key and payload, confirmed applied | Return the recorded acknowledgement without another physical write. |
| Same key, different payload or target | Reject with a conflict. |
| Execution in progress | Return inspectable status; do not start another writer. |
| Confirmed non-application | Permit a controlled retry of the same operation. |
| Unknown physical commit or missing final receipt after possible commit | Require reconciliation; do not replay automatically. |

Persist intent before physical effects. Distinguish physical success from catalog
receipt/statistics finalization, including failures between those steps. Reuse
existing journal conventions where suitable, but its current schema-operation
model is not already a data-transfer implementation. Do not claim exactly-once
execution across independently committed transactions.

Each chunk remains independently committed. Report partial upload completion and
retain an operation reference for recovery. Automatic retries preserve chunk keys;
recovery across client restarts requires an explicit retained operation identifier
and supported status/reconciliation path. A multi-chunk upload is not an atomic
replacement of the whole dataset.

### Library experience and compatibility

Existing small-read and write calls retain their familiar results and Main
Sequence authentication. Upload splitting, digest creation, and acknowledgement
handling are library responsibilities. Users need no Artifact, bucket, Job, or
database-driver setup for these improvements.

Add incremental relation and time-index readers with bounded prefetch, page-size
selection, overall budgets, and cancellation between requests. Yield batches
using the established column types, timezone, and index semantics. Existing
DataFrame helpers may collect from these readers within documented limits.

A DataFrame helper returns the complete requested result or raises an actionable
collection-limit error. It must not silently return a partial DataFrame. Explicit
SQL/table previews retain documented truncation metadata. Distinguish size-limit,
deadline, retry-exhaustion, key-conflict, and unknown-outcome errors, with safe
operation references where available and recovery guidance.

The implemented incremental interface is:

```python
for batch in table.iter_batches(
    start_date=start,
    end_date=end,
    columns=["timestamp", "value"],
):
    process(batch)
```

Retain existing pagination compatibility initially. Offset pages can observe
changes between requests; keyless/unordered previews have no stable snapshot
guarantee. The iterator does not promise a consistent export, unlimited traversal
past server offset limits, or replay of a partially consumed page without duplicate
delivery. A snapshot/export or wider cursor redesign is separate work.

Deploy additive API limits and receipt support before enabling dependent client
behavior. New clients detect the advertised contract, use conservative limits
with older servers, and never assume receipt support when absent. Older clients
retain supported calls and receive explicit errors for newly enforced bounds.
Document minimum versions and intentionally changed failure behavior.

## Relationship to existing decisions

This record amends only the following provisions; other provisions remain in effect.

| ADR | Amendment or extension | Preserved boundary |
| --- | --- | --- |
| 0007 | Specify admission lifetime and incremental resource bounds beyond a fetched-row count. | Database-enforced access, verbatim SQL, restricted identities, cancellation, and engine-specific transaction semantics. |
| 0008 | Extend backend resource ownership and outcome reporting to bounded fetching and data-chunk receipts. | Shared backend dispatch, explicit transaction ownership, and reconciliation for unknown outcomes. |
| 0010 | Apply common response-byte/deadline handling to structured relation reads. | External read-only admission, relation ownership, source separation, and preview consistency limitations. |
| 0003 | Document client consequences and capability refresh. | SDK release discovery, endpoint pinning, and separation of platform authentication from MetaTables transport. |

This does not transfer platform SDK decisions into this repository or supersede
the listed ADRs in full.

## Delivery and verification

Deliver in five reviewable steps:

1. Shared limits, client upload sizing, and conservative data-operation retries.
2. Incremental backend fetching and bounded HTTP response construction.
3. Concurrent admission, permission/lifecycle coordination, and validated finalization.
4. Catalog migration, chunk identities, receipts, status, and recovery semantics.
5. Client iterators, bounded collection, examples, and complete user documentation.

Use focused non-container unit, contract, API/client, and SQLite checks for routine
development. Cover byte/row boundaries, compressed expansion, single oversized
rows, short pages, cancellation, cleanup, retry deadlines, lost responses before
and after commit, duplicate concurrent submissions, payload conflicts, restart,
receipt retention, stale finalization, revocation races, and partial completion.
Use process RSS as well as Python allocation measurements when checking native
driver buffering. Compare growing result sizes at fixed page limits; do not
claim a throughput improvement without measurement.

Driver buffering, cancellation, lock behavior, and commit outcomes need targeted
real-engine verification before being described as verified for that backend.
Run container/database-matrix tests only when explicitly requested for the current
task, with only that run's resources cleaned up. An ADR does not authorize a test
run. Record engine/version coverage and remaining limitations; mocks alone do not
prove these guarantees. Runtime/backend tests remain manual, outside CI and
required merge checks. CI stays limited to package validation, lint, and docs.

Measure admission/lock wait, fetch time, encoding/decoding time, transferred bytes,
returned rows, cancellation, peak memory, retries, and unknown outcomes. Correlate
with safe operation IDs without logging credentials, SQL parameters, or row data.

## Required documentation and completion criteria

**User-facing and operational documentation is a required implementation
deliverable. This ADR alone is not sufficient documentation. The feature must not
be marked implemented until the relevant guides, references, examples, and recovery
instructions describe the shipped and verified behavior.**

Update these authored surfaces as each corresponding behavior ships:

| Surface | Required content |
| --- | --- |
| [Query and mutate](../../client/query-and-mutate.md) and [time-index readers](../../client/read-existing-time-index-tables.md) | Complete DataFrame versus batch consumption, actual method signatures, limits and units, types/indexes, truncation, pagination consistency, cancellation, and an executable large-read example. |
| [Updaters](../../client/build-an-updater.md) | Automatic row/byte batching, chunk acknowledgements, partial commits, operation identifiers, retry behavior, and recovery across restarts. |
| [Authentication and errors](../../api/authentication-and-errors.md) and [time-index API](../../api/time-index-and-updates.md) | Limit discovery, HTTP/status contracts, typed client errors, conflict and unknown-outcome examples, status lookup authorization, and documented next actions. |
| [Configuration](../../operations/configuration.md) and [hosted runtime](../../operations/hosted-runtime.md) | Effective defaults, ingress/body limits, deadlines, concurrency, rollout compatibility, and how to distinguish lock, fetch, memory, and bandwidth constraints. |
| [Recovery and observability](../../operations/recovery-and-observability.md) and [catalog migrations](../../operations/catalog-migrations.md) | Receipt lifecycle/migration/retention, safe retry versus reconciliation, partial uploads, restart handling, and limits of atomicity and exactly-once claims. |
| [Security behavior](../../concepts/permissions-namespaces-labels.md) | Admission and completed-revocation guarantees, coordination of in-flight work, and unchanged platform identity/cache boundaries. |
| [Capabilities](../../reference/capabilities.md), generated Python/HTTP references, and [examples](../../examples/README.md) | Real supported signatures/endpoints, versions, executable examples in the source examples directory, capability evidence, and remaining backend limitations. |

Follow the [documentation workflow](../../contributing/documentation.md): edit
authored guides and source examples, update the capability inventory and relevant
client usage skills, and regenerate derived references/example copies rather than
editing generated output directly. Update installation/upgrade guidance for mixed
client/API versions and changed failures. Check links, snippets, and the strict
documentation build; execute relevant examples as part of focused verification.

Keep proposed names and unimplemented behavior in this ADR until they ship. Record
implementation and verification status separately from decision acceptance in
this record and the ADR index. Keep navigation and predecessor cross-links current.

## Alternatives and consequences

- Increasing API workers alone leaves shared exclusive locks, unbounded driver
  buffers, and unsafe retries intact.
- Raising row limits or HTTP timeouts increases exposure to large transfers.
  Row count alone does not represent payload size.
- Adding HTTP streaming without incremental database fetching preserves the
  upstream memory problem and introduces longer connection lifetimes.
- Automatically retrying all failures can repeat committed mutations. Always
  calling a write an upsert does not establish idempotency for overwrite ranges,
  arbitrary SQL, or concurrent writers.
- Moving immediately to Artifacts, signed URLs, or Jobs adds platform dependencies
  without resolving the current execution and retry contract. Those remain future
  decisions and are not prerequisites.

The tradeoffs are additional transport/receipt state and recovery logic,
earlier explicit size errors, and conservative stopping on uncertain writes.
Bandwidth still passes through Main Sequence. Batching improves predictability;
it does not remove the cost of moving data or promise a snapshot across pages.


## Implementation record (2026-09-30)

Transfer v1 is opt-in on the runtime descriptor query to preserve older clients'
strict schema validation. Fixed defaults are in the pure shared transfer contract;
request admission runs before JSON parsing. Collection budgets count compact JSON,
not pandas RSS. PostgreSQL uses single-row libpq streaming for verbatim SQL and
named cursors for generated reads; MySQL uses unbuffered cursors. SQL writes finish
result sets before reporting completion. Read cancellation does not drain remaining
MySQL results. Psycopg is pinned to 3.3.6 because its command-stream specialization
uses a version-sensitive cursor hook. Driver integration and native allocation
measurements must precede production rollout on each hosted engine.

Hosted admission uses a shared SQL security-state row lock; reconciliation drops
that read-only transaction and reacquires an exclusive lock before publishing.
MSSQL uses XLOCK for publication, because UPDLOCK alone is compatible with readers.
MySQL catalog transactions use READ COMMITTED. SQLite retains BEGIN IMMEDIATE for
all admissions to preserve revocation under WAL. Known table writers and statistics
refresh lock the table before physical work and retain that lock through catalog
finalization. No shared-to-exclusive lock upgrade occurs in data finalization.

Migration `0008_upload_receipts` records durable intent before effects and retains
keys indefinitely. Stable keys derive from operation UUID and starting row position;
digests bind exact logical records and identity/mode metadata. A separate attempt
UUID fences late arrivals after administrator reconciliation. The API records
operator evidence only after taking exclusive admission; it never infers an outcome
from receipt age. A crashed or failed finalization can still leave `running`, which
requires inspection. Statistics refresh after an operator-confirmed applied outcome
remains an explicit recovery step.

Authored guides, consuming skills, generated references, and the executable bounded
reader accompany the implementation. `metatables.transfer` logging records queue,
elapsed time and wire bytes without datasets or SQL. Database wait/fetch timings
and RSS still require targeted operational measurement; this record does not claim
a completed production benchmark or universal memory bound.

The retry policy follows Microsoft's guidance to classify idempotency and avoid
nested retry layers: [Retry pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/retry).
Driver lifetime details are documented in [Psycopg cursors](https://www.psycopg.org/psycopg3/docs/api/cursors.html)
and [PyMySQL cursors](https://pymysql.readthedocs.io/en/latest/modules/cursors.html).
