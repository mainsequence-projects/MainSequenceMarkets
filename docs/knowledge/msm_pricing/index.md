# msm_pricing

`msm_pricing` owns priceable instrument terms, pricing-specific reference data,
curve and fixing observations, and the QuantLib runtime that turns those rows
into valuations. Core `msm` owns canonical assets and canonical indexes;
pricing extends those rows with pricing contracts instead of widening the core
tables.

Install pricing explicitly with `ms-markets[pricing]` and import the runtime
through `msm_pricing`. The core `ms-markets` install does not require QuantLib.

This page is the operational overview for pricing persistence: which objects
exist, how they point to each other, and what a user or source publisher must
create before pricing works. The focused concept pages linked below cover each
layer in detail.

[ADR 0026](../../ADR/0026-explicit-pricing-market-data-sets.md) defines the
implemented pricing market-data set architecture. Pricing no longer stores
runtime source selection as loose `context_key` plus DataNode identifier
strings. It stores first-class market-data set rows and concept bindings keyed
by backend DataNode storage table UID.

[ADR 0033](../../ADR/0033-pricing-valuation-position-boundary.md) defines the
target boundary for valuation baskets. Pricing should value transient
instrument-and-units lines for an explicit valuation context, but it should not
own a durable generic position registry.

[ADR 0036](../../ADR/0036-prepared-pricing-valuation-context.md) defines the
implemented prepared valuation context for portfolio and scenario pricing. The
context resolves market-data sets, conventions, curve bindings, curves,
curve-building details, observations, and fixings through bulk SQLAlchemy-backed
query planning before the pricing hot loop starts; a public API that merely
hides per-line resolver loops does not satisfy that decision.

## In this section

- [Market Data Sets](market_data_sets.md): first-class `PricingMarketDataSet`
  rows, concept bindings, default-binding seeding, the
  `data_node_uid` vs `storage_table_identifier` boundary, and selecting
  `eod`/`live`/`risk_manager` sets.
- [Instruments](instruments.md): the asset-to-instrument projection
  (`AssetCurrentPricingDetailsTable`, attach/load helpers) and the account and
  portfolio valuation inputs (`ValuationLine`/`ValuationPosition`).
- [Curves](curves.md): curve rows (`CurveTable`), build details
  (`CurveBuildingDetailsTable`), market-data-set curve bindings, and curve
  observations (`DiscountCurvesNode`).
- [Fixings](fixings.md): index fixing observations (`FixingRatesNode`).
- [Scenarios](scenarios/index.md): transient curve scenario and generic
  valuation workflow orchestration under `msm_pricing.scenarios`.
- [Analytics](analytics.md): pure-data spread analytics, cross-asset spread
  primitives, fixed-income DV01 spread metrics, optional dependency boundaries,
  and future sibling module policy.
- [Runtime Resolution](runtime_resolution.md): the persisted-graph resolution
  chain that `price()` follows and the end-to-end fixed-income user workflow.

## What Pricing Owns

Pricing answers these questions:

- Which instrument payload is attached to this asset right now?
- Which backend index UID does the instrument reference?
- Which index conventions reconstruct a QuantLib index?
- Which curve row should be selected for this valuation role?
- Which curve and fixing observations should be read for the valuation date?
- Which QuantLib objects should be materialized for `price()` and cashflow
  analytics?

Pricing does not own:

- Asset identity. Assets stay in `msm.models.AssetTable`.
- Index identity. Indexes stay in `msm.models.IndexTable`.
- Platform Constant aliases. Constants are not pricing identity.
- Curve-as-asset modeling. Curves are pricing rows, not tradable assets.
- Durable generic position state. Pricing can value transient
  instrument-and-units baskets, but accounts and portfolios own their own
  exposure state.
- Legacy string relationships such as `floating_rate_index_name`.

## Package Map

