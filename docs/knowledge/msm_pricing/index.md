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
- [Runtime Resolution](runtime_resolution.md): the persisted-graph resolution
  chain that `price()` follows, plus the end-to-end fixed-income user workflow.

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
  data_interface/  platform reads for curves and index fixings
  utils/           shared date and serialization utilities
```

`msm_pricing.models` must mean pricing-owned SQLAlchemy MetaTables. Runtime
pricing helpers belong in `msm_pricing.pricing_engine`.

## Persisted Graph

The pricing graph has four persistent layers:

1. core assets and indexes from `msm`;
2. pricing MetaTables that extend assets and indexes;
3. pricing DataNodes that publish curve and fixing observations;
4. serialized instrument payloads that reference backend UUIDs.

```text
AssetTable.uid
  -> AssetCurrentPricingDetailsTable.asset_uid
  -> Instrument payload with backend index UID fields

IndexTypeTable.index_type
  -> IndexTable.index_type
  -> IndexConventionDetailsTable.index_uid
  -> QuantLib index and fixings

PricingMarketDataSetTable
  -> PricingMarketDataSetBindingTable(concept_key="discount_curves")
  -> DiscountCurvesStorage

PricingMarketDataSetTable
  -> PricingMarketDataSetCurveBindingTable(role_key, selector_type, selector_key)
  -> CurveTable.uid
  -> CurveBuildingDetailsTable.curve_uid
  -> DiscountCurvesNode(curve_identifier)

IndexTable.unique_identifier
  -> FixingRatesNode(index_identifier, rate)
  -> QuantLib index hydration
```

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
interest-rate fixings by storage table UID, and then calls
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
- [Runtime Resolution](runtime_resolution.md)
- [Assets](../msm/assets/index.md)
- [Derivatives](../msm/derivatives/index.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
