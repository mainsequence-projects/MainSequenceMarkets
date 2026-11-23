# Build an updater

An updater writes incremental rows into an existing `PlatformTimeIndexMetaTable`.
First migrate the storage model and its dependencies. For the ledger example,
create the account row before inserting balance observations because the physical
foreign key still applies.

[The updater example](../examples/updater.py) contains `BalanceConfig`,
`BalanceUpdater`, and a deterministic sample-data function. It uses three fixed
observations so its shape and incremental behavior can be tested offline.
Replace that data source with your actual ingestion logic.

`BalanceConfig.account_uid` selects the producer partition; `start` controls its
first backfill. Both affect update identity. Descriptions belong on every config
field. The output table class is supplied to the updater, not embedded as an
ad hoc storage definition inside `update()`.

```python
from datetime import datetime, timezone
from uuid import UUID
from metatables.examples.updater import BalanceConfig, run

run(BalanceConfig(
    account_uid=UUID("your-existing-account-uuid"),
    start=datetime(2026, 1, 1, tzinfo=timezone.utc),
))
```

Use a real UUID in the example. Construction registers/resolves the producer and
requires the table's catalog binding and effective API context. Running can execute
dependencies, upload chunks, and update run history; it is not a pure constructor
or DataFrame transformation.

The example returns only observations later than its own account's last stored
row, `update_statistics.get_last_update_for_identity(account_uid)`. Update
statistics describe the whole output table, which other producers share:
`max_time_index_value` and `get_max_time_in_update_statistics()` are the newest
row of any of them, so never start one stream there. A producer of several
streams starts at the earliest of their own progress, as the tutorial's
`own_progress` does; the runner drops the rows each stream already has.
Non-empty DataFrames must have the declared index names,
`datetime64[ns, UTC]` as the first index level, and matching value-column types.

Return executable producers and read-only `TimeIndexTableRef` dependencies
explicitly from `dependencies()`. Keep the graph deterministic. Changes to input
selection belong in hashed configuration. A hash namespace changes producer
identity but leaves the output table unchanged; use a separate migrated table
when test data must be physically isolated.

The update lifecycle records execution state and run history, checks current
output edit grants, validates bounded upload chunks, and refreshes statistics.
Each invocation also saves its dependency graph, links dependency attempts to the
existing root run, and reports node progress through the API. Open **Runs** in
Admin or call `TableUpdateRun.get_graph()` to inspect that invocation and its
exact logs. Scheduling remains with Main Sequence Jobs. See
[Runs and execution graphs](../concepts/runs-and-execution-graphs.md) for the
concepts and [Run history and graphs](../operations/run-history.md) for API examples.
For rollback or repair of output tails, use the scoped deletion interface described
in [query and mutate](query-and-mutate.md).

## Upload completion and recovery

Output persistence uses sequential chunks capped by rows and bytes. Chunks commit independently. Retain an `operation_id` when calling `TimeIndexTableUpdate.post_data_frame_in_chunks()` for restart recovery; generic updater runs do not automatically resume an uncertain chunk. Errors retain recovery references. Follow [upload receipts and recovery](bounded-transfers.md#upload-and-recover) before resubmitting.
