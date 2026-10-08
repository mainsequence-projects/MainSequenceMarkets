# ADR 0006: Historical run graphs and the Runs menu

Date: 2026-09-29

Status: Accepted.

Implementation status: Implemented. Verified with migrated SQLite/PostgreSQL
catalogs, actual client/HTTP tutorial executions and Admin contract/build checks.

Owner: MetaTables API, which owns persisted run history and its read contract.
The Python client reports execution progress; Admin presents the history.

Related decisions: [API ADR 0001: Unified API storage](0001-unified-api-storage-and-local-sqlite.md),
[API ADR 0002: Administration and table ownership](0002-application-administration-and-table-ownership.md),
and [API ADR 0005: Run logs and local file capture](0005-run-logs-and-local-file-capture.md).

## Context

Historical updates already record individual updater executions as `UpdateRun`
rows. The root updater and its executed dependencies share the runner's execution
UUID, currently stored in `UpdateRun.trace_id`. ADR 0005 binds each attempt's logs
to its exact run UID and carries that shared UUID as
`data.metatables.execution_uid`.

The current dependency graph reads registered relationships and each updater's
mutable `UpdateDetails.active_update_status` and `last_update`. It does not select
an execution. Its success indicators can therefore describe different invocations,
and its downstream consumers need not have participated in the selected updater's
execution. Historical updates, this graph and the recent-logs view are separate
Admin views without a common selected run.

The missing capability is a historical graph attached to the existing run history.
Grouping runs by their shared UUID alone cannot recover dependencies that never
started, the original graph after dependencies change, or the root relationship.

## Decision

### Ownership and identity

Main Sequence Jobs owns scheduling and platform job execution. MetaTables records
updater execution and its dependency results. This decision adds no schedule,
cron configuration, job launcher, queue, retry engine or platform job model.

Use the existing root `UpdateRun.uid` as the public identity of a graph run. One
invocation has one root run and its dependency runs. A later invocation creates a
new root run even if the updater, day or platform job is the same. A single-updater
invocation is a valid graph run with no executable dependency nodes.

The shared execution UUID remains correlation metadata, not an additional public
run resource or an OpenTelemetry trace ID. A platform `JobRun` reference is
optional external metadata, supplied by the workload and used through the SDK.
One platform job can contain multiple MetaTables invocations; local invocations
need no platform job. Do not infer scheduling information from timestamps or
require a platform lookup to create, list or display a MetaTables run.

### Extend existing historical updates

Persist a graph extension associated one-to-one with the root `UpdateRun`, and
explicitly associate dependency `UpdateRun` records with that root. Keep existing
run UIDs, timestamps, outcomes and log-capture descriptors. Do not duplicate run
history in a parallel execution system.

The extension contains:

- An immutable, versioned snapshot of the executed plan: root updater, participating
  updater identities and hashes, output/input table identities, safe display
  labels, declared dependency edges and the invocation's execution options.
- Per-node execution state, timestamps and a bounded outcome/reason code. Updater
  nodes link to their existing `UpdateRun` records when an attempt starts.
- Explicit membership of each dependency run under the root. A shared dependency
  reached through multiple paths is one node in this invocation.

Snapshot only the plan for this invocation. Unrelated downstream consumers belong
in the dependency overview, not the execution graph. If dependency execution is
disabled, referenced inputs may appear as input context but must not be presented
as updaters scheduled to run. Table-reference dependencies are inputs, not attempts
with a fabricated success result.

Capture topology from the validated source-declared plan used by the runner,
after its existing registration and dependency reconciliation. The API validates
membership, registered edges, execution options, acyclicity and bounds before
admitting it. A caller cannot attach arbitrary runs to another root by reusing its
correlation UUID. Once admitted, execution must follow the captured plan; later
definition changes cannot silently replace it.

The snapshot records structure and safe metadata, not table contents, credentials,
full updater configuration or log bodies. Historical graph retention follows
catalog run-retention and deletion rules; this decision does not promise retained
history after its owning tables and run records are explicitly deleted.

### Recording lifecycle and node states

Extend the existing start/finish execution flow rather than introducing a second
client orchestration path. Root admission atomically creates the root run, its
graph snapshot and initial node states before any updater calculation begins.
Dependency admission atomically creates its run and links it to the admitted root
and node. Completion updates the existing run result and its graph node together.
Validate transitions and retain the existing active-update protections.

Transport retries with the same admission identity must return the same run and
snapshot; they must not duplicate execution history. Conflicting retries fail
explicitly. Repeated matching completion is idempotent, and an ended run's result
cannot be overwritten. A new user invocation uses a new admission identity.

