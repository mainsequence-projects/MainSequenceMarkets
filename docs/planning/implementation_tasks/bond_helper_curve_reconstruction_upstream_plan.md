# Bond Helper Curve Reconstruction Upstream Implementation Plan

## Status

Implemented for the ms-markets core curve reconstruction layer.

This is an implementation plan, not an ADR. It defines the next generic curve
reconstruction work that should move into ms-markets from connector code.

Implemented scope:

- generic zero-coupon and fixed-rate QuantLib bond helper specs/builders;
- generic bond-helper key-node parsing under `rate_helpers@v1`;
- reconstruction through the existing helper-vector bootstrap path;
- observation export through the existing curve observation exporter;
- no-op scenario reconstruction for price-quoted bond helper curves;
- strict diagnostic behavior for non-empty yield shocks until generic
  yield-to-price conversion exists.

Not implemented here:

- Valmer connector refactor and fixture parity checks;
- coupon schedule diagnostics;
- bond pricing payload factory.

## Scope

Item 1 from the Valmer donor analysis is the top-priority upstream phase:
generic bond-helper curve reconstruction.

Items 5 and 6 are intentionally not part of this implementation phase. They
need a Valmer-side design discussion before ms-markets accepts a stable public
contract:

- item 5: coupon schedule diagnostics;
- item 6: bond pricing payload factory.

## Success Conditions

The phase is successful only when:

- ms-markets can build zero-coupon and fixed-rate QuantLib bond helpers from
  provider-neutral specs;
- bond helper key nodes can reconstruct a runtime discount curve through the
  existing generic curve reconstruction path;
- bond-helper reconstruction uses the existing `rate_helpers@v1`
  `CurveBuildingDetails.builder_payload.helper_schema` contract instead of a
  separate source-specific builder type;
- observation export reuses the generic curve observation exporter;
- scenario pricing has an explicit, tested policy for price-quoted bond
  helpers versus yield shocks;
- Valmer code can become a source adapter that reads source rows, maps them to
  generic specs or key nodes, and calls ms-markets;
- ms-markets core contains no Valmer, CETES, M Bono, Mexico, MXN, TIIE, or
  source-file-specific symbols in public APIs, generic tests, or generic
  examples.

## Donor Analysis

