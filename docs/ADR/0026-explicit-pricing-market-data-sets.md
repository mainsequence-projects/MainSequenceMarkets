# 0026. Explicit Pricing Market Data Sets

## Status

Proposed

This ADR is not implemented. It records the intended replacement for the current
pricing market-data binding shape.

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
  storage_table_uid
  storage_table_identifier
  metadata_json
```

`PricingMarketDataSetTable.set_key` is the user-facing key, for example:

```text
default
eod
intraday
stress_2026_06
```

`PricingMarketDataSetBindingTable.storage_table_uid` is the authoritative
resource pointer. `storage_table_identifier` is optional diagnostic cache only;
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
  -> storage_table_uid
  -> APIDataNode.build_from_table_uid(...)
```

If the SDK does not expose `APIDataNode.build_from_table_uid(...)` or an
equivalent UID-based DataNode resolver, this ADR requires an SDK addition before
implementation can be completed.

Identifier-string resolution through `APIDataNode.build_from_identifier(...)`
is allowed only as a transitional compatibility path when migrating existing
binding rows that do not yet have a storage table UID.

## Bootstrap

Pricing bootstrap should seed the default set after runtime attachment, because
only attached storage classes can expose backend UIDs.

The target flow is:

```text
msm_pricing.start_engine(...)
  -> attach pricing storage MetaTables
  -> read DiscountCurvesStorage.get_meta_table().uid
  -> read IndexFixingsStorage.get_meta_table().uid
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
4. optionally migrates existing `PricingMarketDataBindingTable` rows when the
   stored identifier can be resolved to a registered storage table UID;
5. keeps or removes the old binding table according to the final compatibility
   decision made during implementation.

Because the current binding rows store identifiers, existing rows cannot be
blindly converted without resolving those identifiers through the platform.
That adoption step must be explicit and testable.

## Non-Goals

- Do not create a separate migration provider for pricing.
- Do not move pricing tables out of the shared `migrations:migration` provider.
- Do not hand-author SQL manifests or SDK operation manifests.
- Do not change `msm.start_engine(...)`; runtime remains attach-only.
- Do not claim this is implemented until the table models, API, migration,
  bootstrap, resolver, docs, and tests are all updated.

## Implementation Tasks

- [ ] Add `PricingMarketDataSetTable`.
- [ ] Add `PricingMarketDataSetBindingTable`.
- [ ] Add public row APIs for market-data sets and set bindings.
- [ ] Add or verify SDK support for UID-based DataNode resolution.
- [ ] Update pricing data-interface resolution to load a set, validate required
      concept bindings, and resolve DataNodes by storage table UID.
- [ ] Update pricing bootstrap to seed the default set from attached storage
      MetaTable UIDs.
- [ ] Generate and review the Alembic revision under the active namespace
      version directory.
- [ ] Decide and implement the compatibility path for existing
      `PricingMarketDataBindingTable` rows.
- [ ] Update pricing docs, tutorial, and examples.
- [ ] Add tests for set creation, binding uniqueness, bootstrap seeding,
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
