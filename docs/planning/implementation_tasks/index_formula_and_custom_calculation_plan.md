# Index Formula And Custom Calculation Redesign Plan

## Status

Implemented in the library and applied to the selected project on 2026-07-20.
Revision `0015` is the strict one-way schema replacement. The provider upgrade
finalized both formula MetaTables with zero reserved or failed tables, and an
independent `mainsequence migrations current` check reported `0015 (head)`.

Verification evidence:

- `.venv/bin/pytest -q`: `1167 passed, 3 skipped`;
- `.venv/bin/ruff check apps src/msm src/migrations examples tests`: passed;
- `.venv/bin/mkdocs build --strict`: passed;
- `mainsequence migrations upgrade --provider migrations:migration --json`:
  revision `0015` applied and two formula MetaTables finalized;
- `mainsequence migrations current --provider migrations:migration --json`:
  `0015 (head)`.

## Success Condition

The redesign is complete only when:

- the only user-facing Index calculation methods are `formula` and `custom`;
- a formula can reference any mix of typed Asset and Index unique identifiers
  without introducing aliases;
- every formula input pins only the exact MetaTable UID and observable column
  used to resolve its observations;
- Asset and Index expose the same generic `list_related_meta_tables` API, with
  optional `numeric` and `timestamped` filters defaulting to `True`;
- related-MetaTable discovery proves the authoritative
  `asset_identifier -> AssetTable.unique_identifier` or
  `index_identifier -> IndexTable.unique_identifier` relationship instead of
  trusting column names;
- the formula text contains the actual arithmetic instead of selecting an
  operator such as `ratio`, `linear_combination`, or `rebased_basket`;
- custom code publishes Index values without creating a fake formula or a core
  calculation definition;
- self-financing performance is calculated by the Portfolio domain, not the
  generic Index engine;
- stateful chained performance is not implied by an undefined Index operator;
- result presentation uses `decimal` or `percent` plus an optional suffix and
  never drives calculation or unit conversion;
- formula versions retain an explicit start boundary without exposing the
  unclear `effective_from` name to users;
- old calculation kinds and their runtime compatibility aliases are removed;
- migrations, APIs, examples, tests, ADR 0037, concept docs, tutorials, and the
  packaged Index skill all describe the same architecture.

## Architecture Decisions

### 1. Calculation Method Is Formula Or Custom

`Index.calculation_method` is a strict value:

```python
IndexCalculationMethod = Literal["formula", "custom"]
```

- `formula` means core owns and executes a versioned point-in-time expression.
- `custom` means project or extension code owns value production and publishes
  the result through the canonical Index-values DataNode contract.

`index_type` remains the business classification of the observable. It is not
replaced by `calculation_method`, and formula creation must not force
`index_type="derived"`.

A custom Index has no core formula definition. Core must not create an empty
definition, a fake formula, or a registered custom callback to justify values
provided by code.

### 2. Formula Is The Mathematical Contract

The initial formula grammar supports:

- numeric constants;
- typed source fields such as `index["MX_BOND_BENCHMARK"].price` and
  `asset["MX0MGO0000H9"].yield`;
- `+`, `-`, `*`, `/`, `**`, unary `+` and unary `-`;
- parentheses.

The parser must use a strict AST allow-list. The only permitted subscription
and attribute shape is `index["unique_identifier"].observable` or
`asset["unique_identifier"].observable`, with a literal string identifier and
one observable attribute. It must reject function calls, other subscripts,
assignments, comprehensions, arbitrary attribute access, imports, and unknown
names. Python `eval` is not an execution mechanism.

Initial formulas are point-in-time expressions. Time-series functions such as
lagging, chaining, rolling regression, rebalancing, and cumulative returns are
not hidden behind formula operators. A later ADR may add individually defined
formula functions with explicit history contracts.

### 3. Formula Inputs Combine Identity, MetaTable, And Observable

An Asset or Index unique identifier selects the economic identity. It does not
identify a time-series table or a numeric column. Every formula reference must
therefore have one persisted input definition containing exactly:

1. the typed Asset or Index identity;
2. the exact source MetaTable UID;
3. the observable column to read.

