# Formula And Custom Indexes

An Index is calculated in exactly one of two ways:

- `formula`: a versioned point-in-time expression is owned by ms-markets;
- `custom`: application code calculates and publishes values.

These are calculation methods, not Index types. An interest-rate Index can use
either method.

## Formula Shape

Formula references use canonical identifiers directly:

```text
index["MXN-TIIE-28D"].price * 5 + asset["MX-GOVT-5Y"].yield
```

Each reference has one exact source binding:

```python
from msm.api import IndexFormulaInput

rate = IndexFormulaInput(
    source_reference={"type": "index", "identifier": "MXN-TIIE-28D"},
    meta_table_uid="11111111-1111-1111-1111-111111111111",
    observable="price",
)
bond = IndexFormulaInput(
    source_reference={"type": "asset", "identifier": "MX-GOVT-5Y"},
    meta_table_uid="22222222-2222-2222-2222-222222222222",
    observable="yield",
)
```

There is no input key. The formula itself uses the unique Asset or Index
identifier. `meta_table_uid` selects the exact registered source table and
`observable` selects its numeric column.

The formula parser supports numeric constants, parentheses, `+`, `-`, `*`,
`/`, `**`, and unary signs. It does not execute Python or support calls,
rolling calculations, selectors, or custom callbacks.

## Evaluate Historical Series

`IndexFormula` is the self-contained Pydantic contract for pure historical
evaluation. It owns the expression, exact inputs, alignment policy, and
missing-data policy; it requires no persisted Index or formula-definition UID.

```python
from msm.api import IndexFormula

formula = IndexFormula(
    formula=(
        'index["MXN-TIIE-28D"].price * 5 '
        '+ asset["MX-GOVT-5Y"].yield'
    ),
    inputs=(rate, bond),
    alignment_policy="exact",
    missing_data_policy="fail",
)

history = formula.evaluate_historical(
    {
        rate.reference: rate_series,
        bond.reference: bond_yield_series,
    }
).values
```

The result is indexed by UTC `time_index` and contains `value` plus
`source_as_of`. Input observations may be pandas Series or DataFrames keyed by
`FormulaReference` or its expression string. This path performs no platform
read and does not invent publication provenance.

## Find Source Tables

Asset and Index expose the same discovery method:

```python
from msm.api import Asset, Index

asset_tables = Asset.list_related_meta_tables(
    asset_uid,
    numeric=True,
    timestamped=True,
)
index_tables = Index.list_related_meta_tables(
    index_uid,
    numeric=True,
    timestamped=True,
)
```

The default result contains registered time-indexed tables with at least one
numeric non-identity column and an authoritative FK to the corresponding
`unique_identifier`. Set either filter to false to disable it. Discovery does
not assert that the selected identity has rows in a table; authoring still
selects and validates the exact observable.

## Register A Formula

```python
import datetime

from msm.api import FormulaIndex, IndexFormulaDefinition, IndexFormulaInput

definition = IndexFormulaDefinition(
    valid_from=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    formula=(
        'index["MXN-TIIE-28D"].price * 5 '
        '+ asset["MX-GOVT-5Y"].yield'
    ),
    alignment_policy="exact",
    missing_data_policy="fail",
    status="active",
)

formula_index = FormulaIndex.upsert(
    unique_identifier="MXN-RATE-BOND-MIX",
    index_type="interest_rate",
    display_name="MXN Rate And Bond Mix",
    definition=definition,
    inputs=(rate, bond),
    value_format="percent",
)
```

`FormulaIndex.upsert` does not accept a `calculation_method` argument because
it always creates or updates a formula Index.

The formula reference set must exactly equal the input set. Registration
validates source identity, MetaTable visibility, authoritative FK, exact grain,
numeric observable, formula cycles, and monotonic versioning.

Repeated registration of the same semantic definition is idempotent. Changing
the expression, validity start, policy, source identity, MetaTable UID, or
observable creates a different semantic hash and therefore a new version.

## Lifecycle

Definitions use `draft`, `active`, and `retired` status. `valid_from` is the
inclusive first calculation timestamp and `valid_to` is exclusive.

```python
draft = FormulaIndex.upsert(..., definition=draft_definition, inputs=inputs)
active = draft.activate()
retired = active.retire(valid_to="2027-01-01T00:00:00Z")
history = FormulaIndex.history(active.index.uid)
```

Activating a successor closes the open predecessor at the successor's
`valid_from`. Retired versions cannot be reactivated.

## Preview Persisted Formulas

`FormulaIndex.calculate(...)` evaluates the persisted version and adds the
target Index identity and exact `definition_uid` required by canonical
publication:

```python
result = formula_index.calculate(
    {
        rate.reference: rate_series,
        bond.reference: bond_yield_series,
    }
)
```

Bounded platform preview reads the pinned MetaTables:

```python
result = formula_index.calculate_from_sources(
    start="2026-01-01T00:00:00Z",
    end="2026-02-01T00:00:00Z",
)
```

`exact` uses shared timestamps. `asof` is backward-only and requires
`max_staleness_seconds`. Missing data is either dropped or fails according to
the definition.

## Publish Formula Values

Production publication pins immutable formula versions and the exact
registered storage classes for every source MetaTable:

```python
from msm.data_nodes.indices import (
    FormulaIndexDataNode,
    FormulaIndexDataNodeConfiguration,
    configured_index_values_storage,
)

config = FormulaIndexDataNodeConfiguration(
    formula_definition_uids=(formula_index.definition.uid,),
    source_storage_tables=(RateValuesStorage, BondValuesStorage),
    offset_start="2026-01-01T00:00:00Z",
)
node = FormulaIndexDataNode(
    config,
    configured_index_values_storage(cadence="1d"),
)
```

Construction fails unless the registered storage UIDs exactly match the
formula inputs. Dependencies are fixed before `update()` and source reads are
bounded by identity, time, and observable columns.

Formula observations carry `definition_uid`. The stored value is not scaled by
`value_format`.

## Publish Custom Values

Custom code registers the identity and publishes directly:

```python
from msm.api import Index

index = Index.upsert(
    unique_identifier="MY-CUSTOM-BENCHMARK",
    index_type="portfolio_benchmark",
    display_name="My Custom Benchmark",
    calculation_method="custom",
    value_format="decimal",
    value_suffix=" USD",
)
```

Use `IndexValuesDataNode` or `normalize_index_values_frame` for the canonical
cadence storage. Custom rows must not supply `definition_uid`.

Self-financing calculations belong to Portfolio. Publish the Portfolio NAV or
performance into a custom Index only when a reusable observable identity is
needed.

## Display Formatting

`value_format="decimal"` displays the stored value as-is.
`value_format="percent"` displays a decimal ratio as a percentage.
`value_suffix` appends arbitrary display text. These fields do not perform
economic unit conversion.

## Further Reading

- [Index overview](index.md)
- [Formula and custom Index tutorial](../../../tutorial/06-index-formulas.md)
- [ADR 0037](../../../ADR/0037-index-formula-and-custom-calculation-framework.md)
