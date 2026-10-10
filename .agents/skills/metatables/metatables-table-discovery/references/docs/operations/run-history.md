# Run history and execution graphs

Start with [Runs and execution graphs](../concepts/runs-and-execution-graphs.md)
for the distinction between updater definitions, root runs, and dependency attempts.

Each invocation of a Python updater records a root update run and a saved graph
of its executable dependencies and table inputs. Main Sequence Jobs owns
scheduling. MetaTables records what happened when the updater ran, whether called
from a job or a local Python process.

## Find an execution

In Admin, open **Runs**. The left-hand list shows all recorded attempts by default,
including dependency attempts and older records without a captured graph. Each
entry shows its timestamp, outcome and duration; dependency attempts are indented
under their invocation's root when both are on the page. Select one to inspect its
invocation and logs. The filters head the list: updater, outcome, a start-time
range (last hour, 24 hours, 7 days or a custom local-time range) and **Root
invocations only**. **Clear filters** keeps the selected run.
The URL keeps these filters and the selected run. On narrow screens, the list
appears above the run.
Use **Hide history** to give the run the full width; **Show history** restores
the same list, page, and selection.

A table's **Updates** tab and an updater's **Historical Updates** tab use the same
view, scoped to that resource. Table history includes dependency attempts; opening
one shows its original root invocation and selects the corresponding updater.

The run header names the selected record's updater, outcome, duration, start time
and UID, and says whether it is the root attempt or a dependency attempt of its
invocation. Only a root record's duration includes the entire dependency
execution. Updater and output actions refer to the selected attempt; **Parent
execution** opens its root separately. Records without a graph still show their
own details and logs when available.

**Invocation** draws the saved graph as a timeline: one row per updater attempt on
the invocation's clock, dependencies first. The pale bar is the attempt record,
from admission to completion; the solid bar is the calculation the node reported;
a dashed line shows the wait between its dependencies finishing and its next
recorded start. Bars take the node state's theme color. Blocked, not-run and
preparation-failed nodes show a marker when the invocation resolved them. Each row
names the table it writes; its name opens that attempt. Log events appear as ticks
on their attempt's row, colored by level. The selected record's row is
highlighted. **Lineage graph** opens the saved table and updater topology on
demand.

**Logs** reads the whole invocation by default, in time order, with times counted
from the invocation start and each line's attempt named. **This attempt** narrows
it to the selected record. Filter by level, refresh, or load more; select a line
for its exception and structured context. Hovering a line highlights its tick on
the timeline. Hiding history does not hide logs. **All runs of this updater**
filters history to the same producer.

| Node state | Meaning |
| --- | --- |
| Pending | Planned work has not started. |
| Started · unfinished | Calculation start was recorded, but completion was not. |
| Succeeded | This invocation recorded a successful attempt. |
| Failed | This node's attempt failed. |
| Blocked | A required dependency failed before this node could calculate. |
| Skipped | The executor explicitly skipped calculation and recorded a reason. |
| Not run | The invocation ended before reaching this node. |

An unfinished invocation does not prove that its Python process is still running.
No heartbeat, automatic failure detector or scheduler is introduced. Failures
before admission do not have an execution graph. An empty successful update is
still success; it does not automatically mean the executor reported a skip.

The root update run starts before its dependencies. Its graph node's calculation
starts only after those dependencies complete. A failed dependency can therefore
leave a failed invocation with a blocked root node and no root calculation time.
Independent pending nodes left behind by fail-fast execution appear as not run.

Table nodes are input/output context, not successful updater attempts. Dependency
execution disabled through `update_tree=False` captures only the root updater's
attempt and its input context. `update_only_tree=True` executes dependencies and
records the root calculation as skipped with reason `dependencies_only`.

## History stays tied to its execution

The saved graph contains the admitted dependency structure and safe labels, not
the current definitions. Running the same updater again or changing its
dependencies does not recolor or redraw an earlier execution. The existing
definition graph remains available for exploring registered inputs and consumers;
its status indicators are explicitly labeled as latest state.

Current table access applies to historical graphs and logs. Hidden or deleted
resources are omitted and the graph is marked partial. The permitted root's
recorded outcome is preserved even when some dependency nodes are hidden.

Graph records remain available after [logs expire](run-logs.md). Missing logs do
not change success or failure. Nodes that never started have no attempt logs.
History created before graph capture remains visible in **Runs** and the producer's
Historical Updates tab and displays **Historical graph unavailable**; present-day
definitions cannot reconstruct that history reliably. Explicit root-only filtering
excludes attempts whose root identity was never recorded.

## Python and API access

```python
from metatables import TableUpdateRun

for run in TableUpdateRun.filter(root_only=True, limit=25):
    graph = run.get_graph()
    print(run.uid, graph["outcome"])
    for node in graph["nodes"]:
        if node["kind"] == "update" and node["run_uid"]:
            attempt = TableUpdateRun.get(uid=node["run_uid"])
            logs = attempt.get_logs(level="error", limit=50)
            print(node["label"], node["state"], logs.availability)
```

`GET /table-update-runs/?root_only=true` lists root invocations. The existing
`table_update_uid` filter selects the root updater. `outcome` accepts `unfinished`,
`succeeded` or `failed`. `start_time` is inclusive and `end_time` exclusive; both
must include a timezone. Filters apply before pagination, ordered by descending
start time and UID. `limit` accepts 1–500 and `offset` is nonnegative.
Without `root_only`, `output_table_uid` selects attempts by updaters that write
the selected table, including attempts made as dependencies of another root.

`GET /table-update-runs/{run_uid}/graph/` accepts either a root or dependency run
and resolves the saved root graph. It returns the root identity, selected node,
saved topology, per-node attempt UIDs and states, and visibility/availability
information. Graph reads query the catalog without querying a platform log store.

The runner supplies `graph_plan` and `admission_uid` to the existing
`set-start-of-execution` action. Dependencies use `root_run_uid` and their own
admission UID. The API validates the declared plan against registered dependencies
before execution and rejects conflicting admissions. Transport retries reuse the
same admission identity; new invocations use new identities.

The runner reports calculation start or explicit skip through
`PATCH /table-update-runs/{run_uid}/node-state/`; the existing finish action records
completion and finalizes node outcomes. Dependency completion is awaited before
starting its consumers. Low-level start calls without a plan preserve their
existing individual-run behavior and have no captured graph.

Plans are limited to 500 graph nodes, 2,000 edges and a 1 MiB serialized snapshot.
Oversized plans fail before calculation rather than returning truncated history.
Snapshot and state metadata use the selected catalog; log bodies remain in the
stores defined by the logging contract.

Existing stores require system revision `0004_historical_run_graphs`. A hosted
deployment applies it before the API rolls out. Locally, restart the API with the
updated code, then apply pending migrations explicitly in Settings. Local and hosted
runtimes use the same migrations and run lifecycle.
