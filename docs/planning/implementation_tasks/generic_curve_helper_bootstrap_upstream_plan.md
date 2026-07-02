# Generic Curve Helper Bootstrap Upstream Plan

This implementation plan analyzes generic curve-construction machinery
currently embedded in Valmer connector code and defines where it should move in
`msm_pricing`. The goal is not to copy Valmer functions blindly. The goal is to
promote reusable QuantLib helper construction, helper-based bootstrapping, and
curve export mechanics into ms-markets while leaving Valmer source parsing and
vendor policy in `valmer-connectors`.

## Success Conditions

- Generic QuantLib rate-helper construction is available from
  `msm_pricing.pricing_engine`, not from connector packages.
- Helper-style curve key nodes can rebuild runtime discount curves without
  importing `valmer_connectors`.
- `msm_pricing.scenarios.curves` can shock helper-style key nodes and delegate
  runtime curve reconstruction to the generic pricing-engine layer.
- Valmer connector code becomes an adapter: read Valmer files, classify source
  rows, map source quotes into generic helper specs or key nodes, then call
  ms-markets.
- No Valmer URL, file format, source suffix, source exception class, or
  Valmer-specific default quote side is imported into `msm_pricing`.

## Source Analysis

Source file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/rates_curves.py`

| Current Valmer Function | Generic Meaning | Target Owner |
| --- | --- | --- |
| `build_tiie_discount_curve_from_key_nodes(...)` | Rebuild a runtime discount curve from helper-style key nodes. | `msm_pricing.pricing_engine.curve_bootstrap`; scenarios should consume it, not own it. |
| `_build_tiie_ois_helpers_from_key_nodes(...)` | Select `helper_type="ois_rate_helper"` key nodes and convert quote/tenor/index/convention fields into OIS helper specs. | `msm_pricing.pricing_engine.curve_helpers` plus a generic key-node adapter. |
| `_build_tiie_ois_helpers(...)` | Build QuantLib `OISRateHelper` objects from typed quote/tenor/convention specs. | `msm_pricing.pricing_engine.curve_helpers`. |
| `_build_rate_helper_vector(...)` | Convert helper objects to `ql.RateHelperVector`, optionally adding a front overnight deposit helper. | `msm_pricing.pricing_engine.curve_helpers`. |
| `_bootstrap_tiie_discount_curve(...)` | Bootstrap `ql.PiecewiseLogLinearDiscount` from rate helpers. | `msm_pricing.pricing_engine.curve_bootstrap`. |
| `_bootstrap_usd_sofr_discount_curve(...)` | Same bootstrap mechanism with different helper inputs. | `msm_pricing.pricing_engine.curve_bootstrap`. |
| `_export_tiie_zero_rate_points(...)` | Export zero-rate points from a QuantLib curve at pillar and implied front dates. | `msm_pricing.pricing_engine.curve_bootstrap` or `curve_export`. |
| `_export_usd_sofr_zero_rate_points(...)` | Same zero-rate exporter with different implied front dates. | Same generic exporter. |
| `_build_overnight_deposit_helper(...)` | Optional front overnight deposit helper from rate/calendar/day-count settings. | `msm_pricing.pricing_engine.curve_helpers`. |
| `_ql_period_from_tenor(...)` | Strict tenor string to `ql.Period` conversion. | `msm_pricing.pricing_engine.curve_helpers` or `pricing_engine.tenors`. |
| `_key_node_decimal_rate(...)` | Normalize quote/yield percent versus decimal. | Reuse/promote existing `msm_pricing.scenarios.curves.key_node_bumps.key_node_decimal_rate(...)`; do not duplicate. |

Additional generic candidates observed around the listed code:

- `_build_sofr_ois_helper(...)` is the USD analogue of generic OIS helper
  construction and should share the same OIS helper builder.
- `_build_sofr_future_helper(...)` builds a QuantLib `SofrFutureRateHelper`.
  It is generic enough for a SOFR/futures helper spec, but it should be a later
  stage because futures helper fields are not the same contract as OIS helper
  key nodes.
- `_build_usd_sofr_rate_helper_vector(...)` is the same vector assembly as the
  TIIE vector without the optional deposit helper.

## What Must Stay In Valmer

- CSV reading, request URLs, source filenames, source suffix classification,
  and source row selection.
- Valmer-specific error classes and source diagnostics.
- Mapping Valmer source identifiers such as `Swap.13M...` into generic tenor
  and helper specs.
- Valmer default source quote side and source quote unit assumptions.
- Any vendor-specific fallback or repair rule needed to interpret Valmer input
  rows before they become generic key nodes.

## Target Architecture

### Pricing Engine Layer

Create generic helper modules under `src/msm_pricing/pricing_engine/`:

- `curve_helpers.py`
  - `ql_period_from_tenor(tenor: str) -> ql.Period`
  - `OvernightDepositHelperSpec`
  - `OISRateHelperSpec`
  - `SofrFutureRateHelperSpec` only when futures are implemented
  - `build_overnight_deposit_helper(spec: OvernightDepositHelperSpec) -> ql.RateHelper`
  - `build_ois_rate_helper(spec: OISRateHelperSpec) -> ql.RateHelper`
  - `build_rate_helper_vector(helpers: Sequence[ql.RateHelper], *, front_helper: ql.RateHelper | None = None) -> ql.RateHelperVector`

- `curve_bootstrap.py`
  - `bootstrap_piecewise_discount_curve(...) -> ql.YieldTermStructureHandle`
  - `export_zero_rate_points(...) -> dict[int, float]`
  - `build_discount_curve_from_helper_key_nodes(...) -> ql.YieldTermStructureHandle`

These modules should be exported lazily from
`src/msm_pricing/pricing_engine/__init__.py` after implementation.

### Curve Build Details

Do not overload the existing node-based `interpolation_method` path. Current
`build_curve_from_curve_observation(...)` builds from already-materialized curve
nodes. Helper-style curves are different: they bootstrap from market helpers.

Use existing `CurveBuildingDetails.bootstrap_method` and `builder_payload` for
helper bootstrapping:

```python
CurveBuildingDetails(
    builder_type="rate_helper_bootstrap",
    quote_convention="helper_quote",
    rate_unit="decimal",
    interpolation_method="log_linear_discount",
    bootstrap_method="piecewise_log_linear_discount",
    builder_payload={
        "helper_schema": "ois_rate_helper@v1",
        "output_quote_convention": "zero_rate",
        "output_rate_unit": "decimal",
        "front_deposit_helper": {"enabled": True, "tenor": "1D"},
    },
)
```

The exact token names should be finalized during implementation, but the
contract should preserve this split:

- `builder_type` says whether the curve is node-built or helper-bootstrapped.
- `bootstrap_method` says which QuantLib bootstrap constructor is used.
- `builder_payload` carries helper-specific defaults and output conventions.
- The published `curve` column remains normalized exported curve points for
  storage/API use.
- `key_nodes` carries source helper provenance sufficient to rebuild runtime
  helpers.

### Scenario Layer

`msm_pricing.scenarios.curves` should stay responsible for:

- scenario models;
- bump specifications;
- copying and bumping key nodes;
- base/scenario pricing orchestration;
- diagnostics and strict preflight.

It should not own OIS, SOFR, or helper bootstrap construction. When a shocked
curve has helper-style key nodes, `build_scenario_curve_handle(...)` should
delegate to `msm_pricing.pricing_engine.curve_bootstrap` after applying shocks.

This corrects the initial table mapping: `build_tiie_discount_curve_from_key_nodes(...)`
is a scenario consumer use case, but its generic owner is the pricing engine.

### DataNode And Key-Node Layer

The existing `CurveKeyNode` helper already allows source-specific extension
fields. Do not make helper-key-node fields mandatory for all curves. Instead,
document and optionally validate helper-style fields when a producer chooses
helper bootstrapping:

- `helper_type`
- `tenor`
- `quote`, `quote_type`, `quote_unit`
- `floating_index` or a structured index convention reference
- `fixed_payment_frequency`
- optional `settlement_days`, `payment_lag`, `payment_calendar`,
  `payment_frequency`, `rate_averaging`, `pillar`, and source quote fields

Generic rate normalization should reuse the current key-node rate machinery.
If that helper is needed outside scenarios, promote it to a pricing-engine
key-node utility and have `scenarios.curves.key_node_bumps` import from there.

## Implementation Stages

### Stage 1: Tenor And Rate Helper Primitives

Files to create:

- `src/msm_pricing/pricing_engine/curve_helpers.py`
- `tests/msm_pricing/pricing_engine/test_curve_helpers.py`

Tasks:

- [ ] Add strict `ql_period_from_tenor(...)` supporting `D`, `W`, `M`, and `Y`.
- [ ] Add typed helper specs for OIS and optional overnight deposit helpers.
- [ ] Add `build_ois_rate_helper(...)` with explicit settlement days,
  payment calendar, payment frequency, day counter, business-day convention,
  rate averaging, telescopic value dates, and index inputs.
- [ ] Add `build_overnight_deposit_helper(...)` without hard-coded Mexico
  calendar defaults.
- [ ] Add `build_rate_helper_vector(...)`.
- [ ] Add tests proving no Valmer imports, strict tenor parsing, decimal/percent
  quote handling, helper vector ordering, and explicit front helper behavior.

### Stage 2: Helper-Key-Node Adapter

Files to create or update:

- `src/msm_pricing/pricing_engine/curve_helper_key_nodes.py`
- `tests/msm_pricing/pricing_engine/test_curve_helper_key_nodes.py`
- `docs/knowledge/msm_pricing/curves.md`

Tasks:

- [ ] Convert helper-style key-node dictionaries into typed helper specs.
- [ ] Reuse existing rate normalization instead of duplicating
  `_key_node_decimal_rate(...)`.
- [ ] Require explicit units; do not infer percent versus decimal from source.
- [ ] Keep connector-specific source repair outside this adapter.
- [ ] Support `helper_type="ois_rate_helper"` and
  `"overnight_indexed_swap_helper"` first.
- [ ] Defer SOFR futures helper key nodes to a separate stage unless the
  implementation can define a clean generic futures spec.

### Stage 3: Generic Helper-Based Bootstrap

Files to create or update:

- `src/msm_pricing/pricing_engine/curve_bootstrap.py`
- `src/msm_pricing/pricing_engine/__init__.py`
- `src/msm_pricing/pricing_engine/resolvers.py`
- `tests/msm_pricing/pricing_engine/test_curve_bootstrap.py`

Tasks:

- [ ] Add `bootstrap_piecewise_discount_curve(...)` for
  `piecewise_log_linear_discount`.
- [ ] Preserve and restore `ql.Settings.instance().evaluationDate` around
  bootstrap calls.
- [ ] Return `ql.YieldTermStructureHandle` with extrapolation controlled by
  `CurveBuildingDetails.extrapolation_policy`.
- [ ] Add `export_zero_rate_points(...)` with configurable implied front days,
  day counter, compounding, and frequency.
- [ ] Add `build_discount_curve_from_helper_key_nodes(...)` as the generic
  replacement for `build_tiie_discount_curve_from_key_nodes(...)`.
- [ ] Extend resolver dispatch so `builder_type="rate_helper_bootstrap"` uses
  the helper bootstrap path and existing node-based curves remain unchanged.

### Stage 4: Scenario Integration

Files to update:

- `src/msm_pricing/scenarios/curves/engine.py`
- `tests/msm_pricing/scenarios/curves/test_curve_scenarios.py`
- `tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py`

Tasks:

- [ ] Keep scenario shock application in `scenarios.curves`.
- [ ] When runtime build details indicate helper bootstrapping, bump copied
  helper key nodes and delegate reconstruction to
  `pricing_engine.curve_bootstrap`.
- [ ] Preserve existing node-based scenario behavior.
- [ ] Add strict diagnostics for missing helper fields, unsupported helper
  types, unsupported units, and missing scenario handles.
- [ ] Prove scenario curve handles do not mutate persisted observations,
  submitted key nodes, prepared contexts, or submitted instruments.

### Stage 5: Connector Migration

External repository target:

- `/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be`

Tasks:

- [ ] Replace Valmer-local OIS helper construction with
  `msm_pricing.pricing_engine.curve_helpers`.
- [ ] Replace Valmer-local helper bootstrap and zero-rate export with
  `msm_pricing.pricing_engine.curve_bootstrap`.
- [ ] Keep Valmer file parsing and source row classification local.
- [ ] Preserve connector-owned tests for Valmer-specific row mapping.
- [ ] Add compatibility wrappers only where downstream imports require them,
  and mark those wrappers as temporary.

## Validation Requirements

- Focused pricing-engine tests for helper specs, helper vectors, bootstrap, and
  zero-rate export.
- Focused scenario tests proving helper-style shocked curves rebuild through the
  generic pricing-engine path.
- Valmer connector migration tests proving the same curve points are produced
  before and after the adapter cutover within a documented tolerance.
- `ruff check` and `ruff format` on touched files.
- `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site` after
  documentation changes.

## Explicit Non-Goals

- Do not move Valmer CSV readers or HTTP fetchers into ms-markets.
- Do not add Valmer-specific index identifiers, source suffixes, or quote-side
  defaults to ms-markets.
- Do not make helper-style key-node fields required for all `DiscountCurvesNode`
  publishers.
- Do not replace the existing node-based `build_curve_from_curve_observation(...)`
  path; helper bootstrapping is an additional builder path.
- Do not implement futures helpers in the first stage unless the generic
  contract is clean and tested independently from Valmer source parsing.
