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
| `rates_curves.py:967` | Normalize quote/yield percent versus decimal. | `msm_pricing.pricing_engine.curves.quote_units`; scenario bump helpers import the promoted functions. |

Additional generic candidates observed around the listed code:

- The source-specific OIS helper wrapper at `rates_curves.py:704` should share
  the same generic OIS helper builder.
- The source-specific futures helper wrapper at `rates_curves.py:690` maps to
  `InterestRateFutureHelperSpec` and `InterestRateFutureHelperKeyNode`.
  Connector code still owns source contract-code parsing, but the QuantLib SOFR
  future helper construction belongs in ms-markets.
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

### Primitive-First Layering Contract

The core implementation must be QuantLib-primitive first. The persisted
`CurveBuildingDetails` path is only an adapter for resolving stored curves.

Layer 1 is the reusable primitive API. It has no MetaTable, DataNode, connector,
or source dependency:

```python
helpers = build_rate_helper_vector(rate_helpers)
handle = reconstruct_curve_handle(
    valuation_date=valuation_date,
    helpers=helpers,
    method="piecewise_log_linear_discount",
    day_counter=ql.Actual360(),
    extrapolation=True,
)
nodes = export_curve_observation_nodes(
    handle,
    valuation_date=valuation_date,
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter=ql.Actual360(),
    compounding=ql.Compounded,
    frequency=ql.Annual,
)
```

Layer 2 is the persistence adapter. It converts stored
`CurveBuildingDetails` plus `DiscountCurvesNode.key_nodes` into the primitive
API above. It exists because QuantLib helpers, handles, indexes, calendars, and
global evaluation-date state are runtime objects and cannot be persisted
directly.

The dependency direction is strict:

```text
CurveBuildingDetails + key_nodes
  -> adapter parsing and validation
  -> QuantLib helper specs
  -> QuantLib RateHelper objects
  -> reconstruct_curve_handle(...)
  -> optional export_curve_observation_nodes(...)
```

No primitive API may accept `CurveBuildingDetails`. No generic helper builder
may read DataNodes or connector payloads.

### Concrete File And Model Placement

Implemented files in ms-markets:

| File | Owns | Models / Functions |
| --- | --- | --- |
| `src/msm_pricing/pricing_engine/curves/__init__.py` | Curve-pricing subpackage import surface. Keeps curve mechanics grouped instead of adding more flat files to `pricing_engine`. | Lazy exports for stable curve-helper, reconstruction, and observation-export functions. |
| `src/msm_pricing/pricing_engine/curves/quote_units.py` | Canonical rate quote/yield unit normalization shared by reconstruction and scenarios. | `RATE_QUOTE_TYPES`, `key_node_decimal_rate(...)`, `normalize_rate_value(...)`. |
| `src/msm_pricing/pricing_engine/curves/helpers.py` | Generic QuantLib rate-helper construction. Runtime-only, no persistence and no connector imports. | Runtime dataclasses: `OISRateHelperSpec`, `OvernightDepositHelperSpec`, `InterestRateFutureHelperSpec`, `RateHelperSpec`. Functions: `ql_period_from_tenor(...)`, `build_ois_rate_helper(...)`, `build_overnight_deposit_helper(...)`, `build_interest_rate_future_helper(...)`, `build_rate_helper(...)`, `build_rate_helpers(...)`, `build_rate_helper_vector(...)`. |
| `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py` | Convert generic helper-style `key_nodes` dictionaries into runtime helper specs. No source repair or vendor defaults. | Pydantic models: `OISRateHelperKeyNode`, `OvernightDepositHelperKeyNode`, `InterestRateFutureHelperKeyNode`. Functions: `normalize_helper_type(...)`, `parse_rate_helper_key_node(...)`, `helper_specs_from_key_nodes(...)`, `key_nodes_contain_rate_helpers(...)`. |
| `src/msm_pricing/pricing_engine/curves/reconstruction.py` | Generic curve reconstruction dispatch. Initial input family is rate helpers, but the module boundary is not rate-helper-specific. | Pydantic model: `CurveReconstructionConfig`. Functions: `reconstruct_curve_term_structure(...)`, `reconstruct_curve_term_structure_from_helper_specs(...)`, `reconstruct_curve_term_structure_from_key_nodes(...)`, `reconstruct_curve_handle(...)`, `reconstruct_curve_handle_from_helper_specs(...)`, `reconstruct_curve_handle_from_key_nodes(...)`, `build_curve_from_helper_key_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curves/observations.py` | Generic export from runtime curve handles to normalized observation nodes. No source, currency, index, or single-convention-specific names. | Pydantic models: `CurveObservationNode`, `CurveObservationExportConfig`. Methods/functions: `CurveObservationExportConfig.from_curve_building_details(...)`, `curve_observation_value(...)`, `export_curve_observation_nodes(...)`. |
| `src/msm_pricing/pricing_engine/curves/adapters.py` | Persistence adapter from `CurveBuildingDetails` plus curve observation key nodes into primitive reconstruction. | `RATE_HELPER_BUILDER_TYPES`, `is_rate_helper_curve_build(...)`, `reconstruct_curve_from_curve_building_details(...)`. |
| `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py` | Focused unit coverage for the first helper-reconstruction slice. | Tests for tenor parsing, required runtime overnight index, helper-spec reconstruction, resolver adapter dispatch, observation export, scenario reconstruction without mutation, and empty helper rejection. |