```text
msm_pricing/
  api/             row APIs and instrument attach/load bridge helpers
  instruments/     Pydantic priceable instrument contracts
  models/          SQLAlchemy MetaTable declarations owned by pricing
  data_nodes/      pricing DataNodes and storage-facing publishing helpers
  pricing_engine/  QuantLib builders, resolvers, pricers, and analytics
  scenarios/       transient scenario workflows
    curves/        curve shocks, key-node bumps, runtime curve handles
    valuation/     base/scenario valuation workflow orchestration
  analytics/       pure-data analytics such as spread z-scores and pair metrics
  data_interface/  platform reads for curves and index fixings
  utils/           shared date and serialization utilities
```

`msm_pricing.models` must mean pricing-owned SQLAlchemy MetaTables. Runtime
pricing helpers belong in `msm_pricing.pricing_engine`. Pure-data analytics
that operate on caller-supplied marks belong in `msm_pricing.analytics`.

## Persisted Graph

The pricing graph has four persistent layers:

1. core assets and indexes from `msm`;
2. pricing MetaTables that extend assets and indexes;
3. pricing DataNodes that publish curve and fixing observations;
4. serialized instrument payloads that reference backend UUIDs.

Per [ADR 0035](../../ADR/0035-pricing-curve-identity-and-market-data-curve-bindings.md),
curve **identity**, curve **construction**, index **conventions**, and curve
**selection** are four separate responsibilities. `CurveTable` has no index
ownership column: the link from an index to a curve is *valuation policy* held in
`PricingMarketDataSetCurveBindingTable`, not intrinsic curve identity. The full
relationship map:

```text
                 CORE msm REFERENCE                         PRICING EXTENSIONS (1:1)
        +-------------------+                          +-----------------------------+
        | AssetTable        |  1 ───── 1:1 ──────────> | AssetCurrentPricingDetails  |
        | uid, unique_id    |  (asset_uid PK/FK)       | instrument payload (refs     |
        +-------------------+                          | index UIDs inside payload)   |
                                                       +-----------------------------+
        +-------------------+                          +-----------------------------+
        | IndexTable        |  1 ───── 1:1 ──────────> | IndexConventionDetails       |
        | uid, unique_id    |  (index_uid PK/FK)       | QuantLib index + fixings only|
        +---------+---------+                          +-----------------------------+
                  │
                  │ unique_identifier
                  ▼
        +-------------------+
        | IndexFixings      |  observations keyed by index_identifier
        | Storage (obs)     |
        +-------------------+

                 PRICING CURVE REGISTRY  (NO index ownership — ADR 0035)
        +-------------------+  1 ──── 1:1 (curve_uid PK/FK) ──> +-------------------------+
        | CurveTable        |                                   | CurveBuildingDetails    |
        | uid, unique_id    |                                   | builder_type,           |
        | curve_type        |                                   | interpolation, ...      |
        | currency_code     |                                   | (how to build the QL    |
        | quote_side        |                                   |  term structure)        |
        +---+-----------+---+                                   +-------------------------+
            │ 1         ▲ N
            │           │ curve_uid  (NOT unique here)
            │ unique_id │
            ▼           │
   +-----------------+  │        MARKET-DATA SETS: two binding layers
   | DiscountCurves  |  │   +-----------------------------------------------+
   | Storage (obs)   |  │   | PricingMarketDataSetTable (set_key)           |
   +-----------------+  │   +------+----------------------------------+-----+
                        │      1 │ N (concept binding)        1 │ N (curve binding)
                        │        ▼                              ▼
              +---------+----------------+      +-------------------------------------+
              | PricingMarketDataSet     |      | PricingMarketDataSetCurveBinding    |
              | CurveBinding             |      | concept_key -> data_node_uid        |
              | role_key, selector_type, |      |  (SOURCE: which storage table)      |
              | selector_key, quote_side |      +------------------+------------------+
              |   -> curve_uid ──────────┘                         │ data_node_uid
              | selector_key MAY hold an                           ▼
              | IndexTable.uid as a STRING                 selected storage table
              | (policy, not a table FK)                   (e.g. DiscountCurvesStorage)
              +--------------------------+
```

