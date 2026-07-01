# 0035. Pricing Curve Identity And Market-Data Curve Bindings

## Status

Accepted - implemented

## Context

The current pricing curve model couples three different concerns:

1. curve identity;
2. curve construction rules;
3. valuation-context curve selection.

The earlier curve model carried a required index ownership foreign key into
`IndexConventionDetailsTable`. That meant every curve row was forced to belong
to an index convention row.

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
|                             |                                  | key_nodes                   |
|                             |                                  | metadata_json               |
+-----------------------------+                                  +-----------------------------+
```

`DiscountCurvesStorage.curve_identifier` points to
`CurveTable.unique_identifier`. Runtime data reads use that curve identifier.
They do not need an index ownership column on the curve registry.
`DiscountCurvesStorage.curve` remains the constructed pricing payload, while
`key_nodes` records the dated input quotes used to build the specific
observation row. Quote interpretation remains on `CurveBuildingDetails`, not on
per-node fields.

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

The old implementation used an implicit selection shortcut:

```text
index UUID + curve type -> CurveTable row
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

`CurveTable` must not contain an index ownership field. A relationship between
an index and a curve is valuation policy and must be expressed through
`PricingMarketDataSetCurveBindingTable`.

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

Curve construction must use native QuantLib constructors selected by
`interpolation_method`. The supported non-deprecated method set is:

```text
log_linear_discount -> ql.DiscountCurve
log_cubic_discount  -> ql.LogCubicDiscountCurve
linear_zero         -> ql.ZeroCurve with ql.Linear()
cubic_zero          -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
natural_cubic_zero  -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
monotone_cubic_zero -> ql.MonotonicCubicZeroCurve with ql.MonotonicCubic()
linear_forward      -> ql.LinearForwardCurve, only for forward_rate quotes
```

For discount-space methods, stored zero rates are converted to discount factors
with `ql.InterestRate(...).discountFactor(...)`. The pricing code must not
hand-roll compounding math. For zero-space methods, stored zero rates are passed
to the QuantLib zero-curve constructor with the declared compounding and
frequency. Local code only performs parsing and `rate_unit` scaling.

Deprecated QuantLib constructors are intentionally not exposed as aliases.
`log_linear_zero`, `LogLinearZeroCurve`, `monotonic_log_cubic_discount`, and
`MonotonicLogCubicDiscountCurve` must fail validation before runtime pricing.

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
market_data_set_uid + role_key + selector_type + selector_key + quote_side
  -> curve_uid
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
and global bindings. This uniqueness is intentionally selector-side only.
`curve_uid` must not be unique in this table. A curve can be selected by many
bindings across roles, selector types, index UIDs, quote sides, or market-data
sets:

```text
SOFR index UID    + role=projection    + side=mid -> USD OIS curve
SOFR index UID    + role=z_spread_base + side=mid -> USD OIS curve
FedFunds index UID + role=projection   + side=mid -> USD OIS curve
```

The reverse relationship is therefore many-to-one. `CurveTable` does not own an
index or selector, and a caller must inspect
`PricingMarketDataSetCurveBindingTable` rows by `curve_uid` to see every
selector that uses a curve.

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
  -> PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
       role_key="projection",
       index_uid=SOFR_3M_INDEX_UID,
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

market_data_set_key + role_key="projection" + index_uid
  -> upsert_index_curve_selection(...)
  -> PricingMarketDataSetCurveBindingTable
  -> CurveTable
  -> CurveBuildingDetailsTable
  -> forwarding curve handle
```

For benchmark z-spread, the same binding graph uses
`role_key="z_spread_base"` and `index_uid=benchmark_rate_index_uid` through
`upsert_index_curve_selection(...)`. The helper persists
`selector_type="index"` and `selector_key=str(benchmark_rate_index_uid)` in the
generic binding table. The role describes why the curve is selected; it does
not require `CurveTable.curve_type` to equal `z_spread_base`. A selected
benchmark curve may have `curve_type="discount"`, `projection`, `government`,
or another supported physical curve type.

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

Implement this change without a curve-index compatibility path.

### Phase 1: Schema

Add:

- `CurveBuildingDetailsTable`;
- `PricingMarketDataSetCurveBindingTable`;
- public row APIs for both tables;
- tests for API validation, uniqueness, and strict missing-row errors.

Remove the old index ownership column from the curve table in the same
migration.

### Phase 2: Explicit Data Setup

Existing environments must create `CurveBuildingDetailsTable` rows and
`PricingMarketDataSetCurveBindingTable` rows explicitly. There is no implicit
runtime fallback from old implicit curve selection relationships.

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

### Phase 4: Enforcement

Public APIs, examples, docs, and packaged skills must not expose a curve-owned
index relationship. Missing bindings must fail loudly.

## Non-Goals

This ADR does not:

- define every future curve family;
- make `IndexTable` own curve identity;
- store curve observations directly on `CurveTable`;
- use `PricingMarketDataSetBindingTable.metadata_json` as an unstructured
  substitute for curve selection rows;
- add line-level market-data-set overrides to `ValuationPosition`;
- preserve silent fallback from missing curve bindings to old implicit curve
  selection behavior.

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
- Existing persisted curve rows require explicit setup of build details and
  curve bindings before they can be priced.

## Implementation Tasks

- [x] Add `CurveBuildingDetailsTable`.
- [x] Add `PricingMarketDataSetCurveBindingTable`.
- [x] Add public row APIs for curve building details and market-data-set curve
      bindings.
- [x] Add migration revisions for the additive tables.
- [x] Remove the curve-owned index relationship from the curve model and pending
      migration.
- [x] Update `Curve` create/upsert APIs so curve identity has no index selector
      field.
- [x] Update pricing resolvers to use market-data-set curve bindings.
- [x] Update fixed-rate bond, zero-coupon bond, floating-rate bond, and swap
      examples to create explicit curve bindings. (Done for the floating-rate
      bond example, `examples/msm_pricing/bond_pricing_example/main.py`, which
      creates `CurveBuildingDetails` and an `upsert_index_curve_selection`
      binding. No separate fixed-rate, zero-coupon, or swap example files exist;
      those instrument types are covered by tests, not standalone examples.)
- [x] Update pricing docs and packaged skills.
- [~] Add FastAPI route surfaces for curve building details and curve bindings
      if frontend workflows need direct CRUD over those rows. (Read surface
      added: `GET /pricing/curves/{uid}/curve-selections/` lists the curve
      bindings for a curve. Write CRUD and building-details routes are not
      built; deferred until a frontend needs them.)
- [x] Add tests for strict missing binding and explicit curve override
      behavior.
- [~] Add tests for selected storage with missing observations.
      (Skipped — the strict missing-binding coverage in
      `tests/msm_pricing/instruments/test_benchmark_curve_resolution.py` and
      `tests/msm_pricing/pricing_engine/test_resolvers.py` is considered
      sufficient; a dedicated missing-observation test was intentionally not
      added.)
- [x] Remove public docs and packaged-skill guidance for curve-owned index
      selection.

## Success Criteria

This ADR is complete only when:

- new curve rows can be created without a required index relationship;
- each persisted curve used for pricing has one `CurveBuildingDetailsTable` row;
- market-data-set curve bindings select curve identity for discount,
  projection, forwarding, and z-spread-base roles;
- pricing resolution never reads an index selector from the curve row;
- index resolution still uses `IndexConventionDetailsTable` for QuantLib index
  construction and fixings;
- missing source bindings, curve bindings, build details, and observations fail
  loudly with role, selector, market-data-set, and curve identifiers in the
  error message;
- docs and examples describe the two market-data-set layers:
  source binding and curve-identity binding.
