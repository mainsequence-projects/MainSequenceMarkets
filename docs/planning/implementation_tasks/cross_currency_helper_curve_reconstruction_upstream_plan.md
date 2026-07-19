# Cross-Currency Helper Curve Reconstruction Upstream Implementation Plan

## Status

Planned.

This is an implementation-task plan, not an ADR. It defines how generic
cross-currency helper curve reconstruction should move into `msm_pricing`
without importing vendor, currency, country, or index-specific behavior from a
connector.

## Success Conditions

This phase is successful only when:

- ms-markets can build QuantLib FX swap and constant-notional
  cross-currency basis swap helpers from provider-neutral runtime specs.
- Cross-currency helper support extends the existing helper-reconstruction
  stack instead of creating a parallel curve builder, bootstrap path, or
  pricing runtime.
- Helper-style curve key nodes can reconstruct a runtime discount curve from
  FX swap and cross-currency basis swap helper provenance without importing
  connector code.
- FX spot is represented as context/provenance, not as a QuantLib
  `RateHelper`.
- Cross-currency reconstruction uses the existing helper-bootstrap
  architecture and extends it with a context-aware helper schema instead of a
  connector-owned schema token.
- Required runtime dependencies such as collateral curves and base/quote
  currency indexes are resolved through explicit generic resolver hooks.
- Calendar decoding supports generic joint calendars before cross-currency
  helpers depend on them.
- Quote normalization distinguishes FX forward points and basis spreads from
  ordinary rate/yield quotes.
- Reconstruction can return helper diagnostics such as maturity dates, pillar
  dates, and quote errors without forcing connectors to rebuild helpers
  locally.
- The ms-markets implementation contains no Valmer, USD/MXN, TIIE, SOFR,
  Mexico, CETES, M Bono, source-file, or source-row-pattern symbols in generic
  modules, generic tests, public examples, or public API names.

## Current Gap

QuantLib already exposes the primitives needed for this work:

- `ql.FxSwapRateHelper`;
- `ql.ConstNotionalCrossCurrencyBasisSwapRateHelper`;
- `ql.MtMCrossCurrencyBasisSwapRateHelper`.

The gap is in `msm_pricing`, not in QuantLib:

- `src/msm_pricing/pricing_engine/curves/helpers.py` currently owns generic
  deposit, OIS, interest-rate future, and bond helper specs/builders.
- `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py` currently parses
  only those helper families.
- `src/msm_pricing/pricing_engine/curves/adapters.py` accepts only
  `CurveBuildingDetails.builder_payload.helper_schema = "rate_helpers@v1"`.
- The current `rate_helpers@v1` contract assumes every key node is itself a
  helper node. Cross-currency reconstruction needs context nodes, especially FX
  spot.

The target is not a cross-currency special case. The target is a generic
helper-reconstruction extension that can support any currency pair and any
configured curve/index identity supplied by a caller or connector.

## Extension Alignment With Existing Helpers

Cross-currency helper support must be implemented as an extension of the
existing helper machinery already used for deposit, OIS, interest-rate future,
and bond helper reconstruction.

The implementation must preserve these existing extension points:

```text
helper key nodes
  -> helper_specs_from_key_nodes(...)
  -> RateHelperSpec
  -> build_rate_helper(...)
  -> build_rate_helpers(...)
  -> build_rate_helper_vector(...)
  -> reconstruct_curve_term_structure(...)
  -> reconstruct_curve_handle(...)
```

The new cross-currency modules are allowed only to keep the code organized.
They must not introduce a competing `cross_currency_curve` builder type, a
separate bootstrap function, a connector-specific helper schema, or a second
pricing-runtime resolution path.

Required integration points:

- `CrossCurrencyRateHelperSpec` becomes one branch of the existing
  `RateHelperSpec` union.
- `build_rate_helper(...)` delegates cross-currency specs to
  `cross_currency_helpers.py`, just as it delegates bond specs to
  `bond_helpers.py`.