The public contract is:

```python
class IndexFormulaSourceReference(BaseModel):
    type: Literal["asset", "index"]
    identifier: str


class IndexFormulaInput(BaseModel):
    source_reference: IndexFormulaSourceReference
    meta_table_uid: str
    observable: str
```

There is no separate source key or alias. The formula uses the typed source
and its canonical unique identifier directly. For example:

```text
index["MX_BOND_BENCHMARK"].price * 5 * asset["MX0MGO0000H9"].yield
```

The complete authoring payload is explicit:

```json
{
  "formula": "index[\"MX_BOND_BENCHMARK\"].price * 5 * asset[\"MX0MGO0000H9\"].yield",
  "inputs": [
    {
      "source_reference": {
        "type": "index",
        "identifier": "MX_BOND_BENCHMARK"
      },
      "meta_table_uid": "9d22ab0c-4ec6-4ee1-8c65-4b2b73b205f1",
      "observable": "price"
    },
    {
      "source_reference": {
        "type": "asset",
        "identifier": "MX0MGO0000H9"
      },
      "meta_table_uid": "563bd46d-fdc2-4a62-8bed-7be9a27499b5",
      "observable": "yield"
    }
  ]
}
```

The parser extracts every `(type, identifier, observable)` reference from the
formula. The input list must match that set exactly: no missing input, no
unused input, and no duplicate input. Persistence resolves stable Asset and
Index identifiers to relational foreign keys while retaining the exact
MetaTable UID and observable column.

There are no configurable identity or value-column fields:

- `source_reference.type="asset"` always filters `asset_identifier`;
- `source_reference.type="index"` always filters `index_identifier`;
- `observable` is the actual numeric MetaTable column used by the formula.

Input validation must prove all of the following before activation:

- the MetaTable UID exists and is visible to the author;
- it is a time-indexed MetaTable with a declared UTC time index;
- the inferred Asset or Index identifier column exists;
- `observable` exists and is numeric;
- the identity column has an authoritative FK or declared relationship to the
  corresponding Asset or Index unique identifier; matching a column name is
  not sufficient;
- the table grain contains no additional dimensions beyond time and the
  inferred identifier;
- the selected identity and observable produce at most one value per timestamp.

Tables with additional unresolved dimensions are rejected. They must first
publish the required resolved series into an unambiguous Asset- or Index-keyed
table, or the Index must use custom code. The formula contract does not expose
generic dimension filters.

`meta_table_uid` and `observable` are immutable formula semantics and
participate in `definition_hash`. Changing either creates a new formula
version. Execution never searches for another table, guesses a similarly named
column, or falls back to a globally registered dataset.

Creation-time visibility does not grant permanent access. Every preview and
publication read rechecks access under the active request or job identity. An
unavailable MetaTable, revoked permission, schema mismatch, or ambiguous grain
is an explicit failure; none is reported as empty data.

### 4. Persisted Source And DataNode Dependency Contracts

The persisted MetaTable UID makes the formula source reproducible, but Main
Sequence DataNode dependencies must also be deterministic and hashed through
registered storage classes. Production publication therefore uses an explicit
deployment snapshot:

```python
class FormulaIndexDataNodeConfiguration(IndexDataNodeConfiguration):
    formula_definition_uids: tuple[uuid.UUID, ...]
    source_storage_tables: tuple[type[PlatformTimeIndexMetaTable], ...]
```

The configuration factory loads the selected immutable formula versions and
collects their distinct source MetaTable UIDs. Construction then:

1. resolves each storage class with `get_time_index_meta_table()`;
2. verifies that the bound UID set exactly equals the formula input MetaTable
   UID set;
3. verifies that every persisted observable still exists;
4. builds every `APIDataNode` dependency in the constructor;
5. exposes the fixed graph through `dependencies()`.

The storage classes and formula-definition UIDs participate in
`update_hash`. Dependencies are never discovered inside `update()`. A formula
version or source MetaTable change requires a new deployment snapshot and
therefore a new update identity.

