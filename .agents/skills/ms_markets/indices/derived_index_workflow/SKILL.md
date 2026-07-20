---
name: mainsequence-markets-derived-index-workflow
description: Use when creating, classifying, extending, calculating, reviewing, documenting, migrating, or publishing ms-markets Index data. Covers Index-versus-Asset-versus-Portfolio decisions; plain, caller-calculated, core-derived, and extension-owned Index observations; cadence-specific storage and DataNodes; canonical value normalization; versioned definitions and lifecycle; legs, operators, units, selectors, dynamic coefficients, resolved-leg provenance, and no-look-ahead validation. Do not use for portfolio holdings/execution or for constructing pricing and fixed-income curves.
---

# Main Sequence Markets Index Workflow

Treat an Index as a stable identity for a reusable observable through time. An
Index may be directly observed, calculated outside core, or calculated from a
versioned core methodology. It is not required to be a tradable Asset, a
Portfolio, a signal, or a pricing object.

Use this skill to decide what the observable is, who owns its methodology, how
frequency determines its physical storage, and how to publish an auditable
history without confusing theoretical calculation coefficients with owned
positions.

## Scope Contract

Classify the workflow before choosing models, DataNodes, or tables.

| Workflow | Owner and required contract |
| --- | --- |
| Directly observed or source-published value | Index identity plus a cadence-specific Index observation table; no core calculation definition |
| Value calculated by a caller or external system whose methodology core does not own | Index identity plus cadence-specific publication and source provenance; no artificial core definition |
| Value whose reusable methodology is owned and executed by core | Index identity, versioned `IndexCalculationDefinition`, ordered legs, deterministic engine calculation, and cadence-specific publication |
| Rich domain-specific Index observations | Extension-owned Index-indexed MetaTable and producer; normalize into canonical Index values only when generic interoperability is required |
| Capital allocation, holdings, cash, orders, fills, execution, account costs, or realized P&L | Portfolio, not Index |
| Threshold, z-score, action, or trading decision derived from an Index | Downstream analytics, signal, or strategy policy |
| Curve construction or instrument pricing | Pricing domain; it may supply an input observation, but it does not own generic Index identity or methodology |

Do not load or apply fixed-income curve-building or general-pricing guidance
merely because an Index contains a yield, DV01, delta, or price-like value. Use
those skills only when the requested work actually constructs curves or prices
instruments.

## Mandatory Index Versus Asset Versus Portfolio Decision

Use **Index** when the output is a reusable theoretical market observable whose
meaning is independent of a particular holder. Examples include quoted rates,
spreads, ratios, benchmark levels, chained returns, rule-selected baskets, and
theoretical self-financing strategy indexes.

Use **Asset** for an instrument or economic object that may be owned, traded,
priced, or referenced as a component. An Index calculation may reference an
Asset without becoming that Asset.

Use **Portfolio** when the result depends on a particular capital base,
account, owned quantity or notional, cash balance, order, fill, execution
constraint, actual financing charge, realized transaction cost, or realized
P&L.

| Decision question | Route |
| --- | --- |
| Publish the 10-year swap rate through time | Index, even though swap instruments can exist |
| Publish the same 10-year swap Index at one-minute and daily frequencies | One Index identity; two DataNodes and two physical storage tables |
| Publish a 2s10s spread, butterfly, ratio, benchmark return, or beta-neutral mark | Index |
| Apply `+1/-1`, beta, delta, DV01, or physical-unit multipliers | Index legs; coefficients are formula inputs, not holdings |
| Publish theoretical self-financing performance with deterministic lag, financing, and cost rules | Index |
| Allocate actual capital, maintain cash, place orders, consume fills, or report realized P&L | Portfolio |
| Track or replicate a published Index with actual positions | Both: Index owns the benchmark; Portfolio owns implementation state |
| Convert an Index value into long, short, enter, exit, or observe | Downstream signal or strategy policy |

The decisive boundary is **theoretical observable methodology versus actual
owned and executed state**. Modelled financing or transaction costs do not by
themselves turn a theoretical Index into a Portfolio. Never infer Portfolio
quantities from Index coefficients or store Index methodology in
`PortfolioWeightsStorage`.

## Canonical Relationship

Use one canonical Index identity and add only the layers the workflow needs:

```text
IndexTable
  ├─ optional IndexCalculationDefinitionTable × version
  │    ├─ IndexCalculationLegTable × N
  │    └─ optional IndexResolvedLegsStorage × time/component
  ├─ cadence-specific Index values × time
  ├─ downstream signal analytics
  └─ optional Portfolio replication
```