Source file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/mexican_government_bond_curve.py`

| Donor Location | Generic Meaning | Target Owner |
| --- | --- | --- |
| `mexican_government_bond_curve.py:95` | Build a zero-coupon bond helper from a normalized row. | `msm_pricing.pricing_engine.curves.bond_helpers`. |
| `mexican_government_bond_curve.py:117` | Construct `ql.BondHelper`. | `msm_pricing.pricing_engine.curves.bond_helpers`. |
| `mexican_government_bond_curve.py:152` | Build a fixed-rate bond helper from a normalized row. | `msm_pricing.pricing_engine.curves.bond_helpers`. |
| `mexican_government_bond_curve.py:186` | Construct `ql.FixedRateBondHelper`. | `msm_pricing.pricing_engine.curves.bond_helpers`. |
| `mexican_government_bond_curve.py:238` | Collect mixed bootstrap instruments. | Existing `msm_pricing.pricing_engine.curves.helpers` vector path, extended for bond helpers. |
| `mexican_government_bond_curve.py:262` | Build a reconstructed curve frame from selected instruments. | Connector adapter plus ms-markets reconstruction and observation export. |
| `mexican_government_bond_curve.py:315` | Bootstrap a discount curve from helpers. | Existing `msm_pricing.pricing_engine.curves.reconstruction`. |
| `mexican_government_bond_curve.py:338` | Export zero-rate points from the reconstructed curve. | Existing `msm_pricing.pricing_engine.curves.observations`. |

The donor proves a real generic gap: ms-markets now owns OIS, overnight
deposit, and interest-rate future helper reconstruction, but it does not yet
own generic bond helper reconstruction. The donor should not be copied
directly because row filtering, source column parsing, instrument labels, and
vendor validations belong in Valmer.

## Architecture Decision For This Plan

Bond helpers should extend the existing generic helper reconstruction path.
They should not create a separate `bond_helper_curve` builder type.

QuantLib `BondHelper` and `FixedRateBondHelper` are `RateHelper` instances, so
the correct ms-markets architecture is:

```text
CurveBuildingDetails.builder_type = "rate_helper_curve"
CurveBuildingDetails.builder_payload.helper_schema = "rate_helpers@v1"
DiscountCurvesNode.key_nodes[*].helper_type = "zero_coupon_bond_helper"
DiscountCurvesNode.key_nodes[*].helper_type = "fixed_rate_bond_helper"
```

The persisted schema token is already meaningful because it lives in
`CurveBuildingDetails.builder_payload.helper_schema` and is validated by
`src/msm_pricing/pricing_engine/curves/adapters.py`. This phase extends the
allowed helper types under that schema; it does not introduce a new persistence
table or a new connector-owned schema token.

## Target File Locations

Create these files:

| File | Owns | Models / Functions |
| --- | --- | --- |
| `src/msm_pricing/pricing_engine/curves/bond_helpers.py` | Runtime QuantLib bond-helper construction. No DataNode, MetaTable, connector, or source-row imports. | `ZeroCouponBondHelperSpec`, `FixedRateBondHelperSpec`, `BondHelperSpec`, `build_zero_coupon_bond_helper(...)`, `build_fixed_rate_bond_helper(...)`, `build_bond_helper(...)`, `build_bond_helpers(...)`. |
| `src/msm_pricing/pricing_engine/curves/bond_helper_key_nodes.py` | JSON-compatible key-node validation and conversion into runtime bond helper specs. | `ZeroCouponBondHelperKeyNode`, `FixedRateBondHelperKeyNode`, `BondHelperKeyNode`, `parse_bond_helper_key_node(...)`, `bond_helper_specs_from_key_nodes(...)`, `key_nodes_contain_bond_helpers(...)`. |
| `tests/msm_pricing/pricing_engine/curves/test_bond_helpers.py` | Primitive bond helper construction tests. | Unit tests for zero-coupon and fixed-rate helper specs and QuantLib helper creation. |
| `tests/msm_pricing/pricing_engine/curves/test_bond_helper_reconstruction.py` | Reconstruction tests through the persisted key-node adapter. | Mixed helper parsing, curve reconstruction, observation export, and error behavior. |
| `examples/msm_pricing/curve_reconstruction.py` | Offline generic example. | Build generic rate and bond helper specs, reconstruct curves, export observation nodes. |

Update these existing files:

| File | Required Change |
| --- | --- |
| `src/msm_pricing/pricing_engine/curves/__init__.py` | Re-export stable bond-helper specs and parser functions from the curve subpackage. |
| `src/msm_pricing/pricing_engine/curves/helpers.py` | Broaden `RateHelperSpec` and `build_rate_helper(...)` dispatch to include bond helper specs, or delegate to `bond_helpers.py` without creating circular imports. |
| `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py` | Dispatch bond helper key nodes alongside OIS, deposit, and future helper key nodes. |
| `src/msm_pricing/pricing_engine/curves/adapters.py` | Keep `helper_schema="rate_helpers@v1"` and validate the new helper types through the generic parser. |
| `src/msm_pricing/pricing_engine/curves/reconstruction.py` | Reuse existing helper-vector and bootstrap functions; avoid adding bond-specific bootstrap functions. |
| `src/msm_pricing/pricing_engine/curves/observations.py` | Reuse existing zero/discount observation export; add only generic observation options if the bond use case proves a missing primitive. |
| `src/msm_pricing/scenarios/curves/key_node_bumps.py` | Add explicit behavior for bond-helper scenario inputs. Do not silently treat price quotes as rates. |
| `src/msm_pricing/scenarios/curves/engine.py` | Ensure scenario reconstruction can pass through mixed helper key nodes without source-specific hooks. |
| `docs/knowledge/msm_pricing/curves.md` | Canonical user documentation for bond-helper reconstruction, key-node fields, quote policy, and scenario limitations. |
| `docs/tutorial/05-pricing.md` | Add a short fixed-income curve reconstruction workflow after the API is implemented. |
| `CHANGELOG.md` | Add a public change entry when the implementation lands. |

## Model Contracts

`ZeroCouponBondHelperSpec`

- Runtime dataclass in `bond_helpers.py`.
- Holds QuantLib runtime primitives where appropriate.
- Required fields:
  - `quote: float`;
  - `maturity_date: date | datetime | str | ql.Date`.
- Optional fields:
  - `quote_type: Literal["clean_price", "dirty_price"]`;
  - `quote_unit: Literal["price", "price_per_face", "price_per_100"]`;
  - `settlement_days`;
  - `calendar`;
  - `face_value`;
  - `payment_convention`;
  - `redemption`;
  - `issue_date`;

`FixedRateBondHelperSpec`

- Runtime dataclass in `bond_helpers.py`.
- Required fields:
  - `quote: float`;
  - `coupon_rate: float`;
  - `issue_date: date | datetime | str | ql.Date`;
  - `maturity_date: date | datetime | str | ql.Date`.
- Optional fields:
  - `quote_type: Literal["clean_price", "dirty_price"]`;
  - `quote_unit: Literal["price", "price_per_face", "price_per_100"]`;
  - `settlement_days`;
  - `face_value`;
  - `calendar`;
  - `tenor`, `coupon_period_days`, `coupon_frequency`, `schedule`, or
    `schedule_dates`;
  - `day_counter`;
  - `payment_convention`;
  - `business_day_convention`;
  - `termination_business_day_convention`;
  - `redemption`;
  - `payment_calendar`;
  - `date_generation_rule`;
  - `end_of_month`;
  - `first_date`;
  - `next_to_last_date`;
  - ex-coupon fields.

`ZeroCouponBondHelperKeyNode`

- Pydantic model in `bond_helper_key_nodes.py`.
- JSON-compatible persisted representation of
  `ZeroCouponBondHelperSpec`.
- Required fields:
  - `helper_type = "zero_coupon_bond_helper"`;
  - normalized quote fields;
  - date fields as ISO strings;
  - convention fields as canonical ms-markets/QuantLib tokens.

`FixedRateBondHelperKeyNode`

- Pydantic model in `bond_helper_key_nodes.py`.
- JSON-compatible persisted representation of
  `FixedRateBondHelperSpec`.
- Required fields:
  - `helper_type = "fixed_rate_bond_helper"`;
  - normalized quote fields;
  - date fields as ISO strings;
  - coupon fields;
  - schedule generation fields or explicit schedule dates;
  - convention fields as canonical ms-markets/QuantLib tokens.

## Quote And Scenario Policy

Base reconstruction and scenario reconstruction need separate rules.

Base reconstruction:

- bond helpers may consume clean or dirty prices;
- adapters must normalize source prices into one of the generic quote units;
- source-specific price scales stay in connectors.

Scenario reconstruction:

- `CurveBumpSpec` currently bumps rate-like fields such as yield, rate, quote,
  and implied rate;
- price-quoted bond helpers must not be shocked as if the quote were a rate;
- if a scenario bump targets yield, ms-markets must convert the bumped yield
  back to a clean or dirty helper price using explicit bond conventions;
- if that conversion is not implemented in the first slice, bond-helper
  scenario yield shocks must fail with a strict diagnostic instead of producing
  misleading deltas.

This is the highest-risk part of the phase. A nonzero scenario delta is not
enough evidence unless the test proves the bump policy is financially coherent.

## Implementation Tasks

### 1. Primitive Bond Helper Builders

- Add `bond_helpers.py`.
- Implement zero-coupon and fixed-rate helper specs as typed dataclasses.
- Convert generic quote units into QuantLib quote handles.
- Build `ql.BondHelper` and `ql.FixedRateBondHelper`.
- Return QuantLib `RateHelper` objects so the existing helper-vector and
  reconstruction path can consume them.
- Keep every function provider-neutral and fully typed.
- Add docstrings that state the quote convention, runtime-object boundary, and
  lack of persistence dependency.

### 2. Bond Helper Key Nodes

- Add `bond_helper_key_nodes.py`.
- Define JSON-compatible Pydantic key-node models.
- Parse dates, calendars, day counters, business-day conventions, frequencies,
  and schedule generation tokens into runtime specs.
- Keep source identifier mapping out of the parser.
- Integrate parser dispatch into the existing generic helper key-node path.

### 3. Reconstruction Adapter Integration

- Keep `CurveBuildingDetails.builder_type="rate_helper_curve"`.
- Keep `CurveBuildingDetails.builder_payload.helper_schema="rate_helpers@v1"`.
- Extend validation to accept `zero_coupon_bond_helper` and
  `fixed_rate_bond_helper`.
- Reuse `build_rate_helper_vector(...)` and
  `reconstruct_curve_handle(...)`.
- Reuse `export_curve_observation_nodes(...)`.
- Do not add a bond-specific bootstrap function unless a QuantLib method
  requires a truly new primitive.

### 4. Scenario Integration

- Add strict handling in `scenarios.curves.key_node_bumps` for bond helper key
  nodes.
- Support no-op/base reconstruction first.
- Add yield-to-price conversion only with explicit conventions and tests.
- If yield-to-price conversion is deferred, raise a clear diagnostic for bond
  helper yield shocks.
- Prove scenario handles are rebuilt from copied key nodes and do not mutate
  persisted curve data.

### 5. Valmer Adapter Refactor

- Refactor Valmer to keep row selection, column parsing, source identifiers,
  source quote scaling, and vendor validations.
- Map selected source rows to generic bond helper key nodes.
- Call ms-markets reconstruction and observation export.
- Keep Valmer curve names and Valmer fixture parity tests outside ms-markets.
- Delete local Valmer bootstrap helpers only after parity is demonstrated.

### 6. Canonical Documentation

- Document the public workflow in `docs/knowledge/msm_pricing/curves.md`.
- Add the runnable example under `examples/msm_pricing/`.
- Add tutorial coverage in `docs/tutorial/05-pricing.md`.
- Add a changelog entry when the code lands.
- Keep this planning document wired through `mkdocs.yml`.

## Required Tests

- zero-coupon bond helper construction from a generic spec;
- fixed-rate bond helper construction from a generic spec;
- key-node parsing for both helper types;
- mixed helper reconstruction through `rate_helpers@v1`;
- observation export from the reconstructed curve;
- strict failure for unknown quote units or unsupported quote types;
- strict failure for scenario yield shocks if yield-to-price conversion is not
  implemented;
- nonzero scenario delta when yield-to-price conversion is implemented;
- no mutation of persisted key nodes during scenario reconstruction;
- Valmer parity test outside ms-markets before deleting connector-local helper
  code.

## What Stays In Valmer

Valmer should retain:

- source file loading;
- source row filtering;
- source column names and parsing;
- source-local identifiers and curve names;
- CETES and M Bono classification;
- source price scaling;
- source-specific validation messages;
- fixture parity tests proving the adapter maps source rows into generic
  ms-markets specs correctly.

## Item 5: Coupon Schedule Diagnostics

Status: defer for Valmer discussion.

Donor file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/vector_to_asset.py`