Pure `IndexFormula.evaluate_historical(...)` remains platform-independent and
accepts caller-supplied Series or DataFrames keyed by the parsed formula
references. The immutable Pydantic model owns the expression, inputs,
alignment, and missing-data policies without requiring persisted identity.
A separate platform source layer performs governed MetaTable reads for
DataNode publication or API preview. It groups inputs by MetaTable UID, applies
the inferred Asset or Index identifier filter server-side, reads only bounded
time ranges and required observable columns, and returns source timestamps for
no-look-ahead validation.

### 5. Generic Related-MetaTable Discovery

MetaTable relationship discovery is not a formula concept. Asset and Index
must expose the same general method name and filter signature:

```python
Asset.list_related_meta_tables(
    uid,
    *,
    numeric: bool = True,
    timestamped: bool = True,
) -> tuple[RelatedMetaTable, ...]

Index.list_related_meta_tables(
    uid,
    *,
    numeric: bool = True,
    timestamped: bool = True,
) -> tuple[RelatedMetaTable, ...]
```

Filter semantics are identical:

- `timestamped=True` returns only registered TimeIndex MetaTables;
- `timestamped=False` disables the timestamped-table filter;
- `numeric=True` returns only tables with at least one numeric data column
  after excluding time and relationship columns;
- `numeric=False` disables the numeric-column filter.

Both methods return the same neutral `RelatedMetaTable` contract. Replace the
Index-specific `IndexRelatedMetaTable` response name rather than creating an
Asset-specific duplicate or retaining a compatibility alias. Filtering is
computed from the registered MetaTable contract; it does not add formula fields
to the response.

The Asset method resolves the selected Asset and searches all visible
registered MetaTables. A table is related through `asset_identifier` only when
catalog foreign-key metadata proves this exact relationship:

```text
source asset_identifier -> AssetTable.unique_identifier
```

The Index method applies the equivalent rule:

```text
source index_identifier -> IndexTable.unique_identifier
```

Matching only an identifier column name is never sufficient. The shared helper
must verify the bound target MetaTable UID or authoritative physical target and
the target `unique_identifier` column.

The unfiltered candidate set includes every visible table with the
authoritative FK regardless of its columns, grain, cadence, or suitability for
a particular consumer. Setting both filters to `False` returns that complete
set. The result uses the same generic related-MetaTable semantics for Asset and
Index: table UID and identifier, relationship/join metadata, authority,
discovery source, access/exploration capability, and deletion behavior where
applicable. Do not add formula-specific fields or filtering to this contract.

Expose the same query parameters on both existing resource paths:

```text
GET /api/v1/asset/{uid}/related-meta-tables/?numeric=true&timestamped=true
GET /api/v1/index/{uid}/related-meta-tables/?numeric=true&timestamped=true
```

The implementation must enumerate the complete visible MetaTable catalog
without the current inferred-table `limit=500` truncation pattern. Results are
ordered deterministically by MetaTable identifier and UID. Discovery inspects
catalog contracts only: it must not scan source values, enumerate distinct
Asset or Index identifiers, or claim that the selected identity has
observations in a table.

Formula authoring is one consumer of this generic catalog. After a user selects
a related MetaTable, the UX reads that MetaTable's normal column contract and
selects an observable. The formula layer then validates the selected
`meta_table_uid`, observable type, identity relationship, and grain. Those
formula-specific decisions do not belong in either
`list_related_meta_tables` method.

### 6. Formula Inputs Do Not Pretend To Be Portfolio Positions

Formula constants and multipliers are visible arithmetic. There is no separate
coefficient method, coefficient registry, leg role, composition mode, or
rebalance policy in the formula model.

Rule selection, OLS, delta, DV01, and other calculated inputs must be produced
as explicit upstream observables or by custom code. A reusable upstream result
may itself be published as an Index and referenced by another formula. This
keeps a formula readable and avoids a second hidden calculation language in
its source rows.

### 7. Stateful Performance Leaves The Generic Formula Engine

`self_financing` is removed from Index calculations. Self-financing requires
positions, capital, cash, financing, transaction costs, and rebalance timing;
those are Portfolio calculation concepts.

The supported workflow is:

```text
Portfolio calculation -> NAV/performance series -> custom Index publisher
```

The Portfolio owns holdings and state. The optional custom Index owns the
reusable published benchmark series.

`chained_return` is also removed. Chaining is stateful and requires an explicit
return convention, seed, rebalance timing, missing-period policy, and revision
policy. Portfolio performance belongs in Portfolio. A non-Portfolio cumulative
series must be implemented and documented by custom code until a separate,
fully specified time-series formula-function contract is accepted.

### 8. Result Unit Becomes Presentation Metadata

Remove `output_unit` from formula definitions and `unit` from canonical Index
observations. Remove Index result validation and conversion through
`UNIT_REGISTRY`.

Store presentation on Index identity:

```python
value_format: Literal["decimal", "percent"]
value_suffix: str | None
```

Formatting rules are:

- `decimal` displays the stored numeric value without scaling;
- `percent` treats the stored value as a decimal ratio, multiplies it by 100
  for display, and displays `%`;
- `value_suffix`, when present, is appended as display text;
- neither field changes formula evaluation or stored numeric values.

Examples include `decimal` with suffix `" bp"`, `decimal` with suffix
`" USD"`, or `percent` without a suffix. Core does not enumerate every
possible economic unit.

Source data must expose a documented numeric representation. Any required
scale or physical conversion is explicit in the formula or produced upstream;
result formatting never performs it.

### 9. Replace Effective From With A Clear Formula Boundary

The temporal boundary is required because formula versions must not rewrite
earlier history. Rename the user-facing field:

```text
effective_from -> valid_from
effective_to   -> valid_to
```

`valid_from` is the first observation timestamp calculated with that formula
version. `valid_to` is exclusive and is set by lifecycle activation when a
successor starts. In user interfaces the label is **Formula starts at**.

`valid_from` remains required for formula definitions. Custom Indexes do not
have formula version boundaries. Removing the boundary entirely would make
formula version selection and historical backfills ambiguous.

## Target Persistence Model

### IndexTable

Add:

- `calculation_method`, constrained to `formula` or `custom`;
- `value_format`, constrained to `decimal` or `percent`;
- nullable `value_suffix`.

Contract invariants:

- a formula Index may own formula versions;
- a custom Index must not own formula versions;
- changing calculation method after formula definitions or canonical values
  exist is rejected;
- formatting is display metadata and is excluded from formula hashes.

### IndexFormulaDefinitionTable

Replace `IndexCalculationDefinitionTable` with a formula-specific model:

| Field | Contract |
| --- | --- |
| `uid` | Formula-version UUID. |
| `index_uid` | FK to a formula Index. |
| `version` | Positive monotonic version. |
| `status` | `draft`, `active`, or `retired`. |
| `valid_from` | Inclusive formula-version start. |
| `valid_to` | Exclusive formula-version end. |
| `formula` | Strict arithmetic expression. |
| `alignment_policy` | `exact` or bounded `asof`. |
| `alignment_parameters_json` | Strict parameters; `asof` requires maximum staleness. |
| `missing_data_policy` | `drop` or `fail`. |
| `definition_hash` | Canonical AST, formula inputs, policies, and validity start. |
| `metadata_json` | Non-calculation descriptive metadata. |

Remove:

- `calculation_kind` and `calculation_parameters_json`;
- `calculation_family`;
- `output_unit`;
- `composition_mode`;
- rebalance fields;
- methodology `source`.

### IndexFormulaInputTable

Replace `IndexCalculationLegTable` with one row per referenced observable:

| Field | Contract |
| --- | --- |
| `uid` | Input-row UUID. |
| `definition_uid` | Owning formula version. |
| `asset_uid` | Nullable Asset FK. |
| `component_index_uid` | Nullable Index FK. |
| `meta_table_uid` | Exact source TimeIndexMetaTable UID; not a relational FK. |
| `observable` | Exact numeric MetaTable column referenced by the formula. |

Exactly one source FK is required. Partial unique constraints enforce one input
per `(definition_uid, asset_uid, observable)` or
`(definition_uid, component_index_uid, observable)`. One source may expose
multiple observables and each observable may use a different MetaTable.