- `IndexTable` owns stable identity.
- `IndexCalculationDefinitionTable` owns an optional immutable methodology
  version and effective interval.
- `IndexCalculationLegTable` owns ordered formula inputs.
- `IndexResolvedLegsStorage` owns time-varying selector and coefficient audit
  facts.
- A cadence-specific Index-values table owns the published history.
- Signal and Portfolio layers consume Index values without changing Index
  ownership.

Do not create parallel identities such as `SignalIndex`, duplicate core
observation models, or fake Assets for non-asset observables.

## Mandatory Workflow

Follow this order:

1. Classify the result as Index, Asset, Portfolio, downstream signal, or a
   combination with explicit boundaries.
2. Decide whether the Index is plain/source-observed, caller-calculated,
   core-derived, or extension-owned.
3. Register the semantic `IndexType` and establish one stable
   `Index.unique_identifier` for one stable historical meaning. Use the
   built-in `derived` type only for a core-derived Index; do not label every
   observed Index as derived.
4. Select every publication frequency and create one physical storage class
   and DataNode class per stable frequency.
5. For a core-derived Index, create or reuse the immutable effective
   definition and its ordered legs through the typed API.
6. Bind source storage explicitly and resolve selectors or dynamic
   coefficients without look-ahead.
7. Apply transforms, align observations, apply missing-data policy, normalize
   units, resolve/rebalance coefficients, and execute the registered operator
   in engine order.
8. Publish required resolved-leg provenance before publishing dynamic values.
9. Publish canonical values incrementally with explicit status and provenance.
10. Let signals, applications, or Portfolios consume the published Index
    without moving their state into the Index domain.

## Identity, Frequency, And Methodology History

Keep three independent decisions explicit:

1. **Index identity** describes what the historical observable means.
2. **Frequency identity** describes the physical time-series storage contract.
3. **Definition version** describes a core-owned methodology during an
   effective interval.

One-minute and daily observations of the same `USD_SWAP_10Y` meaning retain one
Index identity but require separate DataNodes and tables. Build the canonical
models with:

```python
Swap10Y1mStorage = configured_index_values_storage(cadence="1m")
Swap10Y1dStorage = configured_index_values_storage(cadence="1d")
```

These resolve to distinct canonical contracts:

| Frequency | MetaTable identity | Physical table |
| --- | --- | --- |
| `1m` | `IndexValuesTS.1m` | `ms_markets__index_values__t_1m` |
| `1d` | `IndexValuesTS.1d` | `ms_markets__index_values__t_1d` |

Frequency must drive all of the following:

- `__cadence__`;
- MetaTable identifier;
- physical table suffix;
- storage hash components;
- DataNode class and output storage.

Never encode stable frequency only in a schedule, runtime config, column, or
`hash_namespace`. Never mix stable frequencies in one canonical physical
table.

Frequency alone does not split Index identity. Split the identity when the
observable meaning differs, such as official closing versus indicative
intraday methodology, or when full incompatible histories must coexist.

For calculation changes:

- retain the definition for software-only fixes that do not alter semantics;
- create a prospective definition version when the methodology meaning changes
  while the continuous Index identity remains valid;
- create distinct Index identities when complete method histories coexist or
  the historical meaning changes materially.

Do not silently rewrite methodology history.

## Plain And Caller-Calculated Observations

Not every Index is core-derived. A quoted `USD_SWAP_10Y` rate, a vendor value,
or a value calculated by a caller can be published without an
`IndexCalculationDefinition` when core neither owns nor promises to reproduce
the method.

Publish through `IndexValuesDataNode` into a table returned by
`configured_index_values_storage(cadence=...)`. The canonical grain is:

```text
(time_index, index_identifier)
```

Canonical fields are:

- required `value` and `unit`;
- nullable `definition_uid`;
- nullable `observation_status`;
- nullable `source_as_of`;
- nullable `metadata_json` for non-semantic provenance.

Leave `definition_uid` null for plain or caller-owned methodology. Do not
invent a spread, leg graph, pricing model, or core definition merely to justify
storage. Use `IndexValuesStorage` only as the schema anchor; publish to a
concrete cadence-configured class.

## Core-Derived Methodology

Use `IndexCalculationDefinitionTable` only when core owns the reusable method.
Create and mutate definitions through the typed public surface, never by
writing SQLAlchemy rows directly:

```python
from msm.api.indices import (
    DerivedIndex,
    IndexCalculationDefinition,
    IndexCalculationLeg,
)
```

Use `DerivedIndex.upsert(...)` for atomic identity, definition, and leg
creation. Use `get_by_identifier`, `get_by_index_uid`, and
`definition_history` for inspection; use `activate` and `retire` for lifecycle;
use `calculate` for pure preview without publication.

Each definition must make these semantics explicit:

- positive, monotonic `definition_version`;
- lifecycle status `draft`, `active`, or `retired`;
- inclusive `effective_from` and exclusive `effective_to`;
- registered `calculation_kind` and optional calculation parameters;
- semantic `calculation_family`;
- registered output unit;
- alignment policy and parameters;
- missing-data policy and parameters;
- composition mode `fixed`, `rule_selected`, or `rebalanced`;
- rebalance policy and parameters when applicable;
- deterministic `definition_hash`.

Activated effective intervals must not overlap. The semantic hash must include
ordered operator, policy, leg, unit, selector, transform, coefficient, and
effective-start semantics. It must exclude database UID, version number,
lifecycle status, `effective_to`, source label, and display metadata. Component
Index legs must pass dependency-cycle validation.

## Leg Methodology

Each ordered leg must have a stable `leg_key`, order, optional role, semantic
`observable_code`, explicit `input_unit`, registered `transform_code`, and
registered `coefficient_method`.

Configure exactly one source per leg:

- `asset_uid` for a fixed Asset;
- `component_index_uid` for a fixed component Index;
- `selector_code` plus strict selector parameters for rule resolution.

A fixed coefficient must be finite. Dynamic coefficient methods must leave
`coefficient=None` and put window, lag, bounds, observable, and fallback policy
in method parameters. Formula coefficients are algebraic multipliers, not
positions or portfolio weights.

## Calculation Pipeline And Registered Capabilities

Execute methodology deterministically in this order:

```text
resolve sources -> transform legs -> align -> apply missing policy
-> normalize units -> resolve/rebalance coefficients -> calculate operator
-> validate output unit -> publish
```

Use only registered capability codes and strict parameter validation.

| Registry | Initial codes |
| --- | --- |
| Calculation | `linear_combination`, `ratio`, `rebased_basket`, `chained_return`, `self_financing` |
| Transform | `identity`, `rebase`, `log`, `simple_return`, `log_return` |
| Coefficient | `fixed`, `equal_weight`, `price_ols`, `return_ols`, `beta_neutral`, `dv01_neutral`, `delta` |
| Selector | `nearest_tenor`, `most_liquid_near_tenor`, `futures_rank` |
| Alignment | `inner`, `asof`, `calendar_aligned` |
| Missing data | `drop`, `fail`, `forward_fill` |
| Rebalance | `daily`, `weekly`, `monthly`, `quarterly`, `event` |

Use `asof` only with explicit maximum staleness. Use `forward_fill` only with
explicit maximum age. A ratio must identify numerator and denominator roles.
A same-time delta-adjusted expression is a mark, not self-financing
performance. `self_financing` requires explicit prior/lagged positions plus
financing and cost semantics.

## Units

Every leg input and definition output must use registered units. Core supports:

- rate conversions among `decimal`, `percent`, and `basis_points`;
- dimensionless `ratio`;
- `index_points`;
- separate currency dimensions including `usd`, `mxn`, `eur`, `gbp`, and
  `jpy`;
- physical conversion between `usd_per_gallon` and `usd_per_barrel` using the
  registered factor of 42.

Reject incompatible dimensions. Do not imply foreign-exchange conversion
between currency units and do not hide anonymous multipliers in metadata.

## Dynamic Resolution And No Look-Ahead

Selectors and coefficient methods must be deterministic for equal timestamps.
Every resolved source timestamp must be at or before its effective time.

- OLS and beta methods require a positive lag, window, and minimum observation
  count.
- DV01 and delta methods record the risk-observation timestamp, configured lag,
  bounds, and fallback behavior.
- Self-financing calculations apply positions using explicit `position_lag`;
  same-time risk may not be applied to an already completed return interval.
- Dynamic methodologies must publish `IndexResolvedLegsStorage` before their
  canonical values.

Resolved-leg grain is:

```text
(time_index, index_identifier, leg_key, resolved_component_key)
```

