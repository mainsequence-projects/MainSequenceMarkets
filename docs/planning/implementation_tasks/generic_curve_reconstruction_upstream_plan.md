# Generic Curve Reconstruction And Observation Export Upstream Plan

This implementation plan analyzes generic curve-construction machinery
currently embedded in Valmer connector code and defines where it should move in
`msm_pricing`. The goal is not to copy Valmer functions blindly. The goal is to
promote reusable QuantLib helper construction, generic curve reconstruction,
and curve observation export mechanics into ms-markets while leaving Valmer
source parsing and vendor policy in `valmer-connectors`.

## Success Conditions

- Generic QuantLib rate-helper construction and curve-handle reconstruction are
  available from `msm_pricing.pricing_engine.curves`, not from connector
  packages.
- Helper-style curve key nodes can rebuild runtime curve handles and normalized
  curve observation nodes without importing `valmer_connectors`.
- `msm_pricing.scenarios.curves` can shock helper-style key nodes and delegate
  runtime curve reconstruction to the generic pricing-engine layer.
- Zero-rate export is one observation convention, not the architecture. Future
  curve families must be able to add observation conventions without renaming
  the public reconstruction or export APIs.
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

- `pricing_engine.curves`
- `pricing_engine.curves.helpers`
- `pricing_engine.curves.helper_key_nodes`
- `pricing_engine.curves.reconstruction`
- `pricing_engine.curves.observations`
- `OISRateHelperSpec`
- `InterestRateFutureHelperSpec`
- `OvernightDepositHelperSpec`
- `CurveReconstructionConfig`
- `CurveObservationExportConfig`
- `reconstruct_curve_handle(...)`
- `build_curve_from_helper_key_nodes(...)`
- `export_curve_observation_nodes(...)`

Method-specific names such as `piecewise_log_linear_discount` may exist only as
configuration tokens or private dispatch targets. They should not become the
top-level module or public API boundary.

Source-specific donor function names should not be repeated as concepts in this
plan. Use donor file/line references and generic behavior descriptions instead.
They must not be copied into ms-markets symbols.

## Source Analysis

