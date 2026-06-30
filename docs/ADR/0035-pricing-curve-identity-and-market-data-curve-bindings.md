# 0035. Pricing Curve Identity And Market-Data Curve Bindings

## Status

Accepted - partially implemented

## Context

The current pricing curve model couples three different concerns:

1. curve identity;
2. curve construction rules;
3. valuation-context curve selection.

Today `CurveTable.index_uid` is required and points to
`IndexConventionDetailsTable.index_uid`. That means every curve row is forced to
belong to an index convention row.

That relationship is too strong. It makes sense for some rate curves, but it is
not a general curve identity rule. A discount curve, issuer curve, credit curve,
government curve, basis curve, or future non-rate curve can be a valid pricing
curve without being owned by one `IndexTable` row.

This decision is also about future curve variety. Pricing must be able to carry
multiple curve identities for the same broad economic family: bid, mid, and
offer curves; vendor-specific and scenario-specific curves; discount and
projection curves; spread and basis curves; and future volatility curves or
pricing surfaces. Those identities should not require synthetic index rows just
to satisfy a foreign key.

The existing DataNode storage already shows that curve observations are not
index-keyed:

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| CurveTable                  |<--------------------------------| DiscountCurvesStorage       |
|-----------------------------|        curve_identifier          |-----------------------------|
| uid                         |                                  | time_index                  |
| unique_identifier           |                                  | curve_identifier            |
| curve_type                  |                                  | curve                       |
+-----------------------------+                                  +-----------------------------+
```

`DiscountCurvesStorage.curve_identifier` points to
`CurveTable.unique_identifier`. Runtime data reads use that curve identifier.
They do not need `CurveTable.index_uid`.

`PricingMarketDataSetTable` and `PricingMarketDataSetBindingTable` already
solve a different problem: selecting which registered storage table should be
used for a pricing concept.

```text
PricingMarketDataSet("eod")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
  -> data_node_uid
  -> DiscountCurvesStorage
```

That only answers:

```text
Where do I read discount curve observations from?
```

It does not answer:

```text
Which curve identity inside that storage should be used for this valuation role?
```

A single discount-curve storage table can contain many `curve_identifier`
values. Pricing needs a second market-data-set layer that selects the curve
identity for a valuation role and selector.

The current implementation uses `CurveTable.index_uid` as an implicit selection
shortcut:

```text
index_uid + curve_type -> CurveTable row
```

That is the wrong ownership boundary. The relationship between an index and a
curve is valuation policy inside a market-data set. It is not intrinsic curve
identity.

## Decision

Split the model into four explicit responsibilities:

1. `CurveTable` owns curve registry identity.
2. `CurveBuildingDetailsTable` owns how a curve is built from observations.
3. `IndexConventionDetailsTable` owns QuantLib index and fixing
   reconstruction.
4. `PricingMarketDataSetCurveBindingTable` owns market-data-set curve
   selection.

### CurveTable

`CurveTable` should become a curve registry table. It should identify the curve
and hold high-level classification only.

Target shape:

```text
CurveTable
  uid
  unique_identifier
  display_name
  curve_type
  currency_code nullable
  quote_side nullable
  source nullable
  status
  metadata_json
```

`quote_side` is nullable because many production curves are mid or official
marks without bid/offer semantics. When present, it distinguishes curve
identities such as bid, mid, offer, or model.

`CurveTable.index_uid` should be treated as a legacy field. New code must not
use it as the primary curve relationship. The field can remain during a
migration window, but it should become nullable or be removed after resolvers
and bindings move to the new model.

`CurveTable.unique_identifier` remains the stable observation key used by curve
DataNodes through `curve_identifier`.

### CurveBuildingDetailsTable

Add `CurveBuildingDetailsTable` as the one-to-one build specification for a
curve.

Target shape:

```text
CurveBuildingDetailsTable
  curve_uid PK/FK -> CurveTable.uid
  builder_type
  quote_convention
  rate_unit
  day_counter_code
  calendar_code
  interpolation_method
  compounding
  compounding_frequency nullable
  extrapolation_policy
  bootstrap_method nullable
  builder_payload JSON nullable
  source nullable
  metadata_json
```

This table answers:

```text
How do I turn this curve's stored observations into a QuantLib term structure?
```

It is intentionally keyed by `curve_uid`, not by `index_uid`.

Examples of `builder_type`:

```text
zero_rate_curve
discount_factor_curve
par_swap_bootstrap
spread_curve
basis_curve
volatility_curve
volatility_surface
```

Examples of `quote_convention`:

```text
zero_rate
discount_factor
par_rate
spread
volatility
```

The initial implementation can support only the currently needed
`zero_rate_curve` path, but the schema should not encode the assumption that
all curves are index curves or that all future pricing market data is a rate
term structure.

### IndexConventionDetailsTable

Keep `IndexConventionDetailsTable`, but narrow its ownership:

```text
IndexConventionDetailsTable
  index_uid PK/FK -> IndexTable.uid
  index_family
  convention_dump
  serialization_format
  source
  metadata_json
