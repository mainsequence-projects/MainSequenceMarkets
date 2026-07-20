# Formula And Custom Indexes

This tutorial creates a custom Index, discovers formula source tables, defines
a mixed Asset/Index formula, previews it, and prepares deterministic
publication.

## 1. Start The Runtime

The MetaTable migration must be current before row operations.

```python
import msm

msm.start_engine(
    models=[
        "Asset",
        "IndexType",
        "Index",
        "IndexDatasetAvailability",
        "IndexFormulaDefinition",
        "IndexFormulaInput",
    ]
)
```

## 2. Register A Custom Source Index

Custom means code supplies the observations.

```python
from msm.api import Index

tiie = Index.upsert(
    unique_identifier="MXN-TIIE-28D",
    index_type="interest_rate",
    display_name="MXN TIIE 28D",
    calculation_method="custom",
    value_format="percent",
)
```

Publish its values with a cadence-specific `IndexValuesDataNode`. Custom rows
contain no `definition_uid`.

## 3. Resolve The Asset

The mixed formula also uses a bond Asset already registered as
`MX-GOVT-5Y`:

```python
from msm.api import Asset

bond = Asset.get_by_unique_identifier("MX-GOVT-5Y")
if bond is None:
    raise LookupError("MX-GOVT-5Y is not registered")
```

## 4. Discover Source MetaTables

Use the same method for both source types:

```python
index_tables = Index.list_related_meta_tables(
    tiie.uid,
    numeric=True,
    timestamped=True,
)
asset_tables = Asset.list_related_meta_tables(
    bond.uid,
    numeric=True,
    timestamped=True,
)

for table in (*index_tables, *asset_tables):
    print(table.meta_table_uid, table.identifier)
```

The resolver returns tables with authoritative FKs. It does not choose an
observable or claim that the selected identity has rows. Inspect the chosen
MetaTable contract and select its numeric column.

For this tutorial, assume:

```python
RATE_VALUES_UID = "11111111-1111-1111-1111-111111111111"
BOND_VALUES_UID = "22222222-2222-2222-2222-222222222222"
```

## 5. Define Exact Inputs

```python
from msm.api import IndexFormulaInput

rate_input = IndexFormulaInput(
    source_reference={"type": "index", "identifier": tiie.unique_identifier},
    meta_table_uid=RATE_VALUES_UID,
    observable="price",
)
bond_input = IndexFormulaInput(
    source_reference={"type": "asset", "identifier": bond.unique_identifier},
    meta_table_uid=BOND_VALUES_UID,
    observable="yield",
)
inputs = (rate_input, bond_input)
```

The identity column is implied by source type. There are no resolver fields or
input aliases.

## 6. Register The Formula

```python
import datetime

from msm.api import FormulaIndex, IndexFormulaDefinition

definition = IndexFormulaDefinition(
    status="active",
    valid_from=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    formula=(
        'index["MXN-TIIE-28D"].price * 5 '
        '+ asset["MX-GOVT-5Y"].yield'
    ),
    alignment_policy="exact",
    missing_data_policy="fail",
)

mixed = FormulaIndex.upsert(
    unique_identifier="MXN-RATE-BOND-MIX",
    index_type="interest_rate",
    display_name="MXN Rate And Bond Mix",
    definition=definition,
    inputs=inputs,
    value_format="percent",
)
```

Registration fails when a reference is missing from `inputs`, an input is
unused, a table UID is unavailable, the observable is not numeric, the table
has extra identity dimensions, or an Index dependency cycle would result.

Formula versioning is monotonic. Repeating the same semantic payload returns
the existing version.

## 7. Preview With Local Series

```python
import pandas as pd

from msm.api import IndexFormula

formula = IndexFormula.from_definition(definition, inputs)
times = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
result = formula.evaluate_historical(
    {
        rate_input.reference: pd.Series([0.1050, 0.1060], index=times),
        bond_input.reference: pd.Series([0.0920, 0.0910], index=times),
    }
)
print(result.values)
```

`IndexFormula` is an immutable Pydantic model. It validates the grammar,
reference/input equality, and policies before evaluation. Its result is
indexed by UTC `time_index` and contains numeric `value` and `source_as_of`;
it needs no persisted UID. `mixed.calculate(...)` remains available when a
canonical preview with target `index_identifier` and `definition_uid` is
required.

For a permission-checked bounded platform preview:

```python
result = mixed.calculate_from_sources(
    start="2026-01-01T00:00:00Z",
    end="2026-02-01T00:00:00Z",
)
```

## 8. Publish Through A DataNode

Use the actual registered source storage classes whose MetaTable UIDs match
the two input UIDs:

```python
from msm.data_nodes.indices import (
    FormulaIndexDataNode,
    FormulaIndexDataNodeConfiguration,
    configured_index_values_storage,
)

DailyIndexValues = configured_index_values_storage(cadence="1d")
config = FormulaIndexDataNodeConfiguration(
    formula_definition_uids=(mixed.definition.uid,),
    source_storage_tables=(RateValuesStorage, BondValuesStorage),
    offset_start="2026-01-01T00:00:00Z",
)
node = FormulaIndexDataNode(config, DailyIndexValues)
```

Construction verifies exact source UID coverage, source grain, observable
types, and unique dependencies. Dependencies are built before `update()`.

## 9. Create A Successor

Create a draft with a later `valid_from`, then activate it:

```python
successor = FormulaIndex.upsert(
    unique_identifier=mixed.index.unique_identifier,
    index_type=mixed.index.index_type,
    display_name=mixed.index.display_name,
    definition=IndexFormulaDefinition(
        valid_from=datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC),
        formula=(
            'index["MXN-TIIE-28D"].price * 4 '
            '+ asset["MX-GOVT-5Y"].yield'
        ),
    ),
    inputs=inputs,
    value_format=mixed.index.value_format,
)
successor = successor.activate()
```

Activation closes the predecessor at `2027-01-01T00:00:00Z`. Historical
backfills select the version whose half-open validity interval contains the
observation timestamp.

## 10. Keep Stateful Performance In Portfolio

A self-financing benchmark is not a formula:

```text
Portfolio holdings and cash
        -> Portfolio NAV/performance calculation
        -> custom Index value publication
```

The executable example `examples/msm/indices/delta_hedged_option_index.py`
demonstrates this boundary. The mixed arithmetic example is
`examples/msm/indices/formula_index.py`.

## Next Steps

- [Formula and custom Index workflow](../knowledge/msm/indices/formula_indexes.md)
- [Index API](../knowledge/msm/indices/index.md)
- [Index FastAPI](../fast_api/v1/indexes.md)
