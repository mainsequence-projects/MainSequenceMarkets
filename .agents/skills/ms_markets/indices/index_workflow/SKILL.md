---
name: mainsequence-markets-index-workflow
description: Use when creating, classifying, calculating, publishing, reviewing, migrating, or documenting ms-markets Index data, including custom observations, formula versions, exact Asset/Index source bindings, cadence storage, related MetaTable discovery, and Portfolio boundaries.
---

# MainSequence Markets Index Workflow

## Scope

Use this skill for:

- Index identity and type classification;
- formula versus custom calculation ownership;
- mixed Asset and Index formula inputs;
- formula lifecycle, preview, and publication;
- canonical cadence-specific Index values;
- Asset/Index related-MetaTable source discovery;
- Index catalog, availability, FastAPI, examples, and migrations.

Use the Portfolio skill when holdings, cash, financing, transaction costs,
rebalancing, NAV, or self-financing performance are involved.

## Required Architecture

An Index is a reusable observable, not necessarily a tradable Asset.

`Index.calculation_method` is exactly:

- `formula`: core evaluates a versioned point-in-time expression;
- `custom`: application code publishes values.

`index_type` is independent business classification. Do not force a formula
Index into a special type.

Result presentation is:

- `value_format="decimal"` or `value_format="percent"`;
- optional `value_suffix`.

Formatting never changes stored values or formula calculation. Canonical
observations have no `unit` field.

## Formula Contract

Supported syntax:

```text
index["INDEX-ID"].observable
asset["ASSET-ID"].observable
numeric constants
+ - * / **
unary + and -
parentheses
```

Do not use Python `eval`. Reject calls, arbitrary attributes, variables,
assignments, imports, and comprehensions.

Every parsed reference has exactly one input:

```python
IndexFormulaInput(
    source_reference={"type": "asset", "identifier": "ASSET-ID"},
    meta_table_uid=source_meta_table_uid,
    observable="yield",
)
```

Do not add aliases, keys, resolver wrappers, configurable identity/value
columns, or static dimension filters.

Source type implies identity column:

```text
asset -> asset_identifier
index -> index_identifier
```

Registration must prove:

- visible registered time-indexed MetaTable;
- authoritative FK to the corresponding `unique_identifier`;
- exact grain `(time_index, identity_column)`;
- numeric observable;
- exact formula-reference/input-set equality;
- no component-Index dependency cycle.

MetaTable UID and observable are immutable formula semantics. Runtime code must
not search for fallback tables or columns.

## Formula Lifecycle

Use:

```python
from msm.api import FormulaIndex, IndexFormula, IndexFormulaDefinition, IndexFormulaInput
```

`IndexFormula` is the immutable Pydantic contract for pure historical
evaluation. It owns `formula`, `inputs`, `alignment_policy`,
`alignment_parameters_json`, and `missing_data_policy`. Use
`IndexFormula.evaluate_historical(...)` with caller-supplied pandas Series or
DataFrames when no persisted Index or formula-definition UID is needed. Its
UTC-indexed result contains `value` and `source_as_of` only.

`IndexFormulaDefinition` owns:

```text
version, status
valid_from, valid_to
formula
alignment_policy, alignment_parameters_json
missing_data_policy
definition_hash, metadata_json
```

`valid_from` is inclusive; `valid_to` is exclusive. Status is `draft`,
`active`, or `retired`.

Create persisted versions with `FormulaIndex.upsert(...)`. Evaluate persisted
versions with `calculate(...)` or bounded `calculate_from_sources(...)`.
Activate drafts with `activate()` and retire versions with `retire()`.

The only alignment policies are:

- `exact`;
- backward-only `asof` with required `max_staleness_seconds`.

The only missing-data policies are `drop` and `fail`.

Formula calculation must reject duplicate timestamps, naive timestamps,
nonnumeric inputs, division by zero, and non-finite output.

## Source Discovery

Asset and Index use the same API and neutral response contract:

```python
Asset.list_related_meta_tables(uid, numeric=True, timestamped=True)
Index.list_related_meta_tables(uid, numeric=True, timestamped=True)
```

Both filters default to true and are independent. Discovery must traverse the
complete visible MetaTable catalog in pages, prove authoritative FKs, and avoid
value scans or distinct-identifier scans.

The discovery result is a source-selection catalog. It does not prove that the
selected Asset or Index currently has observations in the table.

## Publication

Canonical cadence storage is created with:

```python
configured_index_values_storage(cadence="1d")
```

Grain is `(time_index, index_identifier)`. Values contain:

```text
value
definition_uid
observation_status
source_as_of
metadata_json
```

Custom publication uses `IndexValuesDataNode` and must not provide
`definition_uid`.

Formula publication uses:

```python
FormulaIndexDataNodeConfiguration(
    formula_definition_uids=(...),
    source_storage_tables=(...),
)
FormulaIndexDataNode(config, target_storage)
```

The registered source-storage MetaTable UID set must exactly equal the
persisted formula-input UID set. Verify unique UIDs, exact grain, numeric
observables, and build all `APIDataNode` dependencies before `update()`.

Formula results always include the exact formula `definition_uid`.

## Custom And Portfolio Boundary

Use a custom Index when code supplies values without a core formula. Do not
create an empty formula or callback registry.

Self-financing and chained performance are stateful. Calculate them in
Portfolio, then optionally publish NAV/performance as a custom Index.

Selectors, rolling hedge ratios, OLS, delta, DV01, and rebalancing are not
hidden formula-input behavior. Publish reusable upstream observables or use
custom code.

## Catalog And API

Index exploration uses:

```text
Index.list_formulas / Index.get_formula
Index.list_datasets / Index.get_dataset_summary / Index.get_values
Index.list_related_meta_tables
Index.get_summary / Index.get_detail
```

FastAPI formula routes are `/formulas/`, not methodology routes. Formula input
responses contain only `source_reference`, `meta_table_uid`, and `observable`.

Dataset availability distinguishes populated, compatible-empty, and
unavailable. Interactive `has_canonical_values` and `cadence` filters use
indexed availability metadata.

Deletion is the standard direct row API governed by database FKs. Do not add
confirmation secrets, signing tokens, journals, or custom executors.

## Migration Rules

Revision `0015` is a hard one-way replacement. It must fail when old
calculation definitions remain because exact source MetaTable UIDs cannot be
inferred. Do not add compatibility aliases or automatic semantic conversion.

After schema changes, keep provider migrations, runtime model registration,
tests, OpenAPI, docs, examples, tutorial, changelog, and this skill aligned.

## Validation Checklist

1. Run focused parser, engine, API, repository, DataNode, model, migration, and
   example tests.
2. Run FastAPI/OpenAPI and Adapter from API contract tests.
3. Run Ruff on every changed Python file.
4. Build MkDocs in strict mode.
5. Apply the migration through the selected provider and verify current head.
6. Verify mixed Asset/Index example output and custom Portfolio publication.

## Canonical References

1. `docs/ADR/0037-index-formula-and-custom-calculation-framework.md`
2. `docs/ADR/0038-index-user-api-and-fastapi-exploration.md`
3. `docs/knowledge/msm/indices/formula_indexes.md`
4. `docs/tutorial/06-index-formulas.md`
5. `examples/msm/indices/formula_index.py`
