# Time-index tables and updates

A time-index table stores observations indexed by time followed by zero or more
identity dimensions. For a balance dataset, the grain might be
`["time_index", "account_uid"]`: each account has a sequence of observations.

The server stores a one-to-one time-index profile sharing the MetaTable UID. The
Python HTTP representation is `TimeIndexMetaTable`; the authoring base is
`PlatformTimeIndexMetaTable`.

## Coordinates, cadence, and layout

The time column leads `index_names`. Cadence describes an expected interval such
as `1m`, `1h`, or `1d`; it does not schedule execution. Storage layout describes
coordinate uniqueness, indexing, and tail-deletion scope. Statistics describe
observed progress globally and by coordinate. These are separate concerns.

A non-empty producer DataFrame has index levels matching the declared grain,
with the first time level exactly `datetime64[ns, UTC]`. Supply typed value
columns matching the contract. Timezone-naive timestamps are not valid UTC
observations. Metadata such as cadence and descriptions belongs to storage,
not producer configuration.

## Producer and output table

A `TimeIndexTableUpdater` is executable Python logic. Its configuration describes
which dataset or partition it produces, its dependencies provide inputs, and
`update()` returns incremental data. The output table must already be migrated
and bound before constructing the updater.

A `TimeIndexTableUpdate` identifies that configured producer in the catalog.
Multiple producers can write to the same output table. Producer hash and output
table UID remain separate identities.

Configuration fields participate in hashing by default. Use `ClassVar` for
non-configuration constants. A field excluded with
`json_schema_extra={"hash_excluded": True}` must not affect output values or
source/dependency selection. An explicit hash namespace isolates an experiment's
producer identity, but does not isolate the physical output table or its rows.

## Dependencies and execution state

Return dependencies deterministically from `dependencies()`. Updater dependencies
can be executed within the invocation; `TimeIndexTableRef` dependencies contribute lineage and
read access without running a producer. Dependency selection that changes output
belongs in hashed configuration.

Update details hold current execution/progress state. Run records capture
individual executions, their status, and associated timing/error information.
Execution operations check the active run identity and current output grants.
Statistics are derived from accepted data and physical state; a client's claimed
statistics do not authorize or prove an upload.

[Runs and execution graphs](runs-and-execution-graphs.md) explains root invocations,
dependency attempts, captured table connections, node outcomes, and exact run logs.
Main Sequence Jobs owns scheduling; MetaTables records each execution separately.

Use the API's scoped `delete_after_date(...)` for rollback of updater output.
A missing cutoff is accepted only with explicit dimension or coordinate scope;
a completely unbounded tail delete is rejected.