Update these existing files:

| File | Change |
| --- | --- |
| `src/msm_pricing/pricing_engine/__init__.py` | Optionally re-export only stable high-level curve functions from `pricing_engine.curves`; do not make it the owner of every helper symbol. |
| `src/msm_pricing/pricing_engine/resolvers.py` | Dispatch generic curve reconstruction builders to `pricing_engine.curves.reconstruction`; keep existing node-based construction unchanged. |
| `src/msm_pricing/scenarios/curves/key_node_bumps.py` | Stop owning generic rate normalization if it is needed by pricing-engine helper parsing; import promoted helpers instead. |
| `src/msm_pricing/scenarios/curves/engine.py` | For helper-reconstructed curves, bump copied key nodes and delegate reconstruction to `pricing_engine.curves.reconstruction`. |
| `docs/knowledge/msm_pricing/curves.md` | Document the primitive API, persistence adapter boundary, helper-style key-node fields, and builder-payload contract. |
| `docs/knowledge/msm_pricing/runtime_resolution.md` | Document resolver dispatch between node-built and reconstructed curves. |
| `docs/tutorial/05-pricing.md` | Add the user workflow note after the API is implemented. |
| `CHANGELOG.md` | Add a public change entry when code is implemented. |
| `examples/msm_pricing/curve_reconstruction.py` | Offline helper-based curve reconstruction and observation-export smoke example. |

Model placement rules:

- `OISRateHelperSpec`, `OvernightDepositHelperSpec`, and
  `InterestRateFutureHelperSpec` are runtime dataclasses in
  `pricing_engine/curves/helpers.py`. They may hold QuantLib runtime objects
  such as indexes, calendars, handles, day counters, and enum values. They are
  not serialized and are not stored in DataNodes.
- `OISRateHelperKeyNode`, `OvernightDepositHelperKeyNode`, and
  `InterestRateFutureHelperKeyNode` are Pydantic models in
  `pricing_engine/curves/helper_key_nodes.py`. They validate generic key-node
  dictionaries from `DiscountCurvesNode.key_nodes`. They must contain only
  JSON-compatible fields.
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
  fields required for all curve publishers. Its canonical source identity is
  `source_reference={"type": "asset" | "index", "identifier": "..."}`;
  top-level `asset_identifier` and `index_identifier` key-node fields are
  rejected.
- `FixedIncomeCurveKeyNode` is the typed fixed-income base for quote fields and
  the shared source reference. Deposit, OIS, futures, bond, FX, and basis helper
  models inherit it while retaining only their own helper-specific fields.

No model or function created in these files may use source-specific names.
Source-specific names remain only in connector adapters and migration notes.

Initial model contracts:

| Model | File | Type | Required Fields | Optional Fields |
| --- | --- | --- | --- | --- |
| `OISRateHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass | `quote: float`, `tenor: str | ql.Period`, `overnight_index: ql.OvernightIndex` | Generic QuantLib OIS fields: `settlement_days`, `discounting_curve`, `telescopic_value_dates`, `payment_lag`, `payment_convention`, `payment_frequency`, `payment_calendar`, `forward_start`, `overnight_spread`, `pillar`, `custom_pillar_date`, `averaging_method`, `end_of_month`, `fixed_payment_frequency`, `fixed_calendar`, `lookback_days`, `lockout_days`, `apply_observation_shift`, `pricer`, `rule`, `overnight_calendar`, and `date_generation_convention`. |
| `OvernightDepositHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass | `quote: float` | `tenor: str | ql.Period`, `fixing_days`, `calendar`, `convention`, `end_of_month`, `day_counter` |
| `InterestRateFutureHelperSpec` | `pricing_engine/curves/helpers.py` | frozen dataclass | `quote: float`, `reference_month: int \| str`, `reference_year: int`, `reference_frequency: int \| str` | `future_family`, `convexity_adjustment`, `pillar`, `custom_pillar_date`. The first supported concrete family is SOFR because QuantLib exposes `SofrFutureRateHelper`; the model remains the generic interest-rate futures runtime contract. |
| `FixedIncomeCurveKeyNode` | `pricing_engine/curves/fixed_income_key_nodes.py` | Pydantic base model | `quote: float`, `quote_type: str`, `quote_unit: str` | typed asset/index `source_reference`, `instrument_type`, and `quote_side` |
| `OISRateHelperKeyNode` | `pricing_engine/curves/helper_key_nodes.py` | Pydantic model | `helper_type: Literal["ois_rate_helper", "overnight_indexed_swap_helper"]`, `quote: float`, `quote_type: str`, `quote_unit: str`, `tenor: str` | shared source fields, `settlement_days`, OIS-only index/runtime dependencies, generic OIS schedule/convention fields mirroring `OISRateHelperSpec`, and source metadata fields |
| `OvernightDepositHelperKeyNode` | `pricing_engine/curves/helper_key_nodes.py` | Pydantic model | `helper_type: Literal["overnight_deposit_helper"]`, `quote: float`, `quote_type: str`, `quote_unit: str` | shared source fields, `tenor`, `fixing_days`, `calendar_code`, `business_day_convention`, `day_counter_code`, `end_of_month`, source metadata fields |
| `InterestRateFutureHelperKeyNode` | `pricing_engine/curves/helper_key_nodes.py` | Pydantic model | `helper_type: Literal["interest_rate_future_helper", "sofr_future_rate_helper"]`, `quote: float`, `quote_type: str`, `quote_unit: str`, `reference_month`, `reference_year`, `reference_frequency` | shared source fields, `future_family`, `convexity_adjustment`, `pillar`, `custom_pillar_date`, source metadata fields. It has no OIS-only fields. `sofr_future_rate_helper` defaults `future_family` to `sofr`. |
| `CurveReconstructionConfig` | `pricing_engine/curves/reconstruction.py` | Pydantic model | none beyond defaults | `bootstrap_method`, `day_counter_code`, `extrapolation`; derived from `CurveBuildingDetails` by the adapter. |
| `CurveObservationExportConfig` | `pricing_engine/curves/observations.py` | Pydantic model | none beyond defaults | `quote_convention`, `rate_unit`, `day_counter_code`, `compounding`, `compounding_frequency`; `from_curve_building_details(...)` derives these from persisted build details and requires explicit output/runtime payload keys when source-helper placeholders are used. |

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
  - `InterestRateFutureHelperSpec`
  - `build_overnight_deposit_helper(spec: OvernightDepositHelperSpec) -> ql.RateHelper`
  - `build_ois_rate_helper(spec: OISRateHelperSpec) -> ql.RateHelper`
  - `build_interest_rate_future_helper(spec: InterestRateFutureHelperSpec) -> ql.RateHelper`
  - `build_rate_helper_vector(helpers: Sequence[ql.RateHelper]) -> ql.RateHelperVector`