Persist definition UID, component kind, resolved coefficient, coefficient
method, observable, source observation time, status, and metadata required for
audit. Resolved rows are methodology provenance, not holdings, orders, or
executed weights.

## DataNode Publication

Use one explicit cadence-specific output storage per DataNode.

- `IndexValuesDataNode` publishes plain or caller-calculated observations.
- `DerivedIndexResolvedLegsDataNode` publishes dynamic resolution provenance.
- `DerivedIndexDataNode` calculates and publishes core-derived values.

For core-derived non-empty output, require exact `definition_uid`, registered
`observation_status`, unit, and cadence-specific storage. Use
`DerivedIndexDataNodeConfiguration` with explicit source storage classes.
Source bindings are hashed configuration, and dependencies must be built
deterministically before `update()`.

All frames must be time-first with `datetime64[ns, UTC]` and must match the
declared table grain. Updates are incremental. Use update statistics for normal
continuation and scoped `repair_after(..., index_identifiers=[...])` for tail
repair. Use an explicit `hash_namespace` for the first shared-backend
execution, but never use it as a substitute for cadence-owned storage identity.

## Extension-Owned Index Storage

An extension may define its own Index-indexed
`PlatformTimeIndexMetaTable` and producer. Do not require it to inherit
`IndexTimestampedDataNode`, `IndexValuesDataNode`, or concrete
`IndexValuesStorage`.

Require the extension contract to provide:

- canonical Index identity;
- `index_identifier -> IndexTable.unique_identifier` foreign key;
- declared UTC time and identity grain;
- one stable cadence per physical table;
- frequency-bearing MetaTable identity, table name, and cadence;
- normal migration ownership and validation.

The extension may retain richer native fields. Normalize one selected value
into the matching cadence-specific canonical Index-values table only when a
generic consumer needs the common contract. Do not introduce another core
`IndexObservationsStorage` abstraction.

## Index Catalog, Exploration, And Lifecycle API

Use the typed `Index` catalog methods when a caller needs to manage or inspect
the observable rather than author a new calculation engine:

```python
Index.list_page(...)
Index.get_detail(uid)
Index.get_summary(uid)
Index.list_methodologies(uid)
Index.get_methodology(uid, definition_uid)
Index.list_datasets(uid)
Index.get_dataset_summary(uid, meta_table_uid)
Index.get_values(uid, meta_table_uid, start=..., end=...)
Index.list_related_meta_tables(uid)
Index.delete(uid)
```

`DerivedIndex` remains the methodology-authoring API. Do not duplicate its
upsert, activation, retirement, or pure-calculation behavior in HTTP routes.

Canonical dataset discovery must prove all of the following together:

- registered identifier `IndexValuesTS.<cadence>`;
- cadence matching the identifier and configured storage identity;
- frequency-specific physical table;
- grain containing `time_index` and `index_identifier`;
- required `value` and `unit` columns;
- an actual SQLAlchemy/Alembic foreign key from `index_identifier` to
  `IndexTable.unique_identifier`;
- caller view access.

Never promote a table based on an `index_identifier` column name, description,
or physical-name prefix. Extension relationship providers must supply the same
authoritative FK proof, but their producer does not have to inherit a core
Index DataNode.

For HTTP value browsing, require a selected Index UID, selected registered
MetaTable UID, timezone-aware start/end, stable order, and server-enforced row
limit. Always resolve the UID to `Index.unique_identifier` and apply that
dimension filter. Return the SDK `TabularFrameResponse` for Command Center
table/chart consumers. If the installed `APIDataNode` read method cannot
enforce a server page limit, use a governed bounded compiled SELECT; never load
full history and truncate in memory.

Index deletion uses the standard direct row API. Database `CASCADE`,
`SET NULL`, `RESTRICT`, and `NO ACTION` constraints govern related rows.
Identity deletion does not imply deletion of canonical timestamped values or
extension-owned storage.

This lifecycle surface does not change the Index-versus-Portfolio decision.
Browsing or deleting an Index's benchmark history is Index work. Managing the
actual positions, notional, cash, orders, fills, transaction costs, or realized
P&L of a replication remains Portfolio work.

## Migration Contract

Build every configured storage class before constructing its SDK migration
provider and include the exact models in `metatable_models`. Use the
SDK-managed provider and migration CLI. Runtime attachment is not schema
creation. Do not edit an applied migration; create a new revision.