Read it as two questions answered by two different binding rows:

- **Where do I read observations from?** `PricingMarketDataSetBinding`:
  `(market_data_set, concept_key) -> data_node_uid -> storage table`.
- **Which curve identity inside that storage do I use?**
  `PricingMarketDataSetCurveBinding`:
  `(market_data_set, role_key, selector_type, selector_key, quote_side) -> curve_uid`.

Cardinalities that matter:

- `AssetCurrentPricingDetails`, `IndexConventionDetails`, and
  `CurveBuildingDetails` are each **one-to-one** with their parent
  (`asset_uid`, `index_uid`, `curve_uid` is both PK and FK).
- A curve binding is **many-to-one** onto `CurveTable`: `curve_uid` is *not*
  unique in `PricingMarketDataSetCurveBindingTable`, so the same curve can be
  selected by many roles, selectors, sides, and sets. To find every selector
  that uses a curve, query the binding table by `curve_uid`.
- An index participates in curve selection only as `selector_key` (its UID
  stored as a string) — there is no foreign key from a curve to an index.

The complete fixed-income pricing path, and how the pricing resolver walks it,
is documented in [Runtime Resolution](runtime_resolution.md). The market-data
set rows and concept bindings that supply DataNode locations to that path are
documented in [Market Data Sets](market_data_sets.md).

Registration order matters because pricing MetaTables reference core tables:

```text
AssetTypeTable
AssetTable
IndexTypeTable
IndexTable
IndexConventionDetailsTable
CurveTable
CurveBuildingDetailsTable
AssetCurrentPricingDetailsTable
PricingMarketDataSetTable
PricingMarketDataSetBindingTable
PricingMarketDataSetCurveBindingTable
DiscountCurvesStorage
IndexFixingsStorage
AssetPricingDetailsStorage
```

Use the pricing startup helper instead of manually passing table handles. It
uses direct backend lookup keyed by each SQLAlchemy table name, then binds the
returned `MetaTable` or `TimeIndexMetaTable` to the model class.

Run the relevant `msm` migrations before pricing runtime startup:

```python
from msm_pricing.bootstrap import attach_pricing_schemas

attach_pricing_schemas(seed_default_market_data_bindings=True)
```

For an end-to-end example that shows the explicit architecture, inspect
`examples/msm_pricing/bond_pricing_example/main.py`. It attaches the pricing
storage tables, disables automatic default seeding, creates
`PricingMarketDataSet(set_key="default")`, binds discount curves and
interest-rate fixings by storage table UID, publishes separate projection and
discount curve rows with both the pricing `curve` and source-owned JSON
`key_nodes` that storage compresses at rest, binds both roles for the floating
index, and then calls
`loaded_instrument.price(market_data_set=market_data_set.set_key)`.

## Rejected Patterns

Do not reintroduce these patterns:

- `benchmark_rate_index_name`, `floating_rate_index_name`, or
  `float_leg_index_name` in serialized instruments;
- `main_sequence_asset_id` in instrument payloads;
- curve rows stored as assets;
- Main Sequence Constant names as index or curve identity;
- a persisted `IndexSpec` registry with `curve_uid`;
- source-specific builder names inside hashed DataNode configuration.

The old `IndexSpec` shortcut bundled conventions and curve identity in memory.
The persistent contract is now explicit:
`IndexConventionDetailsTable` plus `CurveTable`, with QuantLib construction in
`msm_pricing.pricing_engine`.

## Related Concepts

- [Market Data Sets](market_data_sets.md)
- [Instruments](instruments.md)
- [Curves](curves.md)
- [Fixings](fixings.md)
- [Analytics](analytics.md)
- [Runtime Resolution](runtime_resolution.md)
- [Assets](../msm/assets/index.md)
- [Derivatives](../msm/derivatives/index.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