Use these node states:

| State | Meaning within the selected invocation |
| --- | --- |
| Pending | Planned work has not started, including waiting for dependencies. |
| Running | This node's updater work has started and has no recorded completion. |
| Succeeded | This node's attempt completed successfully in this invocation. |
| Failed | This node's own attempt failed. |
| Blocked | A required dependency failed, preventing this node's work. |
| Skipped | The executor explicitly decided not to perform this work and recorded why. |
| Not run | The invocation ended before this planned work was reached. |

Do not infer a skip or freshness from missing logs, old update statistics or an
absent run row. An empty successful update is still successful unless the executor
explicitly reports a different outcome. Independent pending nodes left behind by
the current fail-fast runner are not run; nodes prevented by a failed dependency
are blocked. Missing attempts must never borrow a previous invocation's success.

The existing root run spans dependency evaluation as well as root calculation.
Its interval and outcome describe the whole invocation. Record the root graph
node's calculation phase separately: while dependencies execute it is pending,
and if a dependency prevents its calculation it is blocked even though the root
run records an unsuccessful invocation. Do not present the root's total duration
as its calculation duration.

Known completion finalizes remaining node states and the root result. An abrupt
client exit or lost completion request leaves an explicitly unfinished record;
the UI must not claim that it is currently executing or succeeded merely because
there is no end timestamp. API restart and missing/expired logs do not finalize
runs. Automatic failure detection, cancellation and new retry behavior are outside
this decision. Failures before root admission remain setup failures without a
graph run, as with pre-run logging in ADR 0005.

### API read contract

The existing run resource provides the following reads:

| Read | Purpose |
| --- | --- |
| `GET /table-update-runs/?root_only=true` | Paginated invocation history for the Runs menu. |
| `GET /table-update-runs/{run_uid}/graph/` | Resolve the run's root and return its saved graph and execution-specific states. |
| `GET /table-update-runs/{run_uid}/logs/` | Existing exact-attempt logs from ADR 0005. |

The default run collection continues to support individual updater history and
its existing `table_update_uid` filter. Root-history reads support root updater,
outcome and start-time interval filters, applied before pagination, with stable
ordering by start time and UID. Return root UID, updater label, timestamps,
duration, recorded outcome, graph availability and optional platform job reference.

The graph response includes its root run UID, snapshot version, saved nodes and
edges, per-node state/timing and exact attempt run UIDs. Opening a dependency run
resolves the same root graph with that node selected. Only live state refreshes
while an invocation is unfinished; its topology remains the admitted snapshot.

Keep the current definition endpoint for exploring registered dependencies. It
must not supply status to a historical graph. Label any latest-state indicators
there explicitly and link to their run where known.

Require current table Reader access on every read, including each node and its
logs. Root access does not grant access to dependency tables. Filter hidden nodes
and edges without exposing their saved identifiers, labels or logs, and indicate
that a permitted graph is incomplete. The root's permitted run outcome remains
its recorded outcome, not an aggregate recomputed from the visible subset.
Deletion or revocation must not be bypassed using saved snapshot metadata.

Graph recording requires the existing execution permissions. Apply the same
runtime binding and limits in local and hosted modes. Start with the existing
graph bounds of 500 nodes and 2,000 edges, add a finite serialized snapshot size
limit, and reject oversized plans before execution rather than silently truncating
historical evidence. Page history and bound graph reads; do not scan all log files
or invoke platform log retrieval merely to render a graph.

### Admin: Runs menu and graph details

Add a top-level **Runs** navigation item, separate from **Time Index Table Updates**,
which continues to describe configured producers. `/runs` lists one row per root
invocation, with root updater, recorded outcome, start/end, duration and the filters
above. Multiple invocations on one day remain separate rows. This menu lists
MetaTables run history and contains no scheduling controls.

Selecting a row opens `/runs/{root_run_uid}` with that invocation's graph. Show
the selected run identity, timestamps and outcome prominently. Permit switching
to another invocation of the root updater without losing the execution scope.
Refreshing an unfinished run updates that same run, never switches to the latest
one. URLs retain the selected run and, where applicable, selected node/attempt.

Admin uses a split view: a paginated list of timestamped runs on the left and
the selected invocation's graph on the right (stacked on narrow screens). Reuse
this view in a table's Updates tab and an updater's Historical Updates tab.
Table history filters by `output_table_uid` before pagination and includes
dependency attempts, whose graph endpoint resolves their original root run.
Selecting a node highlights its connections without removing any visible saved
nodes or edges. In particular, upstream producers' output tables remain visible.
Provide direct links to each updater and table, and separate the selected node's
updater dependencies, input tables, output tables, and consumers in its inspector.
The history list can collapse without resetting run selection or pagination.
Anchor the compact node details inspector inside the graph's lower-left corner;
do not repeat node details below the graph. Keep logs visible in a dedicated,
full-width section below the graph, with filtering, refresh and cursor navigation.
Selecting an updater reads that exact attempt. Selecting a table or clearing the
inspector shows the root attempt, explicitly labeled with its updater and run UID.
Collapsing history or closing the inspector must not hide the log viewer.