- `helper_specs_from_key_nodes(...)` remains the public key-node-to-spec
  adapter. It may delegate cross-currency parsing to
  `cross_currency_key_nodes.py`, but callers should not need a separate
  cross-currency parser for the normal reconstruction path.
- `reconstruct_curve_handle_from_key_nodes(...)` and
  `reconstruct_curve_term_structure_from_key_nodes(...)` remain the handle and
  term-structure entry points.
- `CurveBuildingDetails.builder_type` remains `rate_helper_curve` or
  `rate_helper_bootstrap`; do not add `cross_currency_curve`.
- `CurveBuildingDetails.builder_payload.helper_schema` remains
  `rate_helpers@v1`. Context/provenance nodes are an additive part of that
  canonical helper schema.
- Do not bump helper schema names unless the project explicitly approves a
  breaking contract change.
- existing `rate_helpers@v1` behavior must remain unchanged for helper-only
  curves.

This mirrors the bond-helper extension pattern: new helper families get their
own focused modules, but they still plug into the same `RateHelperSpec`,
generic parser, adapter, vector assembly, bootstrap, observation export, and
scenario reconstruction flow.

## Donor Analysis

Donor source file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/rates_curves.py`

| Donor Behavior | Generic Meaning | Target Owner |
| --- | --- | --- |
| Manual construction of `ql.FxSwapRateHelper` from forward points, spot, tenor, calendar, collateral curve, and FX-base collateral flag. | Build a QuantLib FX swap helper from a typed runtime spec. | `msm_pricing.pricing_engine.curves.cross_currency_helpers`. |
| Manual construction of `ql.ConstNotionalCrossCurrencyBasisSwapRateHelper` from basis spread, base/quote indexes, collateral curve, calendar, flags, payment frequency, and payment lag. | Build a QuantLib constant-notional cross-currency basis swap helper from a typed runtime spec. | `msm_pricing.pricing_engine.curves.cross_currency_helpers`. |
| FX spot key node with `helper_type="fx_spot"`. | Context/provenance required by FX swap helpers, not a QuantLib helper. | `msm_pricing.pricing_engine.curves.cross_currency_key_nodes`. |
| FX swap key node with `helper_type="fx_swap_rate_helper"` and `quote_type="fx_forward_points"`. | Generic JSON-compatible key-node schema for FX swap helper reconstruction. | `msm_pricing.pricing_engine.curves.cross_currency_key_nodes`. |
| Constant-notional cross-currency basis key node with `helper_type="const_notional_cross_currency_basis_swap_rate_helper"` and `quote_type="basis_spread"`. | Generic JSON-compatible key-node schema for constant-notional cross-currency basis helper reconstruction. | `msm_pricing.pricing_engine.curves.cross_currency_key_nodes`. |
| Source-specific quote scaling and tenor normalization before helper creation. | Connector adapter responsibility. ms-markets receives explicit normalized quotes and tenors. | Connector code, not ms-markets. |
| Source-specific validator requiring a specific FX pair, index names, source row patterns, quote side, and point scale. | Source contract validation. | Connector code, not ms-markets. |
| Rebuilding helper diagnostics after bootstrap. | Generic reconstruction diagnostics from built QuantLib helpers. | `msm_pricing.pricing_engine.curves.reconstruction`. |

## What Must Stay In Connectors

Connectors remain responsible for:

- reading source files, URLs, API responses, or vendor tables;
- source row selection and row-family classification;
- source-specific tenor repair or normalization;
- source-specific quote scaling before a normalized generic key node is
  emitted;
- source identifiers, source quote-side defaults, and source diagnostic
  messages;
- validating that a source delivered the expected source-specific instruments;
- mapping source-local curve/index identifiers to canonical ms-markets
  curve/index identifiers.

ms-markets must not hardcode any source-specific curve identifiers or infer
indexes from vendor names.

## Target Schema Contract

### Canonical `rate_helpers@v1`

`rate_helpers@v1` remains the canonical helper reconstruction schema:

```text
key_nodes[*]
  -> helper node
  -> or context/provenance node

