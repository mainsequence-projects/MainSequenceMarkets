# Time-index data and update operations

Time-index reads resolve a visible active table, authorize storage access, and
apply the declared time and coordinate filters. The full observation grain has
time first. Exact coordinate lists and dimension filters have different meanings;
validate that filters use declared dimensions and typed values.

Supported actions include date-range reads, last observations, statistics, and
scoped tail deletion. Both direct table reads and reads through an update node
resolve the output table's grants. Client DataFrame reconstruction uses the table's
index and column dtype contract.

Update registration binds a configured producer hash to an output table. It is
idempotent for that identity and checks output edit permission. Dependency actions
connect producers or read-only table references. Dependency graph/priority reads
filter hidden nodes and re-check current access.

The table detail **Updates** tab reads the collection endpoint with an exact
output-table filter:
`GET /time-index-table-updates/?output_table__uid={table_uid}&limit=25&offset=0`.
The API also exposes table-scoped reads at
`GET /meta-tables/{table_uid}/updates?limit=25&offset=0` and
`/time-index-meta-tables/{table_uid}/updates`. These scoped routes
accept a trailing slash without redirecting. A Reader on the output table can
list its producers; Writer access is unnecessary for this read. Each result uses
the same update projection as `/time-index-table-updates/`, including the nested
output table, execution details, configuration, source-code reference and labels.
The page includes `count`, `results`, `next`, and `previous`, with deterministic
ordering and bounds of 1–500 for `limit` and a nonnegative `offset`.

A visible time-index table with no producers returns an empty page. On the
table-scoped routes, missing,
hidden or relational tables return 404. Counts and rows belong only to the table
named in the path, and current grants are checked on every request. This listing
reads the catalog; it does not run a producer or schedule an update.

The table **Updates** pipeline and update **Graphs** view both use
`GET /meta-tables/{table_uid}/update-graph/`, with
`direction=upstream|downstream|both` (default `both`). For an update, resolve
`table_uid` from its detail response's `output_table.uid` and pass
`update_uid={update_uid}` to root traversal at that update. It must produce the
table in the path. Without `update_uid`, traversal starts at the table.
The response contains `root_id`, `nodes`, and `edges` for registered reads,
writes, and update dependencies. Upstream walks incoming links, downstream walks
outgoing links, and both performs these walks separately; sibling producers do
not become dependencies of the selected update. Table downstream traversal also
starts from its producers that have direct update consumers, retaining those
producers as connecting context without walking their upstream inputs.
Outputs of reachable producers
remain inspectable, except the current update's output in an upstream-only view.
Current grants filter nodes and traversal. Missing or hidden roots and an update
outside the path's table return 404; invalid directions return 422; a graph
exceeding the node or edge limit returns 409. This endpoint reads catalog metadata
without executing an update.

Execution actions start/end runs, patch details, record update statistics, and
handle batch state transitions. The current active run protects execution updates
against stale or mismatched run identities. Batch operations apply their own
atomicity and validation rules; do not infer them from individual PATCH behavior.

Chunk ingestion checks output edit rights, payload bounds, DataFrame/index types,
and storage access mode before writing. Statistics are refreshed from accepted data
or physical state rather than trusting arbitrary caller-supplied progress.

Tail deletion uses an inclusive time cutoff with optional dimension or exact
coordinate scope. A missing cutoff requires explicit coordinate scope. It updates
statistics after physical execution. No completely unbounded delete is accepted
through this action.

Table search and column search work over visible catalog metadata; see
[table search](tables-and-migrations.md#table-search). See the generated
[HTTP reference](reference.md) and [capabilities](../reference/capabilities.md) for
exact paths and evidence classifications.

## TimescaleDB policies

On a `timescale_db` DataSource, each time-index table becomes a hypertable on its
time index when it is finalized or created, unless its storage layout sets
`partitioning.strategy` to `none`. Such tables report
`capabilities.timescale_policies: true`. TimescaleDB 2.11 or later is required.

TimescaleDB stores the policies as background jobs; MetaTables keeps no copy.
`GET /meta-tables/{table_uid}/timescale-policies/` (Reader) returns
`eligibility`, both policies, the derived compression settings (segment by the
identity dimensions, order by time descending), compression stats and the table's
jobs. `PUT` on the same path (Writer, read-write DataSource) replaces both
policies:

```json
{
  "compression": {"after": "7 days"},
  "retention": {"after": "365 days", "schedule_interval": "1 day"}
}
```

`after: null` removes a policy; removing compression keeps compressed chunks.
Retention must be longer than compression and permanently drops older chunks on
every run, including later backfills. Each change is journaled with the caller.
Errors are `404 timescale_policies_unavailable` for other engines,
`409 timescale_not_hypertable`, `409 timescale_version_unsupported`,
`409 timescale_extension_missing` and `422` for an invalid interval, timezone or
`timescale_retention_not_after_compression`.

`GET /data-sources/{uid}/timescale-jobs/` lists the source's jobs with their
status, last and next run, failures and last error. Admins see every job; other
Users see jobs of tables they can read. The Python client exposes
`TimeIndexMetaTable.get_timescale_policies()` and `set_timescale_policies()`.
To keep policies in code, run a Job at bootstrap that calls the client.

## Run logs

The Admin **Runs** menu reads all recorded attempts through
`GET /table-update-runs/`. Its optional **Root invocations** filter sends
`root_only=true`. Select a root or dependency run with
`GET /table-update-runs/{run_uid}/graph/` to inspect its saved topology and node
states. This graph uses that invocation's attempt records, not mutable updater
details. Each attempted updater node carries `attempt_started_at` and
`attempt_ended_at` from its run record around the `started_at`/`ended_at`
calculation window; unattempted nodes have none. Current access filters every
graph and log read. See
[Run history and graphs](../operations/run-history.md) for admission, progress,
filters, limits and unfinished/older-history behavior.

`GET /table-update-runs/{run_uid}/logs/` reads one run;
`GET /table-update-runs/{run_uid}/invocation-logs/` merges every attempt of that
run's invocation into one time-ordered page, skipping attempts whose output table
the caller cannot read; a run without a saved graph is its own invocation.
`GET /time-index-table-updates/{update_uid}/logs/` reads a bounded set of recent
runs for that updater. All three require Reader access to the selected output
table and return the same structured rows, cursor and availability contract.
Optional `run_uid` selects one run on the update route and one attempt of the
invocation on the invocation route. No route accepts filesystem paths or
platform workload overrides. See [Run logs](../operations/run-logs.md) for the
complete query and retention contract.

Run creation now returns `log_capture`, the API-selected capture descriptor.
The client runner supplies the already available platform JobRun reference when
present, emits correlated records, and reports capture availability when finishing
the run. This does not change run success/failure semantics. Existing runs without
capture metadata remain readable as history and report logs as unavailable.

## Bounded transfer contract

`GET /runtime-context/?transfer_contract=1` publishes effective limits. Upload bodies optionally carry UUID `operation_id` and `chunk_key`, plus explicit `retry_failed`. Receipt status is `GET /time-index-table-updates/{update_uid}/upload-receipts/{chunk_key}/`; admin reconciliation is POST to the same path plus `reconcile/`, with `outcome` and an evidence description. [The transfer guide](../client/bounded-transfers.md) specifies authorization, retention, independent chunk commits, and mixed-version behavior.