Source file:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/valmer-connectors-64338319-bd19-48db-bf14-945d8debb9be/src/valmer_connectors/instruments/rates_curves.py`

| Donor Location | Generic Meaning | Target Owner |
| --- | --- | --- |
| `rates_curves.py:303` | Rebuild a runtime curve handle from helper-style key nodes. | `msm_pricing.pricing_engine.curves.reconstruction`; scenarios should consume it, not own it. |
| `rates_curves.py:611` | Select `helper_type="ois_rate_helper"` key nodes and convert quote/tenor/index/convention fields into OIS helper specs. | `msm_pricing.pricing_engine.curves.helpers` plus a generic key-node adapter. |
| `rates_curves.py:581` | Build QuantLib `OISRateHelper` objects from typed quote/tenor/convention specs. | `msm_pricing.pricing_engine.curves.helpers`. |
| `rates_curves.py:644` | Convert helper objects to `ql.RateHelperVector`, optionally adding a front overnight deposit helper. | `msm_pricing.pricing_engine.curves.helpers`. |
| `rates_curves.py:754` | Reconstruct a QuantLib term structure from rate helpers using a configured method. | `msm_pricing.pricing_engine.curves.reconstruction`. |
| `rates_curves.py:770` | Same reconstruction mechanism with different helper inputs. | `msm_pricing.pricing_engine.curves.reconstruction`. |
| `rates_curves.py:782` | Export curve observation nodes from a QuantLib curve at pillar and configured front dates. | `msm_pricing.pricing_engine.curves.observations`. |
| `rates_curves.py:810` | Same curve observation exporter with different configured front dates. | Same generic exporter. |
| `rates_curves.py:741` | Optional front overnight deposit helper from rate/calendar/day-count settings. | `msm_pricing.pricing_engine.curves.helpers`. |
| `rates_curves.py:927` | Strict tenor string to `ql.Period` conversion. | `msm_pricing.pricing_engine.curves.helpers`. |
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
| `src/msm_pricing/pricing_engine/curves/__init__.py` | Curve-pricing subpackage import surface. Keeps curve mechanics grouped instead of adding more flat files to `pricing_engine`. | Lazy exports for stable curve-helper, reconstruction, and observation-export functions. |
| `src/msm_pricing/pricing_engine/curves/helpers.py` | Generic QuantLib rate-helper construction. Runtime-only, no persistence and no connector imports. | Runtime dataclasses: `OISRateHelperSpec`, `OvernightDepositHelperSpec`, deferred `InterestRateFutureHelperSpec`. Functions: `ql_period_from_tenor(...)`, `build_ois_rate_helper(...)`, `build_overnight_deposit_helper(...)`, `build_rate_helper_vector(...)`. |
| `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py` | Convert generic helper-style `key_nodes` dictionaries into runtime helper specs. No source repair or vendor defaults. | Pydantic models: `OISRateHelperKeyNode`, deferred `InterestRateFutureHelperKeyNode`. Functions: `parse_ois_helper_key_node(...)`, `ois_helper_specs_from_key_nodes(...)`, `helper_specs_from_key_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curves/reconstruction.py` | Generic curve-handle reconstruction dispatch. Initial input family is rate helpers, but the module boundary is not rate-helper-specific. | Pydantic model: `CurveReconstructionConfig`. Functions: `reconstruct_curve_handle(...)`, `build_curve_from_helper_key_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curves/observations.py` | Generic export from runtime curve handles to normalized observation nodes. No source, currency, index, or single-convention-specific names. | Pydantic model: `CurveObservationExportConfig`. Functions: `export_curve_observation_nodes(...)`, `curve_observation_value(...)`. |
| `tests/msm_pricing/pricing_engine/curves/test_helpers.py` | Unit coverage for helper specs and QuantLib helper construction. | Tests for tenor parsing, OIS helper construction, deposit helper construction, helper vector order, and no connector imports. |
| `tests/msm_pricing/pricing_engine/curves/test_helper_key_nodes.py` | Unit coverage for helper-key-node parsing. | Tests for required generic fields, unit normalization, unsupported helper types, and absence of source-specific defaults. |
| `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py` | Unit coverage for curve reconstruction dispatch and helper-based reconstruction. | Tests for settings restoration, extrapolation policy, method dispatch, and builder payload parsing. |
| `tests/msm_pricing/pricing_engine/curves/test_observations.py` | Unit coverage for curve observation export. | Tests for exported node conventions, pillar/front-date inclusion, rate units, and unsupported conventions. |

Update these existing files:

| File | Change |
| --- | --- |
| `src/msm_pricing/pricing_engine/__init__.py` | Optionally re-export only stable high-level curve functions from `pricing_engine.curves`; do not make it the owner of every helper symbol. |
| `src/msm_pricing/pricing_engine/resolvers.py` | Dispatch generic curve reconstruction builders to `pricing_engine.curves.reconstruction`; keep existing node-based construction unchanged. |
| `src/msm_pricing/scenarios/curves/key_node_bumps.py` | Stop owning generic rate normalization if it is needed by pricing-engine helper parsing; import promoted helpers instead. |
| `src/msm_pricing/scenarios/curves/engine.py` | For helper-reconstructed curves, bump copied key nodes and delegate reconstruction to `pricing_engine.curves.reconstruction`. |
| `docs/knowledge/msm_pricing/curves.md` | Document helper-style key-node fields and builder-payload contract. |
| `docs/knowledge/msm_pricing/runtime_resolution.md` | Document resolver dispatch between node-built and reconstructed curves. |
| `docs/tutorial/05-pricing.md` | Add the user workflow note after the API is implemented. |
| `CHANGELOG.md` | Add a public change entry when code is implemented. |

Model placement rules:

- `OISRateHelperSpec`, `OvernightDepositHelperSpec`, and future
  `InterestRateFutureHelperSpec` are runtime dataclasses in
  `pricing_engine/curves/helpers.py`. They may hold QuantLib runtime objects
  such as indexes, calendars, handles, day counters, and enum values. They are
  not serialized and are not stored in DataNodes.
- `OISRateHelperKeyNode` and future `InterestRateFutureHelperKeyNode` are
  Pydantic models in `pricing_engine/curves/helper_key_nodes.py`. They validate
  generic key-node dictionaries from `DiscountCurvesNode.key_nodes`. They must
  contain only JSON-compatible fields.
- `CurveReconstructionConfig` is an internal Pydantic model in
  `pricing_engine/curves/reconstruction.py`. It is derived from
  `CurveBuildingDetails` plus `CurveBuildingDetails.builder_payload`; callers
  should not have to author the fully normalized dispatch object by hand.
- `CurveObservationExportConfig` is a Pydantic model in
  `pricing_engine/curves/observations.py`. It is derived primarily from
  top-level `CurveBuildingDetails` fields such as `quote_convention`,
  `rate_unit`, `day_counter_code`, `compounding`, and
  `compounding_frequency`.
- `CurveBuildingDetails` remains the persisted curve build specification. Do
  not create a new MetaTable for curve reconstruction.
- `CurveKeyNode` remains the broad optional producer helper in
  `src/msm_pricing/data_nodes/curves/key_nodes.py`. Do not make helper-specific
  fields required for all curve publishers.

No model or function created in these files may use source-specific names.
Source-specific names remain only in connector adapters and migration notes.

Initial model contracts:

| Model | File | Type | Required Fields | Optional Fields |
| --- | --- | --- | --- | --- |
| `OISRateHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass | `tenor: str`, `quote_decimal: float`, `overnight_index: ql.OvernightIndex`, `settlement_days: int`, `payment_frequency: int`, `payment_calendar: ql.Calendar`, `payment_convention: int`, `rate_averaging: int` | `discounting_curve: ql.YieldTermStructureHandle | None`, `telescopic_value_dates: bool`, `payment_lag: int`, `forward_start: ql.Period | None`, `spread_decimal: float`, `pillar: int | None`, `custom_pillar_date: ql.Date | None`, `end_of_month: bool` |
| `OvernightDepositHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass | `quote_decimal: float`, `tenor: str`, `settlement_days: int`, `calendar: ql.Calendar`, `business_day_convention: int`, `day_counter: ql.DayCounter` | `end_of_month: bool` |
| `InterestRateFutureHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass, deferred | To be defined only when futures are implemented generically. | To be defined only when futures are implemented generically. |
| `OISRateHelperKeyNode` | `pricing_engine/curves/helper_key_nodes.py` | Pydantic model | `helper_type: Literal["ois_rate_helper", "overnight_indexed_swap_helper"]`, `tenor: str`, `quote: float`, `quote_type: str`, `quote_unit: str` | `quote_side`, `settlement_days`, `payment_frequency`, `payment_calendar_code`, `payment_convention`, `day_counter_code`, `rate_averaging`, `telescopic_value_dates`, `payment_lag`, `forward_start`, `spread_decimal`, `pillar`, `custom_pillar_date`, source metadata fields |
| `InterestRateFutureHelperKeyNode` | `pricing_engine/curves/helper_key_nodes.py` | Pydantic model, deferred | To be defined only when futures are implemented generically. | To be defined only when futures are implemented generically. |
| `CurveReconstructionConfig` | `pricing_engine/curves/reconstruction.py` | Pydantic model | `builder_type: str`, `reconstruction_method: str`, `observation_export: CurveObservationExportConfig` | `input_schema`, `input_options`, `method_options`, `metadata_json` |
| `CurveObservationExportConfig` | `pricing_engine/curves/observations.py` | Pydantic model | `quote_convention: str`, `rate_unit: str` | `node_days`, `include_pillar_dates`, `day_counter_code`, `compounding`, `frequency`, `calendar_code`, `metadata_json` |