```

This table answers:

```text
How do I rebuild a QuantLib index and hydrate fixings for this index?
```

It owns index mechanics such as index family, tenor, fixing calendar,
settlement days, business-day convention, end-of-month behavior, and fixing
identity.

It must not be the source of truth for curve construction rules.

### PricingMarketDataSetCurveBindingTable

Add a second market-data-set binding layer for selecting curve identity within
the storage source selected by `PricingMarketDataSetBindingTable`.

Preferred name:

```text
PricingMarketDataSetCurveBindingTable
```

Target shape:

```text
PricingMarketDataSetCurveBindingTable
  uid
  market_data_set_uid FK -> PricingMarketDataSetTable.uid
  binding_key
  role_key
  selector_type
  selector_key
  quote_side nullable
  curve_uid FK -> CurveTable.uid
  source nullable
  priority
  status
  metadata_json
```

The existing `PricingMarketDataSetBindingTable` remains the source binding:

```text
market_data_set_uid + concept_key -> data_node_uid
```

The new curve binding is the identity binding:

```text
market_data_set_uid + role_key + selector_type + selector_key -> curve_uid
```

`binding_key` is a deterministic normalized key used for uniqueness within a
market-data set. It should be derived by the public API instead of being
hand-authored by callers.

Example binding keys:

```text
discount:currency:USD:default
discount:currency:USD:bid
discount:currency:USD:offer
discount:currency:MXN:mid
projection:index:3d9e0e7a-0000-0000-0000-000000000001:mid
z_spread_base:index:3d9e0e7a-0000-0000-0000-000000000001:mid
volatility:asset:7d3f0c7f-0000-0000-0000-000000000002:offer
```

Recommended uniqueness:

```text
(market_data_set_uid, binding_key)
```

This avoids nullable uniqueness traps across index-specific, currency-specific,
and global bindings.

Examples:

```text
PricingMarketDataSet("eod")
  -> PricingMarketDataSetBinding("discount_curves")
  -> data_node_uid = DiscountCurvesStorage

PricingMarketDataSet("eod")
  -> PricingMarketDataSetCurveBinding(
       role_key="discount",
       selector_type="currency",
       selector_key="USD",
       quote_side="mid",
       curve_uid=USD_OIS_DISCOUNT
     )

PricingMarketDataSet("eod")
  -> PricingMarketDataSetCurveBinding(
       role_key="projection",
       selector_type="index",
       selector_key="<SOFR_3M_INDEX_UID>",
       quote_side="mid",
       curve_uid=USD_SOFR_3M_FORWARD
     )
```

Initial `role_key` values:

```text
discount
projection
forwarding
z_spread_base
```

Future `role_key` values may include:

```text
credit_spread
basis
volatility
issuer_discount
```

Initial `selector_type` values:

```text
currency
index
global
```

Future selector types such as `issuer`, `asset`, `curve_family`, or
`scenario_bucket` require a follow-up ADR unless the implementation keeps them
strictly internal and backward-compatible.

## Runtime Resolution

Pricing resolution should have two separate steps:

1. Resolve the storage source for a pricing concept.
2. Resolve the curve identity for a valuation role and selector.

Target flow for a currency discount curve:

```text
market_data_set_key
  -> PricingMarketDataSetTable
  -> PricingMarketDataSetBindingTable(concept_key="discount_curves")
  -> data_node_uid
  -> APIDataNode.build_from_table_uid(data_node_uid)

market_data_set_key
  -> PricingMarketDataSetCurveBindingTable(
       role_key="discount",
       selector_type="currency",
       selector_key="USD"
     )
  -> CurveTable.uid
  -> CurveTable.unique_identifier
  -> DiscountCurvesStorage rows keyed by curve_identifier
  -> CurveBuildingDetailsTable
  -> QuantLib YieldTermStructure
```

Target flow for a floating-rate index:

```text
index_uid
  -> IndexTable
  -> IndexConventionDetailsTable
  -> QuantLib index and fixings

market_data_set_key + role_key="projection" + selector_type="index" + index_uid
  -> PricingMarketDataSetCurveBindingTable
  -> CurveTable
  -> CurveBuildingDetailsTable
  -> forwarding curve handle