- `helper_key_nodes.py`
  - `OISRateHelperKeyNode`
  - `OvernightDepositHelperKeyNode`
  - `InterestRateFutureHelperKeyNode`
  - `parse_rate_helper_key_node(node: Mapping[str, object]) -> RateHelperKeyNode`
  - `helper_specs_from_key_nodes(...) -> tuple[OvernightDepositHelperSpec | OISRateHelperSpec, ...]`

- `reconstruction.py`
  - `CurveReconstructionConfig`
  - `reconstruct_curve_handle(helpers: Sequence[ql.RateHelper] | ql.RateHelperVector, *, valuation_date: ql.Date, day_counter: ql.DayCounter, bootstrap_method: Literal["piecewise_log_linear_discount"], extrapolation: bool = True) -> ql.YieldTermStructureHandle`
  - `reconstruct_curve_term_structure(...) -> ql.YieldTermStructure` for
    callers that need QuantLib pillar dates through `dates()`
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
`CurveReconstructionConfig.bootstrap_method`. Do not name modules or public
functions after bootstrap.

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
        "helper_schema": "rate_helpers@v1",
    },
)
```

The v1 token contract is fixed:

- `builder_type="rate_helper_curve"` means the stored `key_nodes` are converted
  into QuantLib `RateHelper` objects and reconstructed through the primitive
  curve API.
- `bootstrap_method="piecewise_log_linear_discount"` is the only v1
  reconstruction method for `rate_helper_curve`.
- `quote_convention`, `rate_unit`, `day_counter_code`, `calendar_code`,
  `compounding`, and `compounding_frequency` describe the exported observation
  convention.
- `builder_payload.helper_schema="rate_helpers@v1"` is the only v1 helper input
  schema. It is not a vendor source.
- `builder_payload` must not contain market-data quotes. A front overnight
  deposit helper is represented as a `key_nodes` item with
  `helper_type="overnight_deposit_helper"`.
- The published `curve` column remains normalized exported observation nodes
  for storage/API use.
- `key_nodes` carries source helper provenance sufficient to rebuild runtime
  helpers.

Extension note: context/provenance nodes, such as FX spot context for
cross-currency helpers, are additive under the canonical
`rate_helpers@v1` helper schema. Do not bump helper schema names unless the
project explicitly approves a breaking contract change. The extension keeps the
same `builder_type="rate_helper_curve"` and primitive reconstruction path.

`quote_convention="zero_rate"` is only one supported observation export
convention. The design must allow additional conventions such as
`discount_factor`, `forward_rate`, spread/basis observations, or other future
curve-family outputs without renaming the module or the public reconstruction
function.

The generic layer should still normalize this persisted row internally:

```python
config = CurveReconstructionConfig.from_curve_building_details(building_details)
```

That normalized object contains only the adapter values needed by the v1
primitive reconstruction path: `bootstrap_method`, `day_counter_code`, and
`extrapolation`. It is an implementation convenience, not the row shape users
should have to hand-author.

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
The high-level `price_curve_scenario(...)` path must also forward
`overnight_index` and `overnight_index_resolver` into that helper so OIS
helper curves can use the same generic scenario loop.

This corrects the initial table mapping: donor key-node rebuild behavior is a
scenario consumer use case, but its generic owner is the pricing engine.

### DataNode And Key-Node Layer

The existing `CurveKeyNode` helper already allows source-specific extension
fields. Do not make helper-key-node fields mandatory for all curves. Instead,
document and optionally validate helper-style fields when a producer chooses
helper-based reconstruction:

- `source_reference` with `type="asset"` or `type="index"` and a canonical
  unique identifier
- `helper_type`
- `tenor`
- `quote`, `quote_type`, `quote_unit`
- optional `settlement_days`, calendar/day-count fields for deposit helpers,
  helper-specific runtime dependencies, and source metadata fields

Source identity is independent from helper construction. A fixed-income bond
helper may reference an asset, while swap, futures, deposit, FX, and basis
quotes may reference Index rows. Futures helpers do not carry OIS-specific
fields. Do not infer helper dependencies from `source_reference`.

The v1 helper key-node adapter accepts these helper and context types:

- `overnight_deposit_helper`
- `ois_rate_helper`
- `overnight_indexed_swap_helper`
- `interest_rate_future_helper`
- `sofr_future_rate_helper`
- `zero_coupon_bond_helper`
- `fixed_rate_bond_helper`
- `fx_spot`
- `fx_swap_rate_helper`
- `const_notional_cross_currency_basis_swap_rate_helper`

Generic rate normalization should reuse the current key-node rate machinery.
If that helper is needed outside scenarios, promote it to a pricing-engine
key-node utility and have `scenarios.curves.key_node_bumps` import from there.

## Implementation Stages

### Documentation Gate: Canonical Pricing Docs

This plan is not the final documentation. The implementation is not complete
until the primitive-first architecture is documented in the canonical pricing
documentation.

Files to update:

- `docs/knowledge/msm_pricing/curves.md`
- `docs/knowledge/msm_pricing/runtime_resolution.md`
- `docs/tutorial/05-pricing.md`
- `examples/msm_pricing/` with a focused curve reconstruction example once the
  public API exists

Tasks:

- [x] Add a canonical `Primitive QuantLib API` section to
  `docs/knowledge/msm_pricing/curves.md` showing
  `build_rate_helper_vector(...)`, `reconstruct_curve_handle(...)`, and
  `export_curve_observation_nodes(...)` without `CurveBuildingDetails`.
- [x] Add a canonical `Persistence Adapter` section explaining that
  `CurveBuildingDetails + key_nodes` is only a resolver/scenario bridge into
  the primitive API, not the core abstraction.
- [x] Document the exact v1 tokens accepted by the adapter:
  `builder_type="rate_helper_curve"`,
  `bootstrap_method="piecewise_log_linear_discount"`,
  `builder_payload.helper_schema="rate_helpers@v1"`, and supported helper
  node `helper_type` values.
- [x] Document that context-aware helper nodes extend the same
  `rate_helpers@v1` adapter path instead of creating a separate curve builder
  or schema name.
- [x] Document that market-data front helpers are represented as helper key
  nodes, not as a magic `builder_payload.front_helper` flag.
- [x] Update `runtime_resolution.md` with the resolution flow from
  `CurveBuildingDetails + key_nodes` to QuantLib helpers to the reconstructed
  handle.
- [x] Update `docs/tutorial/05-pricing.md` and add an `examples/msm_pricing/`
  example after the public API is implemented.
- [x] Add documentation validation to the implementation PR:
  `uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`.

### Stage 1: Tenor And Rate Helper Primitives

Files created:

- `src/msm_pricing/pricing_engine/curves/__init__.py`
- `src/msm_pricing/pricing_engine/curves/helpers.py`
- `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py`

Tasks:

- [x] Add strict `ql_period_from_tenor(...)` supporting `D`, `W`, `M`, and `Y`.
- [x] Add typed helper specs for OIS and optional overnight deposit helpers.
- [x] Add `build_ois_rate_helper(...)` with explicit quote, tenor, settlement
  days, caller-supplied overnight-index inputs, and the generic QuantLib OIS
  schedule/convention fields required by non-default market conventions.
- [x] Add `build_overnight_deposit_helper(...)` without hard-coded
  source/currency calendar defaults.
- [x] Add `build_rate_helper_vector(...)`.
- [x] Add tests proving strict tenor parsing and helper-based curve
  reconstruction through QuantLib helpers.

### Stage 2: Helper-Key-Node Adapter

Files created or updated:

- `src/msm_pricing/pricing_engine/curves/helper_key_nodes.py`
- `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py`
- `docs/knowledge/msm_pricing/curves.md`

Tasks:

- [x] Convert helper-style key-node dictionaries into typed helper specs.
- [x] Promote rate normalization into `pricing_engine.curves.quote_units` and
  have scenario key-node bumps import it.
- [x] Require explicit units; do not infer percent versus decimal from source.
- [x] Add typed asset/index `source_reference` provenance shared by every
      fixed-income helper model, with no scalar identity compatibility fields.
- [x] Keep connector-specific source repair outside this adapter.
- [x] Support `helper_type="overnight_deposit_helper"`,
  `"ois_rate_helper"`, and `"overnight_indexed_swap_helper"` in v1.
- [x] Map generic OIS key-node fields such as payment convention,
  payment/fixed-leg frequency, payment/fixed-leg calendar, averaging method,
  pillar choice, and observation-shift fields into `OISRateHelperSpec`.
- [x] Support `helper_type="sofr_future_rate_helper"` through the generic
  `InterestRateFutureHelperSpec` and require explicit futures price units.

### Stage 3: Generic Curve Reconstruction And Observation Export

Files created or updated:

- `src/msm_pricing/pricing_engine/curves/reconstruction.py`
- `src/msm_pricing/pricing_engine/curves/observations.py`
- `src/msm_pricing/pricing_engine/curves/__init__.py`
- `src/msm_pricing/pricing_engine/__init__.py`
- `src/msm_pricing/pricing_engine/resolvers.py`
- `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py`
- `tests/msm_pricing/pricing_engine/curves/test_reconstruction.py`

Tasks:

- [x] Add `reconstruct_curve_handle(...)` with explicit bootstrap-method
  dispatch.
- [x] Add the first reconstruction method for `builder_type="rate_helper_curve"` and
  `bootstrap_method="piecewise_log_linear_discount"` without exposing that
  method as the module or top-level public API name.
- [x] Preserve and restore `ql.Settings.instance().evaluationDate` around
  QuantLib reconstruction calls.
- [x] Return `ql.YieldTermStructureHandle` with extrapolation controlled by
  `CurveBuildingDetails.extrapolation_policy`.
- [x] Add term-structure reconstruction functions for observation export paths
  that need QuantLib `dates()` pillar access.
- [x] Add `export_curve_observation_nodes(...)` with configurable node days,
  pillar-date inclusion, quote convention, rate unit, day counter, compounding,
  and frequency.
- [x] Add `CurveObservationExportConfig.from_curve_building_details(...)` so
  helper-built curves can export compounded annual zero nodes from canonical
  build details instead of connector-local export functions.
- [x] Support implied front nodes through `node_days=[...]` combined with
  pillar-date export.
- [x] Add `build_curve_from_helper_key_nodes(...)` as the generic replacement
  for the donor key-node rebuild behavior.
- [x] Extend resolver dispatch so `builder_type="rate_helper_curve"` uses the
  generic reconstruction path and existing node-based curves remain unchanged.
- [x] If existing rows require `builder_type="rate_helper_bootstrap"`, accept it
  only as a compatibility alias that maps to
  `builder_type="rate_helper_curve"`.
- [x] Require persisted `builder_payload.helper_schema` for helper-based curve
  reconstruction instead of treating the schema marker as optional
  documentation; `rate_helpers@v1` covers helper key nodes plus additive
  context/provenance key nodes.

### Stage 4: Scenario Integration

Files to update:

- `src/msm_pricing/scenarios/curves/engine.py`
- `tests/msm_pricing/scenarios/curves/test_curve_scenarios.py`
- `tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py`

Tasks:

- [x] Keep scenario shock application in `scenarios.curves`.
- [x] When runtime build details indicate helper-based reconstruction, bump copied
  helper key nodes and delegate reconstruction to
  `pricing_engine.curves.reconstruction`.
- [x] Preserve existing node-based scenario behavior.
- [x] Add strict errors for missing helper fields, unsupported helper types,
  unsupported units, and missing runtime overnight indexes.
- [x] Prove scenario curve handles do not mutate persisted observations,
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
- [ ] Before deleting connector-local OIS helpers, add a parity test that
  rebuilds the existing connector fixture through the generic OIS helper path
  and compares exported observation nodes against the current connector output.
  If parity fails, extend the generic OIS surface, not the connector-local
  helper path.

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
- Keep futures helper support generic and tested independently from Valmer
  source parsing; connector migration should only map source rows into the
  generic key-node fields.