Relevant donor functions:

- `_count_future_coupons(...)`;
- `_flow_table(...)`;
- `_snap_first_future(...)`;
- `assert_schedule_matches_sheet_debug(...)`;
- `count_future_coupons(...)`.

Current ms-markets already owns the core schedule construction function:
`src/msm_pricing/pricing_engine/coupon_schedules.py::compute_coupon_schedule_force_match`.

Potential future ms-markets file:
`src/msm_pricing/pricing_engine/bond_diagnostics.py`.

Potential future models/functions:

- `CouponScheduleDiagnostic`;
- `coupon_flow_frame(...)`;
- `count_future_coupons(...)`;
- `diagnose_coupon_schedule(...)`;
- `assert_coupon_schedule_matches(...)`.

This should not be implemented in the bond-helper phase. The donor code is
still print-heavy and source-row-oriented. A reusable version must return
structured diagnostics, take provider-neutral inputs, and avoid embedding
Valmer sheet reconciliation semantics in ms-markets.

## Item 6: Bond Instrument Terms Factory

Status: implemented in ms-markets core. Valmer adapter switch-over remains
downstream work.

Donor file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/bond_terms.py`

Verified donor symbols:

- `BondInstrumentTerms`;
- `BondInstrumentType`;
- `build_instrument_from_bond_terms(...)`;
- `quantlib_evaluation_settings(...)`.

The donor module is a much cleaner upstream candidate than the old
`vector_to_asset.py` payload factory. Verified properties:

- no Valmer row parsing;
- no `SUBYACENTE_TO_INDEX_MAP`;
- no issuer/security-type classification;
- no reference-index bootstrap;
- no sheet schedule fixing or coupon reconciliation;
- no `valmer_connectors.settings` dependency;
- Valmer's `CoreBondPricingPayload` is now only a compatibility alias to the
  generic terms object;
- Valmer's `build_instrument_from_core_bond_pricing_payload(...)` delegates to
  `build_instrument_from_bond_terms(...)`;
- Valmer tests cover zero, fixed, and floating instrument construction,
  UID-field propagation, legacy alias compatibility, wrapper delegation,
  dependency cleanliness, and QuantLib settings restoration.

The ms-markets implementation does not preserve the old "pricing payload"
name. In this library, the resulting bond objects already are the instrument
payloads/terms. The upstream concept is named around instrument terms and
construction.

Target ms-markets files:

| File | Owns | Models / Functions |
| --- | --- | --- |
| `src/msm_pricing/instruments/bond_terms.py` | Provider-neutral construction of existing bond instrument models from typed terms. No asset lookup, provider row parsing, schedule diagnostics, reference-index bootstrap, or source classification. | `BondInstrumentTerms`, `BondInstrumentType`, `build_bond_instrument_from_terms(...)`, `quantlib_evaluation_settings(...)`. |
| `src/msm_pricing/instruments/__init__.py` | Public instrument import surface. | Lazy exports for `BondInstrumentTerms`, `BondInstrumentType`, and `build_bond_instrument_from_terms(...)`. |
| `tests/msm_pricing/instruments/test_bond_terms.py` | Unit coverage for generic construction and settings restoration. | Tests for zero, fixed, and floating bonds, optional benchmark UID behavior, required floating index UID, no legacy name fields, no provider imports, and QuantLib settings restoration. |
| `examples/msm_pricing/bond_terms.py` | Offline instrument-construction example. | Build zero, fixed, and floating bond instruments from generic terms using placeholder UUIDs and public imports. |
| `docs/knowledge/msm_pricing/instruments.md` | Canonical documentation for the terms-to-instrument workflow. | Explain when to use terms construction instead of provider adapters, and how it relates to persisted instrument serialization. |
| `docs/tutorial/05-pricing.md` | Tutorial workflow note. | Point users to the example after the API is implemented. |
| `CHANGELOG.md` | User-facing release note. | Add an entry when the implementation lands. |

Implemented upstream contract adjustments:

- `benchmark_rate_index_uid` must be optional for zero-coupon and fixed-rate
  bonds. Existing ms-markets bond models treat this field as optional
  benchmark analytics/mapping metadata; requiring it for every zero/fixed bond
  would make the generic helper more restrictive than the underlying
  instruments.
- `floating_rate_index_uid` must remain required for floating-rate bonds.
- For floating-rate bonds, `benchmark_rate_index_uid` may default to
  `floating_rate_index_uid` only if the caller does not provide an explicit
  benchmark UID. That default is a generic convenience, not a provider rule.
- The builder should return the existing `ZeroCouponBond`, `FixedRateBond`, or
  `FloatingRateBond` instrument model. It must not create a parallel
  instrument hierarchy.
- `quantlib_evaluation_settings(...)` lives in `bond_terms.py` as a local
  construction helper until another instrument workflow needs the same
  primitive.
- The terms model is a typed frozen dataclass with validation in the builder.
  It preserves QuantLib runtime object support and avoids provider-specific
  JSON assumptions.

Implementation status:

1. [x] Add `src/msm_pricing/instruments/bond_terms.py` with the adjusted terms
   contract and settings context manager.
2. [x] Add public lazy exports from `src/msm_pricing/instruments/__init__.py`.
3. [x] Add tests proving the builder constructs zero, fixed, and floating
   instruments with UID fields and no legacy `*_index_name` keys.
4. [x] Add tests proving QuantLib evaluation-date settings are restored after
   construction.
5. [x] Add tests proving the module has no Valmer/provider imports or source-map
   dependencies.
6. [ ] Update Valmer to import the ms-markets implementation and keep only row
   parsing, source classification, source index lookup, and compatibility
   aliases.
7. [x] Update canonical docs, tutorial, example, and changelog after
   implementation.

Do not upstream:

- `valmer_row_to_core_bond_pricing_payload(...)`;
- `SUBYACENTE_TO_INDEX_MAP`;
- source-specific reference-index lookup/bootstrap;
- issuer/security-type classification;
- sheet schedule fixing or coupon diagnostics;
- the legacy `CoreBondPricingPayload` name.