```

The resolver may still expose convenience functions, but their internals should
use the explicit model:

```text
resolve_market_data_source(...)
resolve_curve_binding(...)
resolve_curve_build_details(...)
build_curve_from_curve_row(...)
resolve_quantlib_index(...)
```

An explicit curve override remains valid for ad hoc valuation:

```text
curve_uid or curve_unique_identifier -> CurveTable -> CurveBuildingDetailsTable
```

Explicit overrides should not require an index relationship.

## Migration Plan

Implement this change in phases.

### Phase 1: Additive Schema

Add:

- `CurveBuildingDetailsTable`;
- `PricingMarketDataSetCurveBindingTable`;
- public row APIs for both tables;
- tests for API validation, uniqueness, and strict missing-row errors.

Do not remove `CurveTable.index_uid` in this phase.

### Phase 2: Backfill

Backfill `CurveBuildingDetailsTable` from existing curve rows and their current
borrowed index conventions.

For each existing `CurveTable` row:

1. copy high-level curve metadata from `CurveTable`;
2. derive current day counter, calendar, compounding, and interpolation values
   from existing fields and the referenced `IndexConventionDetailsTable` only
   as a migration source;
3. write a one-to-one `CurveBuildingDetailsTable` row.

Backfill `PricingMarketDataSetCurveBindingTable` from the existing
`Curve.index_uid + curve_type + source` selection behavior.

The backfill must be explicit about the market-data set it targets. For clean
initial data, it may target only the `default` set. For environments with
multiple market-data sets, the migration or follow-up repair script must verify
which curve identifiers exist in each set's bound discount-curve storage before
creating bindings.

### Phase 3: Resolver Cutover

Change runtime resolution so:

- curve observation source comes from `PricingMarketDataSetBindingTable`;
- curve identity comes from `PricingMarketDataSetCurveBindingTable`;
- curve construction comes from `CurveBuildingDetailsTable`;
- index construction and fixings come from `IndexConventionDetailsTable`.

Resolvers should fail loudly when:

- the market-data set has no source binding for the required concept;
- the market-data set has no curve binding for the requested role and selector;
- the selected curve has no building details;
- the selected storage source has no observations for the selected curve
  identifier and valuation date.

### Phase 4: Legacy Field Deprecation

Deprecate `CurveTable.index_uid` after resolver cutover.

The field may remain temporarily for old rows and diagnostics, but new public
APIs should stop requiring it. A later migration can make it nullable or remove
it once platform data has been backfilled and all runtime paths use explicit
curve bindings.

## Non-Goals

This ADR does not:

- implement the schema changes;
- generate Alembic revisions;
- remove `CurveTable.index_uid` immediately;
- define every future curve family;
- make `IndexTable` own curve identity;
- store curve observations directly on `CurveTable`;
- use `PricingMarketDataSetBindingTable.metadata_json` as an unstructured
  substitute for curve selection rows;
- add line-level market-data-set overrides to `ValuationPosition`;
- preserve silent fallback from missing curve bindings to legacy
  `Curve.index_uid` selection after migration.

## Consequences

Positive consequences:

- `CurveTable` becomes a true curve registry instead of an index-owned table.
- Curve construction details are explicit and curve-owned.
- Index conventions are limited to index reconstruction and fixings.
- Market-data sets choose both the storage source and the curve identity in
  separate, auditable rows.
- Currency discount curves, index projection curves, and future curve families
  no longer need fake index relationships.
- Missing or ambiguous curve selection can fail with actionable messages.

Negative consequences:

- Pricing gains two new MetaTables and public row APIs.
- Existing examples and tests that create curves must also create building
  details and curve bindings.
- Backfill requires careful validation when multiple market-data sets are
  active.
- Resolver APIs need a compatibility and deprecation period for callers that
  currently depend on `index_uid + curve_type` selection.

## Implementation Tasks

- [x] Add `CurveBuildingDetailsTable`.
- [x] Add `PricingMarketDataSetCurveBindingTable`.
- [x] Add public row APIs for curve building details and market-data-set curve
      bindings.
- [x] Add migration revisions for the additive tables.
- [ ] Add a backfill path from existing `Curve.index_uid` rows.
- [x] Update `Curve` create/upsert APIs so `index_uid` is no longer required for
      new curve identity.
- [x] Update pricing resolvers to use market-data-set curve bindings.
- [ ] Update fixed-rate bond, zero-coupon bond, floating-rate bond, and swap
      examples to create explicit curve bindings.
- [x] Update pricing docs and packaged skills.
- [ ] Add FastAPI route surfaces for curve building details and curve bindings
      if frontend workflows need direct CRUD over those rows.
- [x] Add tests for strict missing binding and explicit curve override
      behavior.
- [ ] Add tests for selected storage with missing observations.
- [ ] Deprecate and later remove or relax `CurveTable.index_uid`.

## Success Criteria

This ADR is complete only when:

- new curve rows can be created without a required index relationship;
- each persisted curve used for pricing has one `CurveBuildingDetailsTable` row;
- market-data-set curve bindings select curve identity for discount,
  projection, forwarding, and z-spread-base roles;
- pricing resolution no longer uses `CurveTable.index_uid` as the primary
  selector;
- index resolution still uses `IndexConventionDetailsTable` for QuantLib index
  construction and fixings;
- missing source bindings, curve bindings, build details, and observations fail
  loudly with role, selector, market-data-set, and curve identifiers in the
  error message;
- docs and examples describe the two market-data-set layers:
  source binding and curve-identity binding.