`meta_table_uid` points to the Main Sequence MetaTable catalog and therefore is
validated through the SDK, not declared as a database foreign key in the
ms-markets schema. The formula input keeps the existing relational Asset/Index
FKs for identity and cycle integrity.

`component_kind`, source aliases, source order, roles, selectors, transforms,
coefficient methods, and coefficient parameters are removed. The observable
and source MetaTable UID are first-class fields instead of runtime-only
configuration.

### Canonical Index Values

Keep:

- `time_index` and `index_identifier`;
- `value`;
- nullable `definition_uid`, required for formula-produced rows;
- `observation_status`, `source_as_of`, and `metadata_json` provenance.

Remove observation `unit`. Formatting is read from the selected Index once and
returned as response-level metadata rather than repeated on every observation.

## Target Public API

Replace `DerivedIndex` with `FormulaIndex`; do not add a compatibility alias.

Core entry points become:

- `Index.create/upsert(..., calculation_method, value_format, value_suffix)`;
- `Asset.list_related_meta_tables(uid, numeric=True, timestamped=True)` and
  `Index.list_related_meta_tables(uid, numeric=True, timestamped=True)` with
  identical generic filtering semantics;
- `FormulaIndex.upsert(...)` for atomic formula version and input creation;
- `IndexFormula.evaluate_historical(...)` for pure historical evaluation;
- `FormulaIndex.calculate(...)` for canonical persisted-version preview;
- `FormulaIndex.calculate_from_sources(...)` for permission-checked, bounded
  MetaTable-backed preview;
- `FormulaIndex.activate()` and `FormulaIndex.retire()` for version lifecycle;
- `IndexValuesDataNode` for custom code publication;
- `FormulaIndexDataNode` for platform-backed formula publication.

Methodology responses become formula-version responses and expose `formula`
plus every typed input's source reference, MetaTable UID, and observable. They
do not expose old operator, unit, composition, selector, transform, or
coefficient fields.

Index value and summary responses expose `value_format` and `value_suffix` once.
They do not return `latest_unit` or a per-row `unit`.

## Migration Plan

Revision `0015` implements a strict migration:

1. abort when any old calculation definition remains because the exact source
   MetaTable UID cannot be inferred;
2. initialize existing Index identities as `custom` with decimal formatting;
3. drop old resolved-leg, leg, and definition tables;
4. create formula definition and input tables;
5. repoint the base and discovered cadence-table `definition_uid` foreign keys;
6. remove observation `unit` from the base and discovered cadence tables;
7. provide no legacy downgrade.

Old definitions must be explicitly rewritten as formulas, routed to Portfolio,
or republished by custom code before upgrade. The selected project passed that
preflight, the revision was applied through the configured provider, and the
post-upgrade current-head check reported `0015 (head)`.

The migration is one-time schema evolution, not runtime compatibility. Old
payload fields and calculation-kind names are rejected after the change.

## Implementation Phases

### Phase 1 - ADR And Contracts

- Amend or supersede ADR 0037 before code changes.
- Lock the formula grammar and formula/custom invariants.
- Add typed source references and formula-input Pydantic models with exact
  MetaTable UIDs and observables.
- Add creation-time MetaTable visibility, column, type, relationship, and grain
  validation.
- Add parser security and semantic-hash tests first.

### Phase 2 - Pure Formula Engine

- Parse and canonicalize formulas with the strict AST allow-list.
- Extract typed `source["identifier"].observable` references and require an
  exact formula-input set.
- Evaluate aligned pandas Series without `eval`.
- Reject unresolved identities, missing or unused inputs, division by
  zero, and non-finite output.
- Remove calculation, transform, coefficient, rebalance, and unit registries
  from the Index engine.

### Phase 3 - Persistence And API

- Implement the new Index fields, formula definitions, and persisted formula
  inputs.
- Add the generic Asset `list_related_meta_tables` service and reuse the shared
  authoritative-FK discovery helper with Index.
- Extend both Asset and Index related-MetaTable APIs with identical `numeric`
  and `timestamped` query parameters.
