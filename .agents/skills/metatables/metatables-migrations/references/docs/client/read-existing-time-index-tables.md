# Read existing time-index tables

Use `TimeIndexTableRef` when you need an existing dataset without constructing or
running its producer. It resolves a visible `TimeIndexMetaTable` and exposes a
reader. The reference can be created from a UID, logical identifier, physical
identity, existing MetaTable object, or update resource.

[The reader example](../examples/reader.py) reads one account's observations:

```python
from datetime import datetime, timezone
from examples.reader import balances

frame = balances(
    "balance-table-uuid", "account-uuid",
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    datetime(2026, 2, 1, tzinfo=timezone.utc),
)
```

Use the current API connection and effective API scope. The same resource
visibility rules apply regardless of the lookup method. Physical-identity lookup
must resolve an exact schema/table and, when specified, DataSource UID.

`get_df_between_dates(...)` accepts start/end bounds, inclusivity switches,
selected columns, dimension filters, exact coordinate lists, and range maps.
`get_last_observation(...)` retrieves the latest observation per selected scope.
Results are reconstructed into a DataFrame with the table's declared ordered
index and dtypes.

A table reference used as an updater dependency contributes lineage and read
access only. It does not become an executable upstream producer.

## Incremental readers

Use `TimeIndexTableRef.iter_batches()` for typed UTC/indexed pages with no prefetch. Existing DataFrame helpers return all selected rows within their collection budget or raise; they never silently return a partial frame. See [bounded transfers](bounded-transfers.md) and the [executable batch reader](../examples/bounded_reader.py).