Selecting an updater node shows its state, timing, reason and exact run logs.
Nodes without attempts explain why no logs exist. If an attempt's logs have
expired or are unavailable, preserve the historical graph and its catalog result.
Reuse ADR 0005's log reader, cursor navigation and availability states; do not
filter a recent updater-wide log page in the browser to approximate exact logs.

Link existing historical-update rows to the corresponding graph and selected
node. Keep the definition graph available for exploring current relationships;
its title and context must distinguish it from a selected historical execution.

### Existing records and rollout

Use an explicit catalog migration through the existing Settings workflow. Add
nullable graph/membership metadata so existing update history and logs remain
readable. Existing records without captured topology report **Historical graph
unavailable**. A shared UUID can aid investigation but cannot justify inventing
old edges, root membership or missing-node outcomes from today's definitions.
Do not silently exclude all older records from access to historical updates.

The client reports the admitted plan and node transitions through the API in both
runtime modes. It never writes the catalog directly. No SDK authentication,
Environment, Organization, endpoint discovery or platform scheduling changes are
required. No new environment variables or separate local execution path are added.

## Implementation sequence and acceptance

1. Add graph/membership persistence, admission validation and lifecycle updates to
   the existing run flow. Verify idempotent start/finish, transaction rollback,
   shared-dependency deduplication and conflicting active-run protections.
2. Update the client runner to report its actual plan and phase transitions while
   retaining exact run/log correlation. Verify root success, dependency failure,
   blocked root calculation, independent nodes not reached, explicit skips,
   single-node execution and dependency execution disabled. Preserve the original
   updater exception if reporting completion also fails.
3. Implement the filtered root-history and graph reads. Verify current grants,
   hidden/deleted resources, bounded requests and stable pagination. Restart the
   API and confirm saved graph and states survive without consulting logs.
4. Add the Runs menu, run detail graph and links from existing history. Verify two
   invocations of the same updater display different outcomes without contamination,
   changing dependencies afterwards does not rewrite either graph, and selecting
   a node reads only its exact attempt's logs.
5. Exercise the same client-to-API lifecycle in SQLite and hosted-catalog tests,
   with and without a platform job reference. Verify unfinished execution, expired
   logs, legacy history without graphs and runtime switching do not invent state
   or mix stores. There must be no new scheduling or platform identity request.
6. After behavior is verified, update the API reference, capability inventory,
   client updater guide, run/log operations guide and Admin documentation. Mark
   implementation status separately from acceptance of this decision.

## Consequences

Run history gains bounded catalog metadata for topology and node outcomes while
reusing existing attempts and log capture. This is execution metadata, not the
log-body database storage excluded by ADR 0005. Recording transitions adds API
work, but makes the graph durable and independent of subsequent executions and
log retention. The existing definition graph remains useful for relationships;
the new Runs view answers what happened during a selected invocation.

## Implementation evidence

Revision `0004_historical_run_graphs` adds nullable admission/membership fields
to `UpdateRun` and the one-to-one `UpdateRunGraph` extension. The snapshot is
immutable; bounded node-state JSON is updated under the catalog mutation lock.
Snapshot size is limited to 1 MiB in addition to the node/edge bounds. The Python
runner freezes its reconciled dependency plan before admission and awaits each
dependency's recorded completion before advancing.

`tests/e2e/test_run_graphs.py` exercises HTTP admission, concurrent retries,
rollback, history filters, dependency-only and disabled-dependency execution,
per-invocation states, changed definitions, restart, visibility and legacy records
against migrated SQLite and PostgreSQL catalogs.
`tests/e2e/test_sqlite_runtime.py` executes actual tutorial producers through HTTP,
verifies saved graphs across API restart, then fails a dependency and checks the
blocked root and exact local attempt logs without changing the earlier graph.
Admin transport tests verify invocation selection and exact-attempt log routing;
its type checks, SDK/theme checks and production build validate the Runs integration.

Existing stores still require an explicit Settings migration. See
[Run history and graphs](../../operations/run-history.md) for the implemented
workflow and unfinished-run limitations. Live hosted log-collector verification
remains the separate outstanding item in ADR 0005.