For schema changes, use the ms-markets MetaTable migration skill in addition to
this skill. For DataNode mechanics, use the Main Sequence DataNode skill. For
table contracts, use the Main Sequence MetaTable skill.

## Read First

Inspect the current contracts before changing behavior:

1. `docs/ADR/0037-core-derived-index-definition-and-calculation-framework.md`
2. `docs/ADR/0038-index-user-api-fastapi-exploration-and-safe-deletion.md`
3. `docs/knowledge/msm/indices/index.md`
4. `docs/knowledge/msm/indices/derived_indexes.md`
5. `src/msm/models/index_calculations.py`
6. `src/msm/api/derived_indices.py`
7. `src/msm/services/indices/`
8. `src/msm/analytics/indices/`
9. `src/msm/data_nodes/indices/values.py`
10. `src/msm/data_nodes/indices/derived.py`
11. `src/msm/data_nodes/indices/storage.py`

Also verify current Main Sequence behavior against:

- `https://mainsequence-sdk.github.io/mainsequence-sdk/knowledge/data_nodes/`
- `https://mainsequence-sdk.github.io/mainsequence-sdk/knowledge/meta_tables/sqlalchemy/`

Inspect these examples for executable patterns:

- `examples/msm/indices/plain_index_values.py`
- `examples/msm/indices/index_values_frequency_migration.py`
- `examples/msm/indices/extension_owned_index_storage.py`
- the fixed, ratio, dynamic OLS, selector, and self-financing examples under
  `examples/msm/indices/`.

Do not run `msm copy-msm-skills` inside the ms-markets source checkout.

## Reject These Designs

Reject implementations that:

- create a fake Asset solely to store an Index observation;
- use Portfolio weights or positions as Index methodology;
- create a separate signal-index identity;
- hide output-affecting methodology in `metadata_json`;
- make pricing the generic owner of Index calculation;
- mix one-minute and daily history in one canonical table;
- express cadence only through schedule, config, or hash namespace;
- publish directly to the abstract `IndexValuesStorage` schema anchor;
- calculate production history only on request instead of publishing it;
- force extension producers into a concrete core DataNode inheritance tree;
- apply dynamic sources or coefficients with look-ahead;
- mutate active definition semantics or applied migrations in place.

## Stop And Resolve Ambiguity

Do not proceed by guessing when any of these are unclear:

- whether the output is theoretical methodology or actual owned state;
- whether core owns the calculation method;
- whether two histories share one stable Index meaning;
- which frequency owns each physical table;
- which source storage and unit feed each leg;
- which definition is effective at a timestamp;
- how alignment, missing data, lag, staleness, or fallback works;
- whether a dynamic calculation proves no look-ahead;
- which migration provider owns a new configured model.

## Validation Checklist

Before marking work complete, prove all applicable items:

1. Classification explicitly states Index, Asset, Portfolio, signal, pricing
   input, or combined boundaries.
2. Plain, caller-calculated, core-derived, or extension-owned methodology
   ownership is explicit.
3. One stable historical meaning maps to one Index identity.
4. Every stable frequency has its own DataNode, MetaTable identity,
   `__cadence__`, storage hash, and physical table.
5. Plain values may omit `definition_uid`; core-derived values may not.
6. Definition version, lifecycle, effective interval, and semantic hash are
   correct and non-overlapping.
7. Ordered legs have exactly one source, registered units/transforms/methods,
   and no dependency cycles.
8. Alignment, missing-data, unit, transform, coefficient, and operator steps
   are deterministic and ordered.
9. Dynamic source timestamps, lags, and positions prove no look-ahead.
10. Required resolved-leg provenance exists before dynamic values.
11. Output is time-first `datetime64[ns, UTC]`, matches storage grain, and
    carries required value, unit, status, and provenance.
12. Extension-owned storage is not forced into core concrete inheritance.
13. Every configured model is built before its migration provider, and the
    provider owns the minimal exact model set.
14. Plain, fixed, ratio, dynamic, selector, self-financing, frequency,
    migration, repair/backfill, public-import, example, and compatibility tests
    pass as applicable.
15. ADR, concept docs, tutorial, changelog, examples, and packaged skill remain
    aligned with implemented behavior.
16. Catalog discovery proves real foreign keys and never treats matching column
    names as relationship authority.
17. Value browsing applies one explicit Index dimension, bounded timestamps,
    deterministic ordering, and a server-enforced row limit.
18. Index identity deletion uses the standard direct row API and leaves
    related-row behavior to declared database foreign-key actions.
