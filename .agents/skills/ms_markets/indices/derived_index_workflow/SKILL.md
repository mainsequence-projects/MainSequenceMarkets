---
name: mainsequence-markets-derived-index-workflow
description: Use this skill when creating, extending, reviewing, documenting, or publishing ms-markets derived indexes, or when deciding whether a market workflow belongs to Index or Portfolio. Covers versioned definitions, calculation legs, units, selectors, dynamic coefficients, resolved-leg provenance, DerivedIndexDataNode workflows, and the mandatory Index-versus-Portfolio ownership boundary.
---

# Main Sequence Markets Derived Index Workflow

Use this skill for generic calculated market observables owned by the core
`msm` Index domain. Examples include yield and calendar spreads, butterflies,
ratios, rebased baskets, beta-neutral marks, and self-financing hedged indexes.

## Route And Boundaries

Use `IndexTable` for the stable observable identity and
`IndexCalculationDefinitionTable` plus `IndexCalculationLegTable` for its
versioned methodology. Never introduce a parallel signal identity, put the
methodology in `PortfolioWeightsStorage`, or make `msm_pricing` the generic
calculation owner.

- Assets and component indexes are leg subjects, not derived-index identity.
- Pricing may produce a yield, DV01, delta, or z-spread source fact; Index owns
  how that fact participates in a methodology.
- A Portfolio may consume or replicate a derived index, but portfolio capital,
  quantities, fills, cash, and P&L remain portfolio concepts.
- Entry/exit thresholds and action labels remain downstream signal or strategy
  policy unless they are explicitly the published index value.

## Mandatory Index Versus Portfolio Decision

Make this decision before selecting models or storage.

Use **Index** when the output is a reusable theoretical market observable whose
value is determined by one methodology and the same market inputs for every
consumer. Typical outputs are spreads, ratios, benchmark levels, chained
returns, rule-selected baskets, and theoretical self-financing strategy
indexes.

Use **Portfolio** when the output depends on a particular capital base,
account, owned quantity or notional, cash balance, order, fill, execution
constraint, actual financing charge, realized transaction cost, or realized
P&L.

| Decision question | Route |
| --- | --- |
| Publish a 2s10s yield spread, curve butterfly, calendar spread, beta-neutral mark, or benchmark return series | Index |
| Apply `+1/-1`, beta, delta, DV01, or physical-conversion multipliers to observations | Index legs; these are coefficients, not holdings |
| Publish theoretical self-financing performance with deterministic lag, financing, and cost rules | Index |
| Allocate capital, choose actual notionals, maintain cash, place orders, consume fills, or report realized P&L | Portfolio |
| Track or replicate a published Index with actual positions | Both: Index is the benchmark; Portfolio owns implementation state |
| Turn an Index value into long/short/observe | Downstream signal or strategy policy |

Never infer Portfolio quantities from Index coefficients. Never store an Index
methodology in `PortfolioWeightsStorage`. When both domains are needed, publish
the Index independently through `IndexValuesStorage`; let the Portfolio
reference that Index and persist its own holdings, cash, execution, and P&L.

The decisive distinction is **theoretical methodology versus actual owned and
executed state**. Modelled financing or transaction costs do not by themselves
make a theoretical self-financing Index a Portfolio; account-specific charges,
fills, and realized outcomes do.

## Read First

Inspect the relevant local contracts before changing the workflow:

1. `docs/ADR/0037-core-derived-index-definition-and-calculation-framework.md`
2. `src/msm/models/index_calculations.py`
3. `src/msm/api/derived_indices.py`
4. `src/msm/analytics/indices/`
5. `src/msm/data_nodes/indices/derived.py`
6. `src/msm/data_nodes/indices/storage.py`
7. `docs/knowledge/msm/indices/derived_indexes.md`

For migration changes, also use the ms-markets MetaTable migration skill. For
generic Main Sequence DataNode mechanics, also use the Main Sequence DataNode
skill. Do not run `msm copy-msm-skills` inside the ms-markets source checkout.

## Identity And Versioning

Register or upsert `index_type="derived"`, then create the canonical `Index`
and an immutable methodology version through `DerivedIndex.upsert(...)`.

