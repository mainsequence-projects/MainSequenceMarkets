# ADR 0037: Index Formula And Custom Calculation Framework

## Status

Accepted and implemented in the library on 2026-07-20. Alembic revision
`0015` is authored as a strict one-way replacement. Applying and verifying the
revision against the configured platform remains a deployment step because the
project endpoint was unavailable during implementation.

## Context

An Index is a stable observable identity. Values may either be supplied by
project code or calculated from other Asset and Index observations. The former
operator-and-leg design mixed formula text, hidden transforms, dynamic
coefficients, result units, portfolio state, and runtime source bindings. It
made a definition difficult to read and impossible to reproduce without
additional deployment configuration.

The replacement has two explicit calculation methods:

- `formula`: core evaluates a versioned point-in-time expression;
- `custom`: project or extension code publishes canonical Index values.

`index_type` remains an independent business classification. A formula does
not force an Index into a special type.

## Decision

### Index Identity

`IndexTable` owns:

| Field | Contract |
| --- | --- |
| `unique_identifier` | Stable business identity. |
| `index_type` | Business classification. |
| `display_name` | User-facing name. |
| `calculation_method` | Exactly `formula` or `custom`. |
| `value_format` | Exactly `decimal` or `percent`. |
| `value_suffix` | Optional display suffix. |

Formatting never changes stored values or formula evaluation. `percent`
means a stored decimal ratio is multiplied by 100 for display. A suffix is
plain presentation text.

Changing `calculation_method` is rejected after formula versions or populated
canonical observations exist.

### Formula Grammar

The initial grammar is deliberately small:

```text
index["INDEX-ID"].observable
asset["ASSET-ID"].observable
numeric constants
+ - * / **
unary + and -
parentheses
```

Examples:

```text
index["MXN-TIIE-28D"].price * 5 + asset["MX-GOVT-5Y"].yield
(asset["BOND-5Y"].yield - asset["BOND-2Y"].yield) * 10000
```

The parser is an allow-listed recursive parser. It does not use `eval` and
rejects calls, assignments, arbitrary names, arbitrary attributes,
comprehensions, imports, and nonliteral source identifiers.

Formulas are point-in-time arithmetic. Lagging, chaining, rolling estimation,
rebalancing, and portfolio accounting are not formula operators.

### Exact Formula Inputs

Every parsed reference must have exactly one public input:

```json
{
  "source_reference": {
    "type": "asset",
    "identifier": "MX-GOVT-5Y"
  },
  "meta_table_uid": "22222222-2222-2222-2222-222222222222",
  "observable": "yield"
}
```

The public input has only those three fields. It has no alias, resolver
wrapper, configurable identity column, configurable value column, or static
dimension filters.

Identity columns are implied:

- Asset input: `asset_identifier`;
- Index input: `index_identifier`.

Persistence resolves the public identifier to exactly one relational
`asset_uid` or `component_index_uid` and retains the exact MetaTable UID and
observable. Input validation requires:

- a visible registered time-indexed MetaTable;
- an authoritative FK from the implied identity column to the corresponding
  `unique_identifier`;
- exact grain `(time_index, asset_identifier)` or
  `(time_index, index_identifier)`;
- a numeric observable column;
- no additional unresolved dimensions.

The parsed reference set and input set must match exactly. MetaTable UID and
observable participate in the semantic hash. Runtime execution never searches
for a replacement table or guesses a column.

### Formula Persistence And Lifecycle

`IndexFormulaDefinitionTable` stores immutable versions with:

```text
uid, index_uid, version, status
valid_from, valid_to
formula
alignment_policy, alignment_parameters_json
missing_data_policy
definition_hash, metadata_json
```

`valid_from` is inclusive and `valid_to` is exclusive. Status is `draft`,
`active`, or `retired`. Version numbers are positive and monotonic, semantic
hashes are unique per Index, and at most one version is active.

`IndexFormulaInputTable` stores:

```text
uid, definition_uid
asset_uid or component_index_uid
meta_table_uid, observable
```

Exactly one source FK is required. Index-to-Index dependency cycles are
rejected.

`FormulaIndex.upsert(...)` owns identity, immutable version, exact inputs,
hash idempotency, and requested lifecycle status. `activate()` atomically
retires an open predecessor when its interval ends at the successor's
`valid_from`. `retire()` sets an exclusive end boundary.

There are no compatibility aliases for the removed definition, leg,
resolved-leg, or calculation-registry APIs.

### Alignment And Missing Data

Supported alignment policies are:

- `exact`: calculate only at timestamps shared by all sources, unless explicit
  calculation times are supplied;
- `asof`: backward-only alignment bounded by required
  `max_staleness_seconds`.

As-of alignment never looks ahead. Missing-data policy is `drop` or `fail`.
Duplicate source timestamps, nonnumeric values, division by zero, and
non-finite results fail explicitly.

