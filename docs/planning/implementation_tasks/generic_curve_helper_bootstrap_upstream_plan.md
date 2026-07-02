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

## Naming And Dependency Guardrails

Donor function names are evidence, not target APIs. The ms-markets library must
not introduce source-, vendor-, currency-, or index-specific names for this
machinery.

Forbidden in new `msm_pricing` public APIs, private helper names, module names,
test fixture names, and generic examples:

- vendor names;
- local source filenames or source suffix names;
- country/currency defaults embedded in function names;
- index-family instances embedded in generic names.

Acceptable target names describe the generic financial mechanism:

- `curve_helpers.py`
- `curve_helper_key_nodes.py`
- `curve_bootstrap.py`
- `OISRateHelperSpec`
- `InterestRateFutureHelperSpec`
- `OvernightDepositHelperSpec`
- `build_discount_curve_from_helper_key_nodes(...)`
- `bootstrap_piecewise_discount_curve(...)`
- `export_zero_rate_points(...)`

Source-specific donor function names should not be repeated as concepts in this
plan. Use donor file/line references and generic behavior descriptions instead.
They must not be copied into ms-markets symbols.

## Source Analysis

Source file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/rates_curves.py`

| Donor Location | Generic Meaning | Target Owner |
| --- | --- | --- |
| `rates_curves.py:303` | Rebuild a runtime discount curve from helper-style key nodes. | `msm_pricing.pricing_engine.curve_bootstrap`; scenarios should consume it, not own it. |
| `rates_curves.py:611` | Select `helper_type="ois_rate_helper"` key nodes and convert quote/tenor/index/convention fields into OIS helper specs. | `msm_pricing.pricing_engine.curve_helpers` plus a generic key-node adapter. |
| `rates_curves.py:581` | Build QuantLib `OISRateHelper` objects from typed quote/tenor/convention specs. | `msm_pricing.pricing_engine.curve_helpers`. |
| `rates_curves.py:644` | Convert helper objects to `ql.RateHelperVector`, optionally adding a front overnight deposit helper. | `msm_pricing.pricing_engine.curve_helpers`. |
| `rates_curves.py:754` | Bootstrap `ql.PiecewiseLogLinearDiscount` from rate helpers. | `msm_pricing.pricing_engine.curve_bootstrap`. |
| `rates_curves.py:770` | Same bootstrap mechanism with different helper inputs. | `msm_pricing.pricing_engine.curve_bootstrap`. |
| `rates_curves.py:782` | Export zero-rate points from a QuantLib curve at pillar and implied front dates. | `msm_pricing.pricing_engine.curve_bootstrap` or `curve_export`. |
| `rates_curves.py:810` | Same zero-rate exporter with different implied front dates. | Same generic exporter. |
| `rates_curves.py:741` | Optional front overnight deposit helper from rate/calendar/day-count settings. | `msm_pricing.pricing_engine.curve_helpers`. |
| `rates_curves.py:927` | Strict tenor string to `ql.Period` conversion. | `msm_pricing.pricing_engine.curve_helpers` or `pricing_engine.tenors`. |
| `rates_curves.py:967` | Normalize quote/yield percent versus decimal. | Reuse/promote existing `msm_pricing.scenarios.curves.key_node_bumps.key_node_decimal_rate(...)`; do not duplicate. |

Additional generic candidates observed around the listed code:

- The source-specific OIS helper wrapper at `rates_curves.py:704` should share
  the same generic OIS helper builder.
- The source-specific futures helper wrapper at `rates_curves.py:690` should
  become an interest-rate futures helper spec only in a later stage, because
  futures helper fields are not the same contract as OIS helper key nodes.
- The source-specific helper-vector assembly at `rates_curves.py:729` is the
  same generic vector assembly without the optional deposit helper.

## What Must Stay In Valmer

- CSV reading, request URLs, source filenames, source suffix classification,
  and source row selection.
- Valmer-specific error classes and source diagnostics.
- Mapping source-local instrument identifiers into generic tenor and helper
  specs.
- Valmer default source quote side and source quote unit assumptions.
- Any vendor-specific fallback or repair rule needed to interpret Valmer input
  rows before they become generic key nodes.

## Target Architecture

### Concrete File And Model Placement

Create these new files in ms-markets:

| File | Owns | Models / Functions |
| --- | --- | --- |
| `src/msm_pricing/pricing_engine/curve_helpers.py` | Generic QuantLib rate-helper construction. Runtime-only, no persistence and no connector imports. | Runtime dataclasses: `OISRateHelperSpec`, `OvernightDepositHelperSpec`, deferred `InterestRateFutureHelperSpec`. Functions: `ql_period_from_tenor(...)`, `build_ois_rate_helper(...)`, `build_overnight_deposit_helper(...)`, `build_rate_helper_vector(...)`. |
| `src/msm_pricing/pricing_engine/curve_helper_key_nodes.py` | Convert generic helper-style `key_nodes` dictionaries into runtime helper specs. No source repair or vendor defaults. | Pydantic models: `OISRateHelperKeyNode`, deferred `InterestRateFutureHelperKeyNode`. Functions: `parse_ois_helper_key_node(...)`, `ois_helper_specs_from_key_nodes(...)`, `helper_specs_from_key_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curve_bootstrap.py` | Generic helper-based curve bootstrapping and curve-point export. | Pydantic model: `CurveHelperBootstrapConfig`. Functions: `bootstrap_piecewise_discount_curve(...)`, `export_zero_rate_points(...)`, `build_discount_curve_from_helper_key_nodes(...)`. |
| `tests/msm_pricing/pricing_engine/test_curve_helpers.py` | Unit coverage for helper specs and QuantLib helper construction. | Tests for tenor parsing, OIS helper construction, deposit helper construction, helper vector order, and no connector imports. |
| `tests/msm_pricing/pricing_engine/test_curve_helper_key_nodes.py` | Unit coverage for helper-key-node parsing. | Tests for required generic fields, unit normalization, unsupported helper types, and absence of source-specific defaults. |
| `tests/msm_pricing/pricing_engine/test_curve_bootstrap.py` | Unit coverage for helper-based bootstrap and zero-rate export. | Tests for bootstrap settings restoration, extrapolation policy, output points, and builder payload parsing. |

Update these existing files:

| File | Change |
| --- | --- |
| `src/msm_pricing/pricing_engine/__init__.py` | Lazily export the new generic helper and bootstrap functions after implementation. |
| `src/msm_pricing/pricing_engine/resolvers.py` | Dispatch `builder_type="rate_helper_bootstrap"` to `curve_bootstrap.py`; keep existing node-based construction unchanged. |
| `src/msm_pricing/scenarios/curves/key_node_bumps.py` | Stop owning generic rate normalization if it is needed by pricing-engine helper parsing; import promoted helpers instead. |
| `src/msm_pricing/scenarios/curves/engine.py` | For helper-bootstrapped curves, bump copied key nodes and delegate reconstruction to `pricing_engine.curve_bootstrap`. |
| `docs/knowledge/msm_pricing/curves.md` | Document helper-style key-node fields and builder-payload contract. |
| `docs/knowledge/msm_pricing/runtime_resolution.md` | Document resolver dispatch between node-built and helper-bootstrapped curves. |
| `docs/tutorial/05-pricing.md` | Add the user workflow note after the API is implemented. |
| `CHANGELOG.md` | Add a public change entry when code is implemented. |

Model placement rules:

- `OISRateHelperSpec`, `OvernightDepositHelperSpec`, and future
  `InterestRateFutureHelperSpec` are runtime dataclasses in
  `curve_helpers.py`. They may hold QuantLib runtime objects such as indexes,
  calendars, handles, day counters, and enum values. They are not serialized
  and are not stored in DataNodes.
- `OISRateHelperKeyNode` and future `InterestRateFutureHelperKeyNode` are
  Pydantic models in `curve_helper_key_nodes.py`. They validate generic
  key-node dictionaries from `DiscountCurvesNode.key_nodes`. They must contain
  only JSON-compatible fields.
- `CurveHelperBootstrapConfig` is a Pydantic model in `curve_bootstrap.py`. It
  validates the helper-bootstrap portion of `CurveBuildingDetails.builder_payload`.
- `CurveBuildingDetails` remains the persisted curve build specification. Do
  not create a new MetaTable for helper bootstrapping.
- `CurveKeyNode` remains the broad optional producer helper in
  `src/msm_pricing/data_nodes/curves/key_nodes.py`. Do not make helper-specific
  fields required for all curve publishers.

No model or function created in these files may use source-specific names.
Source-specific names remain only in connector adapters and migration notes.

Initial model contracts:

| Model | File | Type | Required Fields | Optional Fields |
| --- | --- | --- | --- | --- |
| `OISRateHelperSpec` | `pricing_engine/curve_helpers.py` | frozen dataclass | `tenor: str`, `quote_decimal: float`, `overnight_index: ql.OvernightIndex`, `settlement_days: int`, `payment_frequency: int`, `payment_calendar: ql.Calendar`, `payment_convention: int`, `rate_averaging: int` | `discounting_curve: ql.YieldTermStructureHandle | None`, `telescopic_value_dates: bool`, `payment_lag: int`, `forward_start: ql.Period | None`, `spread_decimal: float`, `pillar: int | None`, `custom_pillar_date: ql.Date | None`, `end_of_month: bool` |
| `OvernightDepositHelperSpec` | `pricing_engine/curve_helpers.py` | frozen dataclass | `quote_decimal: float`, `tenor: str`, `settlement_days: int`, `calendar: ql.Calendar`, `business_day_convention: int`, `day_counter: ql.DayCounter` | `end_of_month: bool` |
| `InterestRateFutureHelperSpec` | `pricing_engine/curve_helpers.py` | frozen dataclass, deferred | To be defined only when futures are implemented generically. | To be defined only when futures are implemented generically. |
| `OISRateHelperKeyNode` | `pricing_engine/curve_helper_key_nodes.py` | Pydantic model | `helper_type: Literal["ois_rate_helper", "overnight_indexed_swap_helper"]`, `tenor: str`, `quote: float`, `quote_type: str`, `quote_unit: str` | `quote_side`, `settlement_days`, `payment_frequency`, `payment_calendar_code`, `payment_convention`, `day_counter_code`, `rate_averaging`, `telescopic_value_dates`, `payment_lag`, `forward_start`, `spread_decimal`, `pillar`, `custom_pillar_date`, source metadata fields |
| `InterestRateFutureHelperKeyNode` | `pricing_engine/curve_helper_key_nodes.py` | Pydantic model, deferred | To be defined only when futures are implemented generically. | To be defined only when futures are implemented generically. |
| `CurveHelperBootstrapConfig` | `pricing_engine/curve_bootstrap.py` | Pydantic model | `helper_schema: str`, `output_quote_convention: str`, `output_rate_unit: str` | `bootstrap_method`, `implied_front_days`, `front_deposit_helper`, `zero_export_day_counter_code`, `zero_export_compounding`, `zero_export_frequency` |

Conversion ownership:

- `curve_helper_key_nodes.py` validates JSON-compatible key nodes and converts
  them into runtime specs only when the caller provides a generic runtime
  context, such as the already-built overnight index and calendar/day-count
  objects.
- `curve_helpers.py` builds QuantLib helpers from runtime specs. It never reads
  DataNodes, `CurveBuildingDetails`, connector files, or source identifiers.
- `curve_bootstrap.py` reads `CurveBuildingDetails.builder_payload`, asks the
  key-node adapter for runtime specs, asks `curve_helpers.py` for QuantLib
  helpers, bootstraps the term structure, and exports normalized curve points.

### Pricing Engine Layer

Create generic helper modules under `src/msm_pricing/pricing_engine/`:

- `curve_helpers.py`
  - `ql_period_from_tenor(tenor: str) -> ql.Period`
  - `OvernightDepositHelperSpec`
  - `OISRateHelperSpec`
  - `InterestRateFutureHelperSpec` only when futures are implemented
  - `build_overnight_deposit_helper(spec: OvernightDepositHelperSpec) -> ql.RateHelper`
  - `build_ois_rate_helper(spec: OISRateHelperSpec) -> ql.RateHelper`
  - `build_rate_helper_vector(helpers: Sequence[ql.RateHelper], *, front_helper: ql.RateHelper | None = None) -> ql.RateHelperVector`

- `curve_helper_key_nodes.py`
  - `OISRateHelperKeyNode`
  - `InterestRateFutureHelperKeyNode` only when futures are implemented
  - `parse_ois_helper_key_node(node: Mapping[str, object]) -> OISRateHelperKeyNode`
  - `ois_helper_specs_from_key_nodes(...) -> tuple[OISRateHelperSpec, ...]`
  - `helper_specs_from_key_nodes(...) -> tuple[OISRateHelperSpec, ...]`

- `curve_bootstrap.py`
  - `CurveHelperBootstrapConfig`
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

It should not own rate-helper construction or helper bootstrap construction.
When a shocked curve has helper-style key nodes,
`build_scenario_curve_handle(...)` should delegate to
`msm_pricing.pricing_engine.curve_bootstrap` after applying shocks.

This corrects the initial table mapping: donor key-node rebuild behavior is a
scenario consumer use case, but its generic owner is the pricing engine.

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
- [ ] Add `build_overnight_deposit_helper(...)` without hard-coded
  source/currency calendar defaults.
- [ ] Add `build_rate_helper_vector(...)`.
- [ ] Add tests proving no connector imports, strict tenor parsing,
  decimal/percent quote handling, helper vector ordering, and explicit front
  helper behavior.

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
- [ ] Defer futures helper key nodes to a separate stage unless the
  implementation can define a clean generic interest-rate futures spec.

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
  replacement for the donor key-node rebuild behavior.
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