Conversion ownership:

- `pricing_engine.curves.helper_key_nodes` validates JSON-compatible key nodes
  and converts them into runtime specs only when the caller provides a generic
  runtime context, such as the already-built overnight index and
  calendar/day-count objects.
- `pricing_engine.curves.helpers` builds QuantLib helpers from runtime specs.
  It never reads DataNodes, `CurveBuildingDetails`, connector files, or source
  identifiers.
- `pricing_engine.curves.reconstruction` reads `CurveBuildingDetails` and
  `CurveBuildingDetails.builder_payload`, dispatches by `builder_type` and
  reconstruction method, asks the relevant adapter for runtime specs, asks
  `pricing_engine.curves.helpers` for QuantLib helpers when the builder type is
  `rate_helper_curve`, and builds the runtime curve handle.
- `pricing_engine.curves.observations` exports normalized observation nodes
  according to `CurveObservationExportConfig`. It should not know how the curve
  was reconstructed.

### Pricing Engine Curve Subpackage

Create generic helper modules under
`src/msm_pricing/pricing_engine/curves/`. Do not add more flat curve files
directly under `src/msm_pricing/pricing_engine/`.

- `__init__.py`
  - lazy exports for the curve subpackage

- `helpers.py`
  - `ql_period_from_tenor(tenor: str) -> ql.Period`
  - `OvernightDepositHelperSpec`
  - `OISRateHelperSpec`
  - `InterestRateFutureHelperSpec` only when futures are implemented
  - `build_overnight_deposit_helper(spec: OvernightDepositHelperSpec) -> ql.RateHelper`
  - `build_ois_rate_helper(spec: OISRateHelperSpec) -> ql.RateHelper`
  - `build_rate_helper_vector(helpers: Sequence[ql.RateHelper], *, front_helper: ql.RateHelper | None = None) -> ql.RateHelperVector`