Rules:

- `Index.unique_identifier` represents one stable historical meaning.
- Output-affecting changes create the next positive `definition_version`.
- Activated effective intervals must not overlap and use inclusive start,
  exclusive end semantics.
- `definition_hash` includes ordered operator, policy, leg, unit, selector,
  transform, and coefficient semantics; it excludes display metadata.
- Retroactive histories that must coexist require distinct Index identities.
- Component-index legs must pass dependency-cycle validation.

Do not mutate SQLAlchemy rows directly from application code. Use the typed
public surface:

```python
from msm.api.indices import (
    DerivedIndex,
    IndexCalculationDefinition,
    IndexCalculationLeg,
)
```

## Leg Modeling

Each leg configures exactly one source:

- `asset_uid` for a fixed Asset;
- `component_index_uid` for another fixed Index;
- `selector_code` plus strict selector parameters for rule resolution.

Set a semantic `observable_code`, explicit `input_unit`, registered
`transform_code`, and registered `coefficient_method`. A fixed coefficient must
be finite. Dynamic methods must leave `coefficient=None` and put window, lag,
bounds, observable, and fallback policy in the method parameters.

Formula coefficients are algebraic multipliers. Never call them portfolio
weights or infer invested quantities from them.

## Operators, Units, And Policies

Initial operators are `linear_combination`, `ratio`, `rebased_basket`,
`chained_return`, and `self_financing`. Use `self_financing` for historical
hedged performance; a same-time expression such as option price minus delta
times spot is a mark, not strategy P&L.

Initial transforms are `identity`, `rebase`, `log`, `simple_return`, and
`log_return`. Alignment is explicit: `inner`, `asof` with maximum staleness, or
`calendar_aligned`. Missing data is explicit: `drop`, `fail`, or
`forward_fill` with maximum age. Never add implicit filling.

Every input and output has a registered unit. Let the core unit registry
convert percent/decimal/basis points and physical units. Reject incompatible
dimensions instead of adding anonymous application multipliers.

## Dynamic Resolution And No Look-Ahead

Selectors and coefficient methods must be deterministic for equal timestamps
and must return source timestamps at or before their effective time.

- Rolling OLS/beta methods require a window, minimum observations, and positive
  effective lag.
- DV01 and delta methods record the risk-observation timestamp and configured
  lag.
- A self-financing calculation applies positions with its explicit
  `position_lag`; same-time resolved risk must not be applied to an already
  completed return period.
- A dynamic definition requires `IndexResolvedLegsStorage` provenance before
  its canonical value can publish.

Resolved rows are methodology audit facts keyed by time, index, leg, and
component. They are not holdings, orders, or executed weights.

## DataNode Publication

Use `DerivedIndexDataNodeConfiguration` with explicit source storage classes.
Those bindings are hashed configuration and `dependencies()` must be built
deterministically before `update()`.

Use:

- `IndexValuesStorage` for canonical `(time_index, index_identifier)` values;
- `IndexResolvedLegsStorage` when membership or coefficients vary;
- `DerivedIndexResolvedLegsDataNode` as the declared provenance dependency of
  `DerivedIndexDataNode` for dynamic methodologies.

Updates are incremental. Use update statistics for normal continuation and
the scoped `repair_after(..., index_identifiers=[...])` path for a controlled
tail repair. The first shared-backend execution must use an explicit
`hash_namespace`.

## Validation Checklist

Before marking work complete, verify:

1. The workflow was explicitly classified as Index, Portfolio, both, or a
   downstream signal, using the ownership rule above.
2. Identity, definition version, effective interval, and hash are correct.
3. Ordered legs have exactly one source and compatible units.
4. Dynamic source timestamps prove no look-ahead.
5. Required resolved-leg provenance exists before values.
6. Output is time-first `datetime64[ns, UTC]` and matches storage grain.
7. Migration metadata and runtime attachment contain the minimal model set.
8. Fixed, dynamic, repair/backfill, example, public-import, and compatibility
   tests pass.
9. Concept docs, tutorial, changelog, and packaged-skill tests stay aligned.
