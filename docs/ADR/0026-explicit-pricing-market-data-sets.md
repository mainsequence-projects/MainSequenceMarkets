# 0026. Explicit Pricing Market Data Sets

## Status

Accepted - implemented

Implemented in the ADR 0026 market-data set changes. Pricing runtime now uses
first-class market-data set rows and concept bindings keyed by backend DataNode
storage table UID.

## Context

The current pricing runtime resolves market data through
`PricingMarketDataBindingTable` rows keyed by:

```text
context_key
concept_key
```

Each row stores a `data_node_identifier` string. Bootstrap currently seeds the
built-in `default` bindings from attached storage classes:

```python
DiscountCurvesStorage.get_identifier()
IndexFixingsStorage.get_identifier()
```

That is valid for the current implementation because the identifier comes from
the registered backend `TimeIndexMetaTable`, not from a hand-rebuilt namespace
string. However, it is still not the desired long-term contract.

The current shape has three weaknesses:

1. `context_key` is not a first-class market-data set. It has no row identity,
   description, status, ownership, or validation surface.
2. Binding rows store a resolvable identifier string instead of the backend
   storage table UID that actually identifies the registered platform resource.
3. Pricing discovers missing or incomplete market-data sets late, while resolving
   a valuation, instead of validating a complete set up front.

Pricing needs a durable object that says: "this valuation set uses these
registered data sources for these concepts."

## Decision

Introduce explicit pricing market-data sets.

The target model is:

```text
PricingMarketDataSetTable
  uid
  set_key
  display_name
  description
  status
  metadata_json

PricingMarketDataSetBindingTable
  uid
  market_data_set_uid -> PricingMarketDataSetTable.uid
  concept_key
  data_node_uid
  storage_table_identifier
  source
  metadata_json
```

`PricingMarketDataSetTable.set_key` is the user-facing key, for example:

```text
default
eod
intraday
stress_2026_06
```

`PricingMarketDataSetBindingTable.data_node_uid` is the authoritative resource
pointer. It stores the backend MetaTable/TimeIndexMetaTable UID consumed by
`APIDataNode.build_from_table_uid(...)`. `storage_table_identifier` is optional
diagnostic cache only;
runtime resolution must not depend on it when a UID is available.

The binding uniqueness rule is:

```text
(market_data_set_uid, concept_key)
```

The initial built-in concepts are:

```text
discount_curves
interest_rate_index_fixings
```

Future pricing concepts can be added without changing the set table shape.

## Runtime Resolution

Pricing should resolve market data from a named set:

```text
market_data_set_key
  -> PricingMarketDataSetTable
  -> PricingMarketDataSetBindingTable rows
  -> data_node_uid
  -> APIDataNode.build_from_table_uid(...)
```

The SDK exposes `APIDataNode.build_from_table_uid(...)`, and pricing uses that
resolver for configured market-data bindings. Identifier-string resolution
through `APIDataNode.build_from_identifier(...)` is not part of the pricing
market-data binding path.

## Bootstrap

Pricing bootstrap should seed the default set after runtime attachment, because
only attached storage classes can expose backend UIDs.

The target flow is:

```text
msm_pricing.start_engine(...)
  -> attach pricing storage MetaTables
  -> read DiscountCurvesStorage.get_meta_table_uid()
  -> read IndexFixingsStorage.get_meta_table_uid()
  -> upsert PricingMarketDataSetTable(set_key="default")
  -> upsert required PricingMarketDataSetBindingTable rows
```

Bootstrap must not create tables. Table creation and schema changes remain
owned by the SDK Alembic provider:

```bash
mainsequence migrations upgrade --provider migrations:migration head
```

## Migration Plan

The implementation requires a normal Alembic revision that:

1. creates `PricingMarketDataSetTable`;
2. creates `PricingMarketDataSetBindingTable`;
3. adds foreign keys and uniqueness constraints;
4. removes `PricingMarketDataBindingTable`.

Existing binding-row migration is intentionally not implemented because the
assumed data set is clean and backward compatibility is not part of this
decision.

## Non-Goals

- Do not create a separate migration provider for pricing.
- Do not move pricing tables out of the shared `migrations:migration` provider.
- Do not hand-author SQL manifests or SDK operation manifests.
- Do not change `msm.start_engine(...)`; runtime remains attach-only.
- Do not claim this is implemented until the table models, API, migration,
  bootstrap, resolver, docs, and tests are all updated.

## Implementation Tasks

- [x] Add `PricingMarketDataSetTable`.
- [x] Add `PricingMarketDataSetBindingTable`.
- [x] Add public row APIs for market-data sets and set bindings.
- [x] Add or verify SDK support for UID-based DataNode resolution.
- [x] Update pricing data-interface resolution to load a set, validate required
      concept bindings, and resolve DataNodes by storage table UID.
- [x] Update pricing bootstrap to seed the default set from attached storage
      MetaTable UIDs.
- [x] Generate and review the Alembic revision under the active namespace
      version directory.
- [x] Remove `PricingMarketDataBindingTable` instead of adding a compatibility
      path for clean data.
- [x] Update pricing docs, tutorial, skills, and examples.
- [x] Add tests for set creation, binding uniqueness, bootstrap seeding,
      missing-concept errors, and UID-based resolver calls.

## Success Criteria

This ADR is complete only when:

- pricing has a first-class market-data set row;
- each set binding stores an authoritative storage table UID;
- pricing resolution uses UID-based DataNode lookup;
- the default set is seeded after runtime attachment;
- missing required concepts fail before valuation work starts;
- the Alembic migration is committed in the namespace-scoped revision graph;
- docs and examples no longer describe `context_key` plus
  `data_node_identifier` as the target architecture.