helper nodes -> QuantLib RateHelper specs
context nodes -> runtime context used by helper nodes
```

It supports existing deposit, OIS, interest-rate future, and bond helper
reconstruction, plus additive context/provenance nodes required by helper
families such as cross-currency helpers. The upstream adapter must not accept
connector-owned schema names such as `valmer_xccy_helpers@v1`.

`fx_spot` is the first required context node. It is stored in `key_nodes`
because it is construction provenance, but it must not be returned as a
`RateHelperSpec` and must not be counted as a bootstrap helper.

## Target File Locations

Create these files:

| File | Owns | Models / Functions |
| --- | --- | --- |
| `src/msm_pricing/pricing_engine/curves/cross_currency_helpers.py` | Runtime QuantLib cross-currency helper construction. No MetaTable, DataNode, connector, or source-row imports. | `FxSwapRateHelperSpec`, `ConstNotionalCrossCurrencyBasisSwapRateHelperSpec`, `CrossCurrencyRateHelperSpec`, `build_fx_swap_rate_helper(...)`, `build_const_notional_cross_currency_basis_swap_rate_helper(...)`, `build_cross_currency_rate_helper(...)`. |
| `src/msm_pricing/pricing_engine/curves/cross_currency_key_nodes.py` | JSON-compatible context and helper key-node validation plus conversion into runtime specs. | `FxSpotContextKeyNode`, `FxSwapRateHelperKeyNode`, `ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode`, `CrossCurrencyHelperKeyNode`, `parse_cross_currency_key_node(...)`, `cross_currency_helper_specs_from_key_nodes(...)`, `cross_currency_context_from_key_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curves/helper_resolution.py` | Generic runtime resolver protocol for helper reconstruction dependencies. Keeps resolver plumbing out of individual helper modules. | `RateHelperRuntimeResolver`, `StaticRateHelperRuntimeResolver`, `MissingRateHelperDependencyError`. |
| `tests/msm_pricing/pricing_engine/curves/test_cross_currency_helpers.py` | Primitive QuantLib helper construction tests. | Unit tests for FX swap and constant-notional cross-currency helper specs/builders using neutral identifiers. |
| `tests/msm_pricing/pricing_engine/curves/test_cross_currency_key_nodes.py` | Key-node parsing and context tests. | Tests for `fx_spot` context, FX swap helper nodes, basis helper nodes, missing context diagnostics, and unsupported helper types. |
| `tests/msm_pricing/pricing_engine/curves/test_cross_currency_reconstruction.py` | End-to-end generic reconstruction tests. | Build a neutral helper-key-node fixture, resolve dummy collateral/index dependencies, reconstruct a curve, and assert helper diagnostics. |

Update these existing files:

| File | Required Change |
| --- | --- |
| `src/msm_pricing/pricing_engine/curves/helpers.py` | Broaden `RateHelperSpec` and `build_rate_helper(...)` dispatch to include cross-currency specs by delegating to `cross_currency_helpers.py`. |
| `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py` | Keep `helper_specs_from_key_nodes(...)` as the public adapter. Dispatch cross-currency helper/context key nodes without bloating this file with all cross-currency models. Add parser support for context/provenance nodes under `rate_helpers@v1`. |
| `src/msm_pricing/pricing_engine/curves/quote_units.py` | Add explicit normalizers for `fx_forward_points` and `basis_spread`. Do not route FX forward points through `key_node_decimal_rate(...)`. |
| `src/msm_pricing/instruments/json_codec.py` | Add first-class `JointCalendar` decoding. |
| `src/msm_pricing/pricing_engine/curves/reconstruction.py` | Add a diagnostic reconstruction primitive that returns built helpers, helper specs, context nodes, and the term structure. Existing handle-only APIs should delegate to it where useful. |
| `src/msm_pricing/pricing_engine/curves/adapters.py` | Continue accepting only canonical `rate_helpers@v1`, with context/provenance support in the parser. Forward the generic helper runtime resolver into reconstruction and keep `rate_helper_curve` as the builder type. |
| `src/msm_pricing/pricing_engine/curves/__init__.py` | Re-export stable cross-currency specs, parser functions, and resolver types from the curve subpackage. |
| `src/msm_pricing/pricing_engine/resolvers.py` | Bridge runtime market-data-set curve/index resolution into the generic `RateHelperRuntimeResolver` when persisted curves are reconstructed during pricing. |
| `src/msm_pricing/scenarios/curves/engine.py` | Forward the same resolver context through scenario reconstruction so high-level scenario pricing can rebuild helper curves that depend on collateral curves and indexes. |
| `docs/knowledge/msm_pricing/curves.md` | Document helper schema versions, context nodes, resolver requirements, quote units, and cross-currency helper examples. |
| `docs/knowledge/msm_pricing/runtime_resolution.md` | Document how helper reconstruction gets collateral curves and indexes through pricing runtime resolution. |
| `docs/tutorial/05-pricing.md` | Add a short user workflow after implementation. |
| `examples/msm_pricing/curve_reconstruction.py` | Extend the offline curve reconstruction example with neutral cross-currency helper key nodes. |
| `CHANGELOG.md` | Add a user-facing change entry when implementation lands. |

## Model Contracts

### Runtime Specs

`FxSwapRateHelperSpec`

- Runtime dataclass in `cross_currency_helpers.py`.
- Required fields:
  - `forward_points: float`;
  - `spot: float`;
  - `tenor: str | ql.Period`;
  - `fixing_days: int`;
  - `calendar: ql.Calendar | str | Mapping[str, Any]`;
  - `convention: int | str`;
  - `end_of_month: bool`;
  - `is_fx_base_currency_collateral_currency: bool`;
  - `collateral_curve: ql.YieldTermStructureHandle`.
- Optional fields:
  - `trading_calendar: ql.Calendar | str | Mapping[str, Any] | None`.

`ConstNotionalCrossCurrencyBasisSwapRateHelperSpec`

- Runtime dataclass in `cross_currency_helpers.py`.
- Required fields:
  - `basis: float`;
  - `tenor: str | ql.Period`;
  - `fixing_days: int`;
  - `calendar: ql.Calendar | str | Mapping[str, Any]`;
  - `convention: int | str`;
  - `end_of_month: bool`;
  - `base_currency_index: ql.IborIndex | ql.OvernightIndex`;
  - `quote_currency_index: ql.IborIndex | ql.OvernightIndex`;
  - `collateral_curve: ql.YieldTermStructureHandle`;
  - `is_fx_base_currency_collateral_currency: bool`;
  - `is_basis_on_fx_base_currency_leg: bool`.
- Optional fields:
  - `payment_frequency: int | str`;
  - `payment_lag: int`.

`MtMCrossCurrencyBasisSwapRateHelperSpec`

- Not part of the first implementation.
- Add only when the library defines generic resettable-leg semantics and quote
  convention fields for mark-to-market cross-currency basis swaps.

### Key-Node Models

`FxSpotContextKeyNode`

- Pydantic model in `cross_currency_key_nodes.py`.
- Represents FX spot construction context, not a helper.
- Required fields:
  - `helper_type = "fx_spot"`;
  - `quote: float`;
  - `quote_type = "fx_spot"`;
  - `quote_unit: str`;
  - `fx_pair: str`;
  - `fx_base_currency: str`;
  - `fx_quote_currency: str`.
- Optional fields:
  - optional `source_reference` with `type="asset"` or `type="index"` and the
    canonical source identifier;
  - `maturity_date`;
  - `quote_side`;
  - `quote_source`;
  - `source_quote`;
  - `source_quote_unit`.

`FxSwapRateHelperKeyNode`

- Pydantic model in `cross_currency_key_nodes.py`.
- Required fields:
  - `helper_type = "fx_swap_rate_helper"`;
  - `quote: float`;
  - `quote_type = "fx_forward_points"`;
  - `quote_unit: str`;
  - `tenor: str`;
  - `fixing_days: int`;
  - `calendar_code: str | Mapping[str, Any]`;
  - `business_day_convention: int | str`;
  - `end_of_month: bool`;
  - `fx_pair: str`;
  - `fx_base_currency: str`;
  - `fx_quote_currency: str`;
  - `is_fx_base_currency_collateral_currency: bool`;
  - `collateral_curve: str`.
- Optional fields:
  - `spot: float`;
  - `spot_context_key: str`;
  - `trading_calendar_code: str | Mapping[str, Any] | None`;
  - `source_quote`;
  - `source_quote_unit`;
  - `point_scale`;
  - `market_forward`.

`ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode`

- Pydantic model in `cross_currency_key_nodes.py`.
- Required fields:
  - `helper_type = "const_notional_cross_currency_basis_swap_rate_helper"`;
  - `quote: float`;
  - `quote_type = "basis_spread"`;
  - `quote_unit: str`;
  - `tenor: str`;
  - `fixing_days: int`;
  - `calendar_code: str | Mapping[str, Any]`;
  - `business_day_convention: int | str`;
  - `end_of_month: bool`;
  - `base_currency_index: str`;
  - `quote_currency_index: str`;
  - `collateral_curve: str`;
  - `is_fx_base_currency_collateral_currency: bool`;
  - `is_basis_on_fx_base_currency_leg: bool`.
- Optional fields:
  - `payment_frequency: int | str`;
  - `payment_lag: int`;
  - `basis_sign`;
  - `basis_side`;
  - `notional_style`;
  - `source_quote`;
  - `source_quote_unit`.

### Resolver Protocol

`RateHelperRuntimeResolver`

- Protocol in `helper_resolution.py`.
- Required methods:

```python
from collections.abc import Mapping
from typing import Any, Protocol

