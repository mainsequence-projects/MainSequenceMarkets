# Indexes

An Index is a canonical observable identity, not necessarily a tradable Asset.
Examples include a published market benchmark, an interest-rate fixing, a
swap-quote series, a formula spread, or a Portfolio benchmark.

A tradable future on an Index is an Asset whose future details reference the
Index. Do not create a fake Asset merely to store Index observations.

## Identity And Calculation

`IndexTable` separates three concerns:

- `index_type`: business classification such as `interest_rate`;
- `calculation_method`: exactly `formula` or `custom`;
- `value_format` and optional `value_suffix`: display only.

`formula` means ms-markets owns a versioned point-in-time expression. `custom`
means project or extension code publishes the values. Both can use the same
Index type.

```python
from msm.api import Index

swap_rate = Index.upsert(
    unique_identifier="USD-SWAP-10Y",
    index_type="interest_rate",
    display_name="USD 10Y Swap Rate",
    calculation_method="custom",
    value_format="percent",
)
```

`value_format` does not change the stored value. A percent Index still stores
a decimal ratio. `value_suffix` is arbitrary display text such as `" bp"` or
`" USD"`.

The calculation method cannot change once the Index owns formulas or populated
canonical observations.

## Typed API

The public identity and exploration methods include:

```text
Index.create / Index.upsert / Index.update / Index.delete
Index.get_by_uid / Index.get_by_unique_identifier / Index.filter_by_uids
Index.list_page / Index.get_detail / Index.get_summary
Index.list_formulas / Index.get_formula
Index.list_datasets / Index.get_dataset_summary / Index.get_values
Index.list_related_meta_tables
Index.reconcile_dataset_availability
```

Pure historical evaluation uses the self-contained Pydantic contract:

```text
IndexFormula.evaluate_historical
```

Persisted formula authoring uses `FormulaIndex`, not `Index`:

```text
FormulaIndex.upsert
FormulaIndex.get_by_identifier / get_by_index_uid / get_by_definition_uid
FormulaIndex.history
FormulaIndex.calculate / calculate_from_sources
FormulaIndex.activate / retire
```

There are no aliases for removed calculation-definition or leg APIs.

## Formula Sources

Formula inputs may mix Assets and Indexes:

```text
index["MXN-TIIE-28D"].price * 5 + asset["MX-GOVT-5Y"].yield
```

Every reference pins one exact source MetaTable UID and numeric observable.
Asset and Index source discovery use the same method and filters:

```python
Asset.list_related_meta_tables(asset_uid, numeric=True, timestamped=True)
Index.list_related_meta_tables(index_uid, numeric=True, timestamped=True)
```

Only authoritative FKs to the corresponding `unique_identifier` establish the
relationship. Matching `asset_identifier` or `index_identifier` text is not
enough. Discovery inspects schema only and does not claim that a specific
identity has data in a table.

See [Formula And Custom Indexes](formula_indexes.md) for the full workflow.

## Canonical Values

Stable-frequency publication uses
`configured_index_values_storage(cadence=...)`. Each cadence has a separate
MetaTable and physical table with grain:

```text
(time_index, index_identifier)
```

Canonical columns are:

| Field | Contract |
| --- | --- |
| `time_index` | UTC observation timestamp. |
| `index_identifier` | FK to `IndexTable.unique_identifier`. |
| `value` | Stored numeric observation. |
| `definition_uid` | Formula version, or null for custom publication. |
| `observation_status` | Optional quality/readiness state. |
| `source_as_of` | Optional latest contributing source timestamp. |
| `metadata_json` | Optional bounded provenance. |

There is no observation `unit`. Presentation comes from the Index identity.

One identity can publish at several cadences:

```text
IndexValuesTS.1m -> ms_markets__index_values__t_1m
IndexValuesTS.1d -> ms_markets__index_values__t_1d
```

Frequency is part of dataset identity, not Index identity.

## Custom Publication

Custom producers use `IndexValuesDataNode` or
`normalize_index_values_frame(...)`. Nullable provenance is supplied when
omitted. Custom publication rejects a non-null `definition_uid`.

```python
from msm.data_nodes.indices import (
    configured_index_values_storage,
    normalize_index_values_frame,
)

DailyValues = configured_index_values_storage(cadence="1d")
normalized = normalize_index_values_frame(frame, storage_table=DailyValues)
```

Self-financing and chained performance are custom from the Index perspective.
Portfolio owns holdings and state; a custom Index may publish the resulting NAV
or performance series.

## Formula Publication

`FormulaIndexDataNode` loads immutable formula versions and reads only their
pinned source storage classes. Construction requires the configured storage
UID set to equal the persisted formula-input MetaTable UID set and validates
the source grain and observable types.

Formula results always contain their exact `definition_uid`. Exact or bounded
backward as-of alignment and the definition's missing-data policy determine
which timestamps publish.

## Dataset Availability

Global canonical dataset descriptors answer which cadence contracts exist.
`Index.list_datasets(uid)` answers which are relevant to one Index through
reconciled population state:

- `populated`;
- `compatible_empty`;
- `unavailable`.

The default hides compatible-empty rows and retains unavailable rows. Listing
filters `has_canonical_values` and `cadence` use indexed availability metadata,
not distinct scans of every value table.

Producers reconcile identifiers after successful persistence. Deployment
backfills use the explicit bounded reconciliation API.

## Registration And Migration

Production startup attaches to already-migrated MetaTables. The core runtime
set includes Index type, Index identity, availability, formula definition, and
formula input tables.

```python
import msm

msm.start_engine(
    models=[
        "IndexType",
        "Index",
        "IndexDatasetAvailability",
        "IndexFormulaDefinition",
        "IndexFormulaInput",
    ]
)
```

Revision `0015` is a one-way formula/custom replacement. It refuses to infer
source MetaTable UIDs from old calculation rows. Remediate those rows before
applying it; no runtime compatibility layer exists.

## Related Documentation

- [Formula and custom Index tutorial](../../../tutorial/06-index-formulas.md)
- [Index FastAPI](../../../fast_api/v1/indexes.md)
- [ADR 0037](../../../ADR/0037-index-formula-and-custom-calculation-framework.md)
- [ADR 0038](../../../ADR/0038-index-user-api-and-fastapi-exploration.md)