- Replace the Index-specific related-MetaTable response type with the shared
  `RelatedMetaTable` contract and no compatibility alias.
- Replace `DerivedIndex` and methodology response contracts.
- Preserve Asset/Index foreign keys and formula dependency-cycle validation.
- Keep custom publication definition-free.
- Remove old public imports and OpenAPI fields without aliases.

### Phase 4 - DataNodes And Portfolio Boundary

- Build a deployment snapshot from immutable formula versions and registered
  dependency storage classes.
- Verify each dependency class's bound MetaTable UID against the persisted
  formula inputs before constructing dependencies.
- Implement bounded, dimension-scoped mixed Asset/Index reads using the exact
  persisted MetaTable UID and columns.
- Group compatible inputs by MetaTable UID without widening identifier, time,
  or column bounds.
- Publish formula rows with the exact formula-version UID.
- Add the Portfolio-to-custom-Index publication example.
- Remove stateful seed and resolved-leg machinery from the generic formula
  publication path.

### Phase 5 - Migration, Examples, And Documentation

- Run the preflight data audit and remediate unsupported definitions.
- Generate and apply the new migration.
- Rewrite spread and ratio examples as formulas.
- Add the mixed
  `index["MX_BOND_BENCHMARK"].price * 5 * asset["MX0MGO0000H9"].yield`
  example.
- Enhance the mixed-source example to discover the Asset and Index source
  MetaTables and observables before authoring the formula inputs.
- Add a custom-code Index example.
- Remove the generic self-financing and chained-return Index examples.
- Update ADR 0037, concept docs, tutorial, reference docs, changelog, and the
  packaged Index skill.

## Required Tests

- formula parser accepts only the documented grammar;
- Asset related-MetaTable discovery recognizes every visible table with
  an authoritative `asset_identifier -> AssetTable.unique_identifier` FK;
- Index related-MetaTable discovery applies the equivalent authoritative Index
  FK rule;
- a table that merely contains `asset_identifier` or `index_identifier` is not
  returned;
- `numeric=True` requires a numeric data column while `numeric=False` disables
  that filter;
- `timestamped=True` requires a TimeIndex MetaTable while `timestamped=False`
  disables that filter;
- Asset and Index results use the same response contract and deterministic
  ordering;
- related-MetaTable discovery enumerates the complete visible catalog and
  performs no source-value or distinct-identifier scans;
- formula hash ignores whitespace but changes with arithmetic, source
  identity, MetaTable UID, or observable;
- mixed Asset and Index source formulas calculate correctly;
- the parsed formula-reference set must exactly equal the persisted input set;
- unavailable MetaTable UIDs, missing or nonnumeric observable columns,
  unexpected dimensions, and duplicate timestamps fail before calculation;
- DataNode construction rejects a dependency storage class whose bound
  MetaTable UID differs from its persisted formula input;
- dependency graphs are built before `update()` and change the update hash;
- source reads apply identifier, timestamp, and column bounds server-side;
- component Index dependency cycles are rejected;
- exact and bounded as-of alignment are deterministic and have no look-ahead;
- formula Index values require a formula-version UID;
- custom Index values reject a formula-version UID;
- percent and decimal formatting do not alter stored values;
- formula/custom method changes are rejected after publication;
- old calculation kinds and payload fields are absent from public schemas;
- migration preflight rejects any remaining legacy calculation definition;
- existing Index identities become custom decimal-formatted Indexes;
- canonical values retain their history while formula-produced rows reference
  the new formula-definition table;
- strict MkDocs, Ruff, focused Index tests, full Index tests, public import
  tests, example smoke tests, migration upgrade, and migration-current checks
  pass.

## Explicit Non-Goals

- no arbitrary Python execution in formulas;
- no custom callback registry in core;
- no implicit runtime provider, table, or column selection during formula
  calculation;
- no source-value scans during related-MetaTable discovery;
- no runtime fallback from an unavailable MetaTable UID to another compatible
  dataset;
- no stateful Portfolio simulator inside the Index engine;
- no automatic selector, rolling regression, delta, DV01, or rebalance DSL;
- no enumeration of every possible result unit;
- no legacy aliases for the removed architecture.