### Pure And Platform-Backed Calculation

`IndexFormula` is the self-contained Pydantic value object for an expression,
its exact inputs, alignment, and missing-data policy.
`IndexFormula.evaluate_historical(...)` accepts caller-supplied pandas
observations, requires no persisted Index or definition UID, and returns UTC
historical values with source-as-of provenance. It performs no platform reads.

`FormulaIndex.calculate(...)` applies the same engine to a persisted formula
version and adds canonical Index and definition provenance.

`FormulaIndex.calculate_from_sources(start=..., end=...)` performs a bounded
read from each pinned MetaTable under the active SDK identity. Reads apply the
implied source identifier, time range, and required columns before evaluation.
For as-of formulas, the source read starts only far enough back to satisfy the
maximum staleness bound.

### Publication

Canonical storage grain remains:

```text
(time_index, index_identifier)
```

Rows contain `value` and optional provenance:

```text
definition_uid, observation_status, source_as_of, metadata_json
```

Observation `unit` is removed. A formula result always carries its immutable
formula-definition UID. Custom publication rejects a supplied definition UID.

`FormulaIndexDataNodeConfiguration` pins:

```python
formula_definition_uids: tuple[UUID, ...]
source_storage_tables: tuple[type[PlatformTimeIndexMetaTable], ...]
```

Construction requires the registered source-storage UID set to equal the
persisted formula-input MetaTable UID set. It also verifies exact source grain,
numeric observables, unique storage UIDs, and constructs every dependency
before `update()`. Formula versions and source storage classes therefore
participate in the DataNode update identity.

Custom code publishes with `IndexValuesDataNode` and does not create a fake
formula.

### Related MetaTable Discovery

Asset and Index expose the same API:

```python
Asset.list_related_meta_tables(uid, numeric=True, timestamped=True)
Index.list_related_meta_tables(uid, numeric=True, timestamped=True)
```

Discovery traverses the complete visible MetaTable catalog in bounded pages.
It proves the authoritative FK to `AssetTable.unique_identifier` or
`IndexTable.unique_identifier`; a matching column name alone is insufficient.
It does not scan source values or enumerate identifiers.

`numeric=False` disables the numeric-column filter.
`timestamped=False` disables the time-indexed filter. Both resources return
the neutral `RelatedMetaTable` contract and expose equivalent FastAPI query
parameters.

### Portfolio Boundary

Self-financing and chained-performance calculations are not generic Index
formulas. Self-financing requires holdings, cash, financing, costs, and
rebalance state. The supported flow is:

```text
Portfolio calculation -> NAV/performance series -> custom Index publication
```

Other stateful series remain custom code until their history and revision
semantics are separately specified.

## Migration

Revision `0015`:

1. aborts when legacy calculation definitions exist because exact source
   MetaTable UIDs cannot be inferred safely;
2. initializes existing Index rows as `custom` with decimal formatting;
3. removes old resolved-leg, leg, and definition tables;
4. creates formula definition and input tables;
5. repoints canonical base and cadence-table `definition_uid` FKs;
6. removes observation `unit` from canonical base and cadence tables;
7. intentionally provides no legacy downgrade.

Unsupported legacy rows must be explicitly republished as formulas, routed to
Portfolio, or implemented as custom publishers before migration. Runtime
compatibility code is not provided.

## Consequences

- Formula meaning is readable from the expression and exact input rows.
- Asset and Index inputs can be mixed without aliases.
- Deployment dependencies are deterministic and reproducible.
- Generic formulas cannot hide selectors, transforms, rolling coefficients,
  or portfolio state.
- Source schemas with extra dimensions must first publish an unambiguous
  series or use custom code.
- The one-way migration requires deliberate remediation of any old
  definitions.

## Success Criteria

- [x] Only `formula` and `custom` are accepted calculation methods.
- [x] Formula parsing is allow-listed and does not execute Python.
- [x] Mixed Asset and Index formulas use exact MetaTable UID and observable
  inputs with no source aliases.
- [x] Formula lifecycle, hashes, validity intervals, and cycle checks are
  persisted.
- [x] Exact and bounded backward as-of calculation are implemented.
- [x] Formula and custom publication paths enforce definition provenance.
- [x] Observation units and the unit registry are removed.
- [x] Asset and Index related-table discovery share filters and a neutral
  response contract.
- [x] Formula DataNode dependencies are fixed before update execution.
- [x] Self-financing is demonstrated through Portfolio-owned calculation and
  custom Index publication.
- [x] Public imports, FastAPI routes, OpenAPI, examples, tutorial, concept
  docs, changelog, and the packaged Index skill document this architecture.
- [x] The mixed-source example demonstrates the formula and source discovery
  workflow.
- [ ] Apply revision `0015` and verify migration current against the target
  platform when its configured API endpoint is available.