import QuantLib as ql


class RateHelperRuntimeResolver(Protocol):
    def resolve_yield_curve(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.YieldTermStructureHandle: ...

    def resolve_index(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.IborIndex | ql.OvernightIndex: ...

    def resolve_overnight_index(
        self,
        identifier: str | None,
        node: Mapping[str, Any],
    ) -> ql.OvernightIndex: ...
```

The resolver receives identifiers from key nodes. It must not infer canonical
indexes from source strings. The pricing runtime adapter may implement this
protocol with existing curve/index binding and QuantLib index-resolution
machinery.

### Parse And Reconstruction Results

`ParsedRateHelperKeyNodes`

- Runtime dataclass in `helper_key_nodes.py` or `cross_currency_key_nodes.py`.
- Carries:
  - `helper_specs: tuple[RateHelperSpec, ...]`;
  - `context_nodes: tuple[Mapping[str, Any], ...]`;
  - `helper_nodes: tuple[Mapping[str, Any], ...]`.

`CurveReconstructionResult`

- Runtime dataclass in `reconstruction.py`.
- Carries:
  - `term_structure: ql.YieldTermStructure`;
  - `helpers: tuple[ql.RateHelper, ...]`;
  - `helper_specs: tuple[RateHelperSpec, ...]`;
  - `context_nodes: tuple[Mapping[str, Any], ...]`.
- This is not a persisted model. It exists so connectors, tests, and
  diagnostics can inspect pillar dates and `helper.quoteError()` after
  bootstrap without owning QuantLib helper construction.

## Quote Normalization Policy

FX forward points are not rates. They must not use
`key_node_decimal_rate(...)`.

Add explicit functions:

- `key_node_fx_forward_points(node: Mapping[str, Any]) -> float`;
- `normalize_fx_forward_points_value(value: object, unit: object, *, point_scale: object | None = None) -> float`;
- `key_node_basis_spread(node: Mapping[str, Any]) -> float`;
- `normalize_basis_spread_value(value: object, unit: object) -> float`.

Policy:

- `quote_type="fx_forward_points"` requires explicit units.
- If a node stores already-normalized forward points in `quote`, the normalizer
  returns that value unchanged only when the unit declares direct FX-pair
  points, for example a currency-pair unit string supplied by the producer.
- If a node asks the generic normalizer to consume raw source points, it must
  provide an explicit `point_scale`. The library must not infer point scale
  from currency pair, provider, or source filename.
- `quote_type="basis_spread"` accepts explicit decimal, percent, and basis
  point units. It is spread-like and rate-unit-like, but it gets its own
  normalizer so basis semantics are not confused with zero rates, par rates, or
  yields.

## Calendar Policy

Add first-class joint-calendar decoding to
`src/msm_pricing/instruments/json_codec.py`.

Canonical JSON:

```python
{
    "name": "JointCalendar",
    "calendars": [
        {"name": "TARGET"},
        {"name": "UnitedStates", "market": 0},
    ],
    "rule": "JoinHolidays",
}
```

Rules:

- Accepted `rule` values are `JoinHolidays` and `JoinBusinessDays`.
- If `rule` is omitted, use `JoinHolidays`.
- Nested calendar payloads must be decoded through the existing
  `calendar_from_json(...)` path.
- Invalid or empty `calendars` must raise a clear `ValueError`.

## Reconstruction Flow

The canonical flow should be:

```text
CurveBuildingDetails + DiscountCurvesNode observation
  -> validate helper_schema
  -> parse helper and context key nodes
  -> resolve collateral curves and indexes through RateHelperRuntimeResolver
  -> build runtime helper specs
  -> build QuantLib RateHelper objects
  -> bootstrap PiecewiseLogLinearDiscount
  -> return handle or CurveReconstructionResult
```

The handle-only APIs stay useful for pricing. The diagnostic result API is
needed for export, connector parity checks, and source adapters that want to
persist helper diagnostics.

## Scenario Engine Requirement

The high-level curve scenario engine must forward the same generic resolver
context used by base reconstruction. Otherwise low-level reconstruction would
support cross-currency helper curves, but `price_curve_scenario(...)` would
fail when it tries to rebuild shocked handles.

Required behavior:

- scenario reconstruction receives copied/shocked key nodes;
- context nodes are preserved unless a scenario explicitly targets them;
- collateral curve and index dependencies are resolved through
  `RateHelperRuntimeResolver`;
- scenario reconstruction must not mutate persisted key nodes or source
  observations;
- missing resolver dependencies produce explicit diagnostics.

## Implementation Tasks

1. Add `cross_currency_helpers.py` with typed runtime specs and QuantLib
   helper builders for FX swap and constant-notional cross-currency basis swap
   helpers.
2. Add `helper_resolution.py` with the generic resolver protocol and strict
   missing-dependency errors.
3. Add quote normalizers for FX forward points and basis spreads in
   `quote_units.py`.
4. Add `JointCalendar` JSON decoding in `json_codec.py`.
5. Add `cross_currency_key_nodes.py` with context-node parsing, helper-node
   parsing, and conversion to runtime specs.
6. Extend `helper_key_nodes.py` so `rate_helpers@v1` can parse mixed helper
   and context key nodes through the existing `helper_specs_from_key_nodes(...)`
   entry point while preserving existing helper-only behavior.
7. Extend `helpers.py` dispatch to include cross-currency specs without moving
   all cross-currency model definitions into that file.
8. Add `CurveReconstructionResult` and a diagnostic reconstruction API in
   `reconstruction.py`; keep the existing handle-only reconstruction APIs as
   the normal pricing entry points.
9. Extend `adapters.py` to keep accepting only `rate_helpers@v1` and forward
   `RateHelperRuntimeResolver`; do not add a cross-currency-specific builder
   type or schema name.
10. Extend pricing runtime resolver integration so persisted helper curves can
    resolve collateral curves and base/quote indexes through canonical
    bindings.
11. Extend the curve scenario engine to propagate the same resolver context.
12. Add focused tests for primitives, key-node parsing, calendar decoding,
    reconstruction, diagnostics, and scenario propagation.
13. Update canonical pricing documentation, tutorial, example, and changelog.

## Test Requirements

ms-markets tests must use neutral identifiers. Do not add a generic test
fixture named after a vendor, country, currency pair, or local source file.

Required focused tests:

- FX swap helper spec builds a QuantLib `FxSwapRateHelper`.
- Constant-notional cross-currency basis helper spec builds a QuantLib
  `ConstNotionalCrossCurrencyBasisSwapRateHelper`.
- `fx_spot` parses as context, not as a `RateHelperSpec`.
- FX swap helper nodes can use either inline `spot` or a matching spot context.
- Missing spot context raises a strict diagnostic.
- Missing collateral curve resolver raises a strict diagnostic.
- Missing base/quote index resolver raises a strict diagnostic.
- `JointCalendar` JSON decodes nested calendars and rule.
- FX forward points reject rate/yield normalization.
- Basis spread normalization accepts explicit decimal, percent, and basis
  point units.
- `rate_helpers@v1` remains compatible with existing helper-only key nodes.
- `rate_helpers@v1` also accepts mixed context and helper key nodes.
- cross-currency helper nodes reconstruct through the same
  `helper_specs_from_key_nodes(...)`, `build_rate_helper(...)`, and
  `reconstruct_curve_handle_from_key_nodes(...)` flow used by existing helper
  families.
- `MtMCrossCurrencyBasisSwapRateHelper` nodes are rejected until the library
  defines resettable-leg semantics.
- `valmer_xccy_helpers@v1` is rejected by ms-markets adapters.
- Reconstruction result exposes helper quote errors after bootstrap.
- Scenario reconstruction forwards resolver context and does not mutate source
  key nodes.

Connector parity tests should live in the connector after ms-markets support
lands. For example, a connector may verify the exact number of FX swaps and CCS
helpers, source tenor normalization, source point scaling, and source-specific
basis sign rules. Those are not generic ms-markets fixtures.

## Documentation Requirements

When implemented, update:

- `docs/knowledge/msm_pricing/curves.md` with:
  - `rate_helpers@v1` as the canonical helper schema;
  - FX spot context nodes;
  - FX swap helper key-node fields;
  - constant-notional cross-currency basis helper key-node fields;
  - resolver requirements;
  - quote unit rules;
  - diagnostic reconstruction results.
- `docs/knowledge/msm_pricing/runtime_resolution.md` with:
  - how collateral curves and base/quote indexes are resolved;
  - how this interacts with pricing market-data sets.
- `docs/tutorial/05-pricing.md` with:
  - a short helper-reconstruction workflow after the API is implemented.
- `examples/msm_pricing/curve_reconstruction.py` with:
  - a neutral cross-currency helper example.
- `CHANGELOG.md` with:
  - the new helper family and schema support.

## Connector Follow-Up After Upstream Support

After this is implemented in ms-markets, connectors can be refactored to:

- keep source parsing and source validation local;
- emit generic `rate_helpers@v1` key nodes;
- keep `DiscountCurvesStorage` unchanged;
- set `CurveBuildingDetails.builder_type = "rate_helper_curve"`;
- set `CurveBuildingDetails.builder_payload.helper_schema = "rate_helpers@v1"`;
- replace local QuantLib FX swap and CCS helper loops with
  `msm_pricing.pricing_engine.curves` reconstruction APIs;
- add connector-local parity tests against source fixtures.

No connector should require ms-markets to accept connector-specific schema
names or hardcoded source identifiers.
