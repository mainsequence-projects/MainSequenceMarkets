---
name: metatables-time-index-table-updates
description: "Build or review TimeIndexTableUpdater producers, configuration hashing, dependencies, incremental frames and table readers in applications using the MetaTables Python client. Covers the node Job that runs a producer graph in parallel Job runs. Excludes client-library implementation, API routes, other scheduling and runtime administration."
---

# MetaTables client time-index producers

## Client scope

Apply this skill to applications that consume the installed `metatables` Python
client. It covers application-facing models and workflows. Client-library
implementation, this repository's development/release tooling, and API internals
have separate ownership.

The `metatables/examples/` files named in this skill ship inside the installed package;
`python -c "import metatables.examples as e; print(e.__path__[0])"` prints their folder.

For application development and mutation tests, use the
[local development skill](../metatables-local-development/SKILL.md) to select and
verify local SQLite before writing, then return to the intended environment after
verification within the requested scope.

Read [Build an updater](https://potential-doodle-wn39mnm.pages.github.io/client/build-an-updater/),
[Time-index tables and updates](https://potential-doodle-wn39mnm.pages.github.io/concepts/time-index-tables-and-updates/), and the tested
`metatables/examples/updater.py`. Use [Read existing time-index tables](https://potential-doodle-wn39mnm.pages.github.io/client/read-existing-time-index-tables/) and
`metatables/examples/reader.py` for consumers that only need existing output.

The storage contract is a `PlatformTimeIndexMetaTable` SQLAlchemy class. The
producer is a `TimeIndexTableUpdater`; the API record is `TimeIndexTableUpdate`.
Use the [table skill](../metatables-meta-tables/SKILL.md) for storage design and the
[migrations skill](../metatables-migrations/SKILL.md) for table evolution. API
route behavior is documented in [Time-index data and update operations](https://potential-doodle-wn39mnm.pages.github.io/api/time-index-and-updates/) and supported
capabilities in [Supported capabilities](https://potential-doodle-wn39mnm.pages.github.io/reference/capabilities/).

## Establish the contract

Infer dataset meaning, time grain, identity dimensions, output columns, upstream
choices, first-run/backfill bounds, and whether identity must be preserved from
the task and existing code. Clarify only unresolved choices that change the
published contract. Keep storage description, namespace, identifier, cadence,
columns, and FK/index metadata on the authoring model, not the updater config.
Write table and column descriptions by the rules in the
[table discovery skill](../metatables-table-discovery/SKILL.md); see
`metatables/examples/tables.py`.

Migrate and bind the output class before constructing the producer. Pass explicit
`config` and `output_table`; do not create/register tables inside `update()`.
The optional `hash_namespace` separates producer identities, **not output tables**.
A test namespace alone does not protect shared physical rows. Use a disposable
output binding or explicitly authorized row scope for mutation tests.

A deployed producer runs as its Job's workload User. It needs `editor` on its output
tables, which lets it operate updaters and write rows, and `data_viewer` on its
inputs. When the producer is deployed from the same repository branch as the
migration Job, it gets these through the branch: the provider's `branch_access`
declares `editor` on the output namespace (step 4 of the
[migrations skill](../metatables-migrations/SKILL.md)), and the producer holds it on
its first run, in every Environment and after any rename. It does not wait for a
grant. Inputs in another repository's namespace need one grant from that namespace's
owner to this branch, per Environment (step 5). Output tables belong to the migration
provider and are in the namespaces their models declare: a workload never creates a
table outside a namespace.

## Configuration and dependencies

Use `TimeIndexTableUpdateConfig` with described `Field` values and realistic
examples where useful. Fields affect `update_hash` by default. Values that change
output, source selection, dependencies, or producer scope must stay hashed.
Keep implementation constants in `ClassVar` or runtime configuration. For a
strictly descriptive Pydantic field, the supported exclusion is
`json_schema_extra={"hash_excluded": True}`; do not invent alternate markers.

The client owns configuration version 2 serialization/validation. A configured
upstream authoring class hashes by its bound table UID and must already be bound.
`output_table` is a constructor contract, not an ordinary config field. Removed
configuration forms and `test_node` are unsupported; use explicit namespaces.

Positional and keyword construction give the same `update_hash` since client 0.1.74.
When upgrading past it, a positionally constructed producer can start a new update
record, once, if an intermediate updater class (even one without its own `__init__`)
names or orders the parameters differently, or if a constructor passes `*args`
through. Compare that producer's hash before and after upgrading; do not add a
compatibility hash.

Declare a deterministic `dependencies()` mapping. Executable dependencies are
other updater instances; read-only dependencies are `TimeIndexTableRef` objects.
References contribute lineage and reads without executing a producer. Do not
construct a changing dependency graph inside `update()`.

## Running several producers together

`updater.run()` runs one producer after its dependencies. When a Job runs several
producers that share dependencies, do not call `run()` on each in turn: every call
runs the shared dependencies again. Pass them together:

```python
from metatables import UpdatersFailedError, run_updaters

try:
    outcomes = run_updaters([producer_a, producer_b, producer_c])
except UpdatersFailedError as failure:
    for outcome in failure.outcomes:
        print(outcome.updater.update_hash, outcome.state, outcome.error)
    raise
```

- Their dependency graphs are joined into one run, so a shared dependency runs once.
- A producer that is passed and is also another's dependency runs once, in order.
- A failure stops only the producers that need the failed node; the others finish.
- `run_updaters` raises `UpdatersFailedError` after everything that could run has
  run. Let it fail the Job, and read `outcomes` for each producer's `state`:
  `succeeded`, `failed`, `blocked`, `skipped` or `not_run`.
- One run holds at most 500 graph nodes, counting producers and tables. Split a
  larger set into several calls.

## Running a graph in parallel Job runs

On a hosted runtime, `run(node_job="...")` and `run_updaters([...], node_job="...")`
execute every producer in its own run of one Main Sequence Job, the repository's
**node Job**. Independent producers run at the same time, each in its own container.
Read [Run a graph in parallel](https://potential-doodle-wn39mnm.pages.github.io/client/run-updaters-in-parallel/)
and the tested scripts `metatables/examples/tutorial/jobs/run_updater_node.py` and
`metatables/examples/tutorial/jobs/update_together.py`.

A run is whole: with `node_job` every producer runs in a Job run, without it every
producer runs in the calling process. There is no setting that keeps one producer in
the calling process.

**A project that runs producers** declares two Jobs in its workflow file:

```yaml
resources:
  - key: updater-node              # the node Job: one run executes one producer
    kind: job
    spec:
      name: Updater node
      execution_path: jobs/run_updater_node.py
      cpu_request: "1"             # the size of every producer that declares none
      memory_request: "2"
      max_runtime_seconds: 3600    # one limit for every producer
      automatic_redeployment:
        enabled: true
        tag_regex: null

  - key: update-market             # the orchestrator: the Job that calls run()
    kind: job
    spec:
      name: Market update
      execution_path: jobs/update_market.py
      cpu_request: "1"
      memory_request: "2"
      max_runtime_seconds: 7200
      automatic_redeployment:
        enabled: true
        tag_regex: null
    access:
      resources:
        - key: updater-node
          policy: sized_runner     # runner is enough when no producer declares a size
```

```python
# jobs/run_updater_node.py: the same two lines in every repository
from metatables import run_updater_node

if __name__ == "__main__":
    run_updater_node()
```

- Declare one node Job per repository. Do not declare a Job per producer or per size.
- `node_job` is the node Job's `spec.name`. It is found on the branch the process runs
  on, so every branch uses its own node Job on its own image.
- The node Job and the orchestrator are separate resources: a workflow resource cannot
  declare access to itself.
- `max_parallel_nodes` is the most node Job runs at one time. The default, `-1`, is no
  limit.
- A Job-mode call returns no frame: `run()` returns `(False, None)`. Read the table.
- `node_job` is refused on a local runtime. Develop and test in-process, without it.

**A library whose producers other projects run** declares no Job. Its producers must
rebuild in another process from their saved configuration:

- Declare the producer and its table class with a `class` statement at the top level of
  an importable module. A table class that a function returns has no import address and
  is refused, also when it is held in a config or is the table of a producer passed as
  an argument. A library that offers one table per configuration has its users declare
  each table as a class.
- Keep typed values (dates, times, Enums) inside the pydantic config. As separate
  constructor arguments they are saved as text and the run is refused before it starts.
- Read another producer's result only from its table. A Job run shares no memory with
  any other: no module-level cache, no attribute set after construction.
- Do not combine `override_update_stats` with `node_job`.

A producer that needs more than the node Job declares says so in code, outside the
configuration hash:

```python
from metatables import NodeResources


class RiskModel(TimeIndexTableUpdater):
    def node_resources(self) -> NodeResources:
        return NodeResources(cpu_request="16", memory_request="64")
```

- `cpu_request` is vCPU from 0.25 to 30; `memory_request` is GiB from 0.5 to 110 and
  from 1 to 6.5 times the CPU. Use plain decimal numbers, not `500m` or `1Gi`.
- A field left out takes the node Job's value. On a node Job of 1 vCPU, memory alone
  can go only to 6.5 GiB, so a larger producer names both.
- The platform checks the size when that producer's Job run is started. A refused size
  fails that producer; it is not found before the run.
- A sized run needs `policy: sized_runner` on the node Job. With `runner` the error
  names the policy to declare.

When a Job-mode run is refused, the error names what to fix: the producer and the
argument that does not rebuild, the missing or duplicate node Job, the image that is not
ready, the local runtime, or the missing `sized_runner` policy.

## Incremental output

Use `UpdateStatistics` to determine the next interval, including a first-run
fallback. Statistics describe the whole output table, which other producers may
share: start each stream from its own progress,
`get_last_update_for_identity(key)`, or from the configured start when it has
none. Never use `max_time_index_value` or `get_max_time_in_update_statistics()`
as one stream's start. Return rows matching the bound storage contract and avoid
full-history writes unless the task explicitly needs them.

Every non-empty frame must put `time_index` first and use exactly
`datetime64[ns, UTC]` for that index level. Construct it explicitly with
`pd.DatetimeIndex(..., dtype="datetime64[ns, UTC]")`; timestamp normalization alone
can retain microsecond precision. For a MultiIndex, declare all dimension levels
in storage-grain order and keep payload columns separate.

The time-index mixin creates the unique index for the complete observation grain.
Do not duplicate it manually. Additional indexes and foreign keys belong in
SQLAlchemy/Alembic metadata and should use application-prefixed physical names.
Changing a table contract requires a new migration, not an updater config field.

## Tail repair

Use the documented `TimeIndexMetaTable.delete_after_date` workflow for updater
output rollback. The cutoff is inclusive. Supply `dimension_filters` to select
value sets or `index_coordinates` to select exact streams. A null cutoff requires
one of those scopes and deletes all rows only in that scope. An unscoped null
cutoff must fail. Do not replace this workflow with direct connections, SQL,
truncation, or private endpoints.

The API route is `/time-index-meta-tables/{uid}/delete-after-date/`; deployment
prefixes belong in `METATABLES_API_URL`. See [Query and mutate](https://potential-doodle-wn39mnm.pages.github.io/client/query-and-mutate/).

## Review and verification

Check hashing effects, deterministic dependencies, incremental bounds, configured
output identity, time dtype, dimension order, columns, and tail-delete scope.
Use the relevant updater tests and executable example tests. Report what was
actually exercised: pure frame logic, disposable storage, or a configured API.
Do not claim a scheduling/release workflow from producer tests. If a published
contract decision remains unknown, resolve that decision while continuing any
independent authorized work.

To find what started a run, read its `trace_id`, the platform trace of the request, Job
run or Agent turn that started it. Its `execution_uid` is the runner's id, shared by
every node of one execution, and a node Job run receives it as `--execution-uid`.
`GET /table-update-runs/?trace_id=...` lists the runs of one trace. See
[The trace that started a run](https://potential-doodle-wn39mnm.pages.github.io/operations/run-history/#the-trace-that-started-a-run).

## Bounded transfers and recovery

Read [Bounded reads, uploads, and recovery](https://potential-doodle-wn39mnm.pages.github.io/client/bounded-transfers/) for transfer contract v1. Prefer
`MetaTable.iter_rows()` for structured relation batches and
`TimeIndexTableRef.iter_batches()` for typed time-index frames. Existing complete
DataFrame readers have row, serialized-byte, and elapsed-time budgets; increase
client collection budgets deliberately or narrow the selection. Offset pages do
not provide a snapshot, and iterators do not prefetch.

Uploads remain sequential, with at most 10,000 rows and byte checks per chunk.
Each chunk commits independently. Preserve an explicit operation UUID and input
for restart recovery. On an uncertain outcome, inspect `upload_receipt()` before
resubmitting; do not assign a fresh key to bypass uncertainty. Administrator
reconciliation requires verified physical evidence. This workflow uses the Main
Sequence API and has no Artifact or temporary-URL dependency.

A 429 `transfer_capacity_exceeded` or 503 `database_connections_busy` means the
API was at capacity and nothing ran. Retry after `Retry-After`, an upload with the
same operation UUID; it is not an uncertain outcome.