- `helper_key_nodes.py`
  - `OISRateHelperKeyNode`
  - `InterestRateFutureHelperKeyNode` only when futures are implemented
  - `parse_ois_helper_key_node(node: Mapping[str, object]) -> OISRateHelperKeyNode`
  - `ois_helper_specs_from_key_nodes(...) -> tuple[OISRateHelperSpec, ...]`
  - `helper_specs_from_key_nodes(...) -> tuple[OISRateHelperSpec, ...]`

- `reconstruction.py`
  - `CurveReconstructionConfig`
  - `reconstruct_curve_handle(...) -> ql.YieldTermStructureHandle`
  - `build_curve_from_helper_key_nodes(...) -> ql.YieldTermStructureHandle`

- `observations.py`
  - `CurveObservationExportConfig`
  - `curve_observation_value(...) -> float`
  - `export_curve_observation_nodes(...) -> list[dict[str, float | int | str]]`

These modules should be exported lazily from
`src/msm_pricing/pricing_engine/curves/__init__.py`. Only stable high-level
functions should be re-exported from `src/msm_pricing/pricing_engine/__init__.py`.

### Curve Build Details

Do not overload the existing node-based `interpolation_method` path. Current
`build_curve_from_curve_observation(...)` builds from already-materialized curve
nodes. Helper-style curves are different: they reconstruct runtime curves from
market helpers and then export observation nodes using an explicit output
configuration.

Use `CurveBuildingDetails` for the public persisted contract. Top-level columns
describe the output curve that is published and priced from. `builder_payload`
should contain only input-family details that do not deserve stable columns.
The existing `bootstrap_method` field can carry the first QuantLib method token
for schema compatibility, but the in-memory API should normalize it into
`CurveReconstructionConfig.reconstruction_method`. Do not name modules or
public functions after bootstrap.

```python
CurveBuildingDetails(
    builder_type="rate_helper_curve",
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter_code="Actual360",
    calendar_code="TARGET",
    interpolation_method="log_linear_discount",
    compounding="simple",
    extrapolation_policy="enabled",
    bootstrap_method="piecewise_log_linear_discount",
    builder_payload={
        "helper_schema": "ois_rate_helper@v1",
        "front_helper": {"enabled": True, "tenor": "1D"},
    },
)
```

The exact token names should be finalized during implementation, but the
contract should preserve this split:

- `builder_type` says which public builder path is used. The first new value
  should be `rate_helper_curve`, not a vague `curve_reconstruction` umbrella.
- `bootstrap_method` says which QuantLib reconstruction method is used.
- `quote_convention`, `rate_unit`, `day_counter_code`, `calendar_code`,
  `compounding`, and `compounding_frequency` describe the exported observation
  convention.
- `builder_payload.helper_schema` identifies the helper input schema version,
  not a vendor source.
- `builder_payload` carries only input-family-specific defaults such as a front
  helper, helper quote-side policy, or helper parsing defaults.
- The published `curve` column remains normalized exported observation nodes
  for storage/API use.
- `key_nodes` carries source helper provenance sufficient to rebuild runtime
  helpers.

`quote_convention="zero_rate"` is only one supported observation export
convention. The design must allow additional conventions such as
`discount_factor`, `forward_rate`, spread/basis observations, or other future
curve-family outputs without renaming the module or the public reconstruction
function.

The generic layer should still normalize this persisted row internally:

```python
config = CurveReconstructionConfig.from_building_details(building_details)
```

That normalized object may contain `builder_type`, `reconstruction_method`,
`observation_export`, and input options. It is an implementation convenience,
not the row shape users should have to hand-author.

### Scenario Layer

`msm_pricing.scenarios.curves` should stay responsible for:

- scenario models;
- bump specifications;
- copying and bumping key nodes;
- base/scenario pricing orchestration;
- diagnostics and strict preflight.

It should not own rate-helper construction, curve reconstruction methods, or
observation export.
When a shocked curve has helper-style key nodes,
`build_scenario_curve_handle(...)` should delegate to
`msm_pricing.pricing_engine.curves.reconstruction` after applying shocks.

This corrects the initial table mapping: donor key-node rebuild behavior is a
scenario consumer use case, but its generic owner is the pricing engine.

### DataNode And Key-Node Layer

The existing `CurveKeyNode` helper already allows source-specific extension
fields. Do not make helper-key-node fields mandatory for all curves. Instead,
document and optionally validate helper-style fields when a producer chooses
helper-based reconstruction:

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

- `src/msm_pricing/pricing_engine/curves/__init__.py`
- `src/msm_pricing/pricing_engine/curves/helpers.py`
- `tests/msm_pricing/pricing_engine/curves/test_helpers.py`

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

- `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py`
- `tests/msm_pricing/pricing_engine/curves/test_helper_key_nodes.py`
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

### Stage 3: Generic Curve Reconstruction And Observation Export

Files to create or update:

- `src/msm_pricing/pricing_engine/curves/reconstruction.py`
- `src/msm_pricing/pricing_engine/curves/observations.py`
- `src/msm_pricing/pricing_engine/curves/__init__.py`
- `src/msm_pricing/pricing_engine/__init__.py`
- `src/msm_pricing/pricing_engine/resolvers.py`
- `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py`
- `tests/msm_pricing/pricing_engine/curves/test_observations.py`

Tasks:

- [ ] Add `reconstruct_curve_handle(...)` with explicit `builder_type` and
  `reconstruction_method` dispatch.
- [ ] Add the first reconstruction method for `builder_type="rate_helper_curve"` and
  `reconstruction_method="piecewise_log_linear_discount"` without exposing that
  method as the module or top-level public API name.
- [ ] Preserve and restore `ql.Settings.instance().evaluationDate` around
  QuantLib reconstruction calls.
- [ ] Return `ql.YieldTermStructureHandle` with extrapolation controlled by
  `CurveBuildingDetails.extrapolation_policy`.
- [ ] Add `export_curve_observation_nodes(...)` with configurable node days,
  pillar-date inclusion, quote convention, rate unit, day counter, compounding,
  and frequency.
- [ ] Add `build_curve_from_helper_key_nodes(...)` as the generic replacement
  for the donor key-node rebuild behavior.
- [ ] Extend resolver dispatch so `builder_type="rate_helper_curve"` uses the
  generic reconstruction path and existing node-based curves remain unchanged.
- [ ] If existing rows require `builder_type="rate_helper_bootstrap"`, accept it
  only as a compatibility alias that maps to
  `builder_type="rate_helper_curve"`.

### Stage 4: Scenario Integration

Files to update:

- `src/msm_pricing/scenarios/curves/engine.py`
- `tests/msm_pricing/scenarios/curves/test_curve_scenarios.py`
- `tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py`

Tasks:

- [ ] Keep scenario shock application in `scenarios.curves`.
- [ ] When runtime build details indicate helper-based reconstruction, bump copied
  helper key nodes and delegate reconstruction to
  `pricing_engine.curves.reconstruction`.
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
  `msm_pricing.pricing_engine.curves.helpers`.
- [ ] Replace Valmer-local helper-based reconstruction with
  `msm_pricing.pricing_engine.curves.reconstruction`.
- [ ] Replace Valmer-local curve observation export with
  `msm_pricing.pricing_engine.curves.observations`.
- [ ] Keep Valmer file parsing and source row classification local.
- [ ] Preserve connector-owned tests for Valmer-specific row mapping.
- [ ] Add compatibility wrappers only where downstream imports require them,
  and mark those wrappers as temporary.

## Validation Requirements

- Focused pricing-engine tests for helper specs, helper vectors, helper-based
  reconstruction, and curve observation export.
- Focused scenario tests proving helper-style shocked curves rebuild through the
  generic pricing-engine path.
- Valmer connector migration tests proving the same exported observation nodes
  are produced before and after the adapter cutover within a documented
  tolerance.
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
  path; generic reconstruction is an additional builder path.
- Do not implement futures helpers in the first stage unless the generic
  contract is clean and tested independently from Valmer source parsing.
