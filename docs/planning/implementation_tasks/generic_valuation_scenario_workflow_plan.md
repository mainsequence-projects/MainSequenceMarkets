# Generic Valuation Scenario Workflow Implementation Plan

## Status

Implemented in `msm_pricing` for the first curve-scenario-backed valuation
workflow phase. The remaining work is downstream donor refactoring in
fundcompetition.

## Success Condition

`msm_pricing` exposes a generic valuation scenario workflow that can reproduce
the reusable behavior currently prototyped in downstream
`src/valuation_workflow`, without importing downstream code, Valmer connector
code, or table-shaped dashboard/API output contracts.

The implementation is successful only when:

- callers can submit a `ValuationPosition`, one or more generic valuation
  scenarios, and an optional prepared `PricingValuationContext`;
- the workflow prepares or reuses the context once, resolves required market
  data once, builds runtime scenario overrides without mutating submitted
  instruments or persisted market data, and prices base versus scenario runs;
- line-level pricing can run in diagnostic mode, where failed lines produce
  structured diagnostics while other lines still price;
- price, analytics, cashflow, carry, and line-impact results are returned as
  typed in-memory models, not pandas `DataFrame`s;
- curve shocks are implemented by delegating to
  `msm_pricing.scenarios.curves`, not by reimplementing curve construction in
  the valuation workflow package;
- downstream fundcompetition code can refactor
  `/Users/jose/mainsequence-dev/main-sequence-workbench/projects/mexicofundcompetition-9d81d63f-b8c9-404d-9f1a-5f2ad29dbf16/src/valuation_workflow`
  into a thin wrapper that calls the new `msm_pricing` workflow and formats the
  existing DataFrame/table payloads;
- Valmer-specific overnight-index resolvers, source row parsing, curve
  identifiers, and latest-observation policies remain connector-owned adapter
  inputs, not canonical `msm_pricing` behavior.

## Context

The downstream donor module is a useful prototype:

```text
/Users/jose/mainsequence-dev/main-sequence-workbench/projects/mexicofundcompetition-9d81d63f-b8c9-404d-9f1a-5f2ad29dbf16/src/valuation_workflow
```

Its real purpose is broader than curve scenario pricing. It orchestrates a full
valuation scenario workflow for already-built `msm_pricing.ValuationPosition`
objects:

1. prepare a pricing context for a valuation date and market-data set;
2. discover which market-data curves each line needs;
3. build transient base and shocked runtime handles;
4. compute observed z-spread overlays when a line provides observed dirty
   price metadata;
5. price base and scenario runs line by line;
6. keep successful lines when other lines fail;
7. collect analytics and cashflows when instruments support them;
8. compute line impacts and carry impacts;
9. expose records that downstream dashboards and APIs turn into tables.

That is generic valuation machinery. It should live in `msm_pricing`, but not
as copied donor code. The donor currently also contains table formatting,
project metadata conventions, and Valmer resolver hooks. Those pieces should
stay outside the canonical engine.

## Non-Goals

- Do not move the donor package wholesale into `msm_pricing`.
- Do not make `msm_pricing` import `valmer_connectors`.
- Do not make the canonical engine return pandas `DataFrame`s or Command
  Center `TabularFrameResponse` payloads.
- Do not persist scenario results in this phase.
- Do not make `msm_pricing` own durable portfolio/account positions.
- Do not add equity, FX, commodity, or volatility shock implementations in the
  first implementation unless they fall out naturally as tests for the generic
  extension contract.

## Target Package Layout

Create a dedicated valuation workflow package under `msm_pricing.scenarios`.
This keeps the workflow above curve-specific scenario mechanics and leaves room
for non-curve scenario components later.

```text
src/msm_pricing/scenarios/valuation/__init__.py
src/msm_pricing/scenarios/valuation/models.py
src/msm_pricing/scenarios/valuation/engine.py
src/msm_pricing/scenarios/valuation/line_pricing.py
src/msm_pricing/scenarios/valuation/impacts.py
tests/msm_pricing/scenarios/valuation/test_line_pricing.py
tests/msm_pricing/scenarios/valuation/test_workflow.py
examples/msm_pricing/valuation_scenario_workflow.py
```

Update existing public exports and documentation:

```text
src/msm_pricing/scenarios/__init__.py
src/msm_pricing/__init__.py
docs/knowledge/msm_pricing/runtime_resolution.md
docs/knowledge/msm_pricing/instruments.md
docs/knowledge/msm_pricing/curves.md
docs/tutorial/05-pricing.md
src/msm_pricing/README.md
CHANGELOG.md
mkdocs.yml
```

Curve-specific scenario internals may need one small public split:

```text
src/msm_pricing/scenarios/curves/engine.py
src/msm_pricing/scenarios/curves/models.py
tests/msm_pricing/scenarios/curves/test_curve_scenarios.py
tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py
```

The split should expose curve runtime override preparation without forcing the
caller through strict `price_scenario(...)` pricing. Existing
`price_curve_scenario(...)` should keep working by delegating to that lower
level function.

## Public Model Shape

The canonical API should be typed, serializable, and table-adapter friendly,
but not table-shaped.

### Scenario Input

`models.py` should define a valuation-level scenario container:

```python
@dataclass(frozen=True)
class ValuationScenario:
    name: str
    curve_scenario: CurveScenario | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)
```

The first implementation should support `curve_scenario`. The model is still
valuation-level because future components can be added without putting equity,
FX, commodity, or volatility mechanics under `scenarios.curves`.

If the first implementation needs a more extensible component contract, define
it explicitly instead of hiding arbitrary dictionaries:

```python
class ValuationScenarioComponent(Protocol):
    component_type: str

    def prepare_runtime_overrides(
        self,
        position: ValuationPosition,
        context: PricingValuationContext,
        *,
        strict: bool,
    ) -> ScenarioRuntimeOverrides:
        ...
```

Do not add a generic untyped `payload` field as the primary extension point.
If a future asset-class scenario needs new inputs, it should introduce a typed
component model.

### Runtime Overrides

`models.py` should define runtime-only override models:

```python
@dataclass(frozen=True)
class ScenarioRuntimeOverrides:
    line_curve_handles: Mapping[int, object] = field(default_factory=dict)
    scenario_curve_handles: Mapping[int, object] = field(default_factory=dict)
    curve_resolutions: tuple[ResolvedLineCurve, ...] = ()
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...] = ()
```

`object` is correct for runtime handles because they are QuantLib or
engine-owned objects and must not be serialized or persisted.

### Diagnostics

`models.py` should define one diagnostic row used by all phases:

```python
@dataclass(frozen=True)
class ValuationWorkflowDiagnostic:
    stage: str
    message: str
    severity: Literal["warning", "error"] = "error"
    scenario_name: str | None = None
    line_index: int | None = None
    asset_uid: uuid.UUID | None = None
    curve_identifier: str | None = None
    role_key: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)
```

Diagnostics should be explicit enough for API/dashboard wrappers to render
tables, but the core model should not know downstream column names.

### Line Pricing Result

`line_pricing.py` should own a partial-success valuation primitive:

```python
def price_valuation_lines(
    position: ValuationPosition,
    *,
    context: PricingValuationContext | None = None,
    curve_handles_by_line: Mapping[int, object] | None = None,
    include_analytics: bool = True,
    include_cashflows: bool = True,
    strict: bool = False,
) -> ValuationRunResult:
    ...
```

Result models:

```python
@dataclass(frozen=True)
class ValuationLinePrice:
    line_index: int
    instrument_type: str
    asset_uid: uuid.UUID | None
    units: float
    unit_price: float | None
    market_value: float | None
    status: Literal["priced", "error"]
    error: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class ValuationRunResult:
    scenario_name: str
    total_market_value: float | None
    line_prices: tuple[ValuationLinePrice, ...]
    line_analytics: tuple[ValuationLineAnalytics, ...] = ()
    cashflows: tuple[ValuationCashflow, ...] = ()
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...] = ()
```

Rules:

- `strict=True` raises on the first line failure.
- `strict=False` records line failures and continues.
- `total_market_value=None` when no line priced successfully.
- submitted instruments must not be mutated;
- prepared context compatibility validation must still run;
- `metadata_json` is copied into result models, not mutated.

### Scenario Workflow Result

`engine.py` should expose:

```python
def run_valuation_scenario_workflow(
    position: ValuationPosition,
    scenarios: ValuationScenario | Sequence[ValuationScenario],
    *,
    context: PricingValuationContext | None = None,
    curve_quote_side: str | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
    include_analytics: bool = True,
    include_cashflows: bool = True,
    carry_days: int | None = None,
    strict: bool = False,
) -> ValuationScenarioWorkflowResult:
    ...
```

Result model:

```python
@dataclass(frozen=True)
class ValuationScenarioWorkflowResult:
    base: ValuationRunResult
    scenarios: tuple[ScenarioRunResult, ...]
    diagnostics: tuple[ValuationWorkflowDiagnostic, ...]
    runtime_resolutions: tuple[ResolvedLineCurve, ...] = ()
    observed_z_spread_overlays: tuple[ObservedZSpreadOverlay, ...] = ()

@dataclass(frozen=True)
class ScenarioRunResult:
    scenario: ValuationScenario
    run: ValuationRunResult
    impacts: tuple[ValuationLineImpact, ...]
    carry_impacts: tuple[ValuationCarryImpact, ...] = ()
    runtime_overrides: ScenarioRuntimeOverrides | None = None
```

The workflow should support a single scenario input for convenience, but the
result should be shaped for multiple scenarios because dashboards and APIs will
eventually run scenario grids.

## Engine Responsibilities

The canonical valuation workflow should:

1. normalize the scenario input into a tuple;
2. prepare `PricingValuationContext` once when the caller did not pass one;
3. validate caller-supplied context compatibility when one is passed;
4. compute optional observed z-spread overlays without mutating
   `ValuationLine.metadata_json`;
5. delegate curve runtime override preparation to `msm_pricing.scenarios.curves`;
6. price the base run with `price_valuation_lines(...)`;
7. price each scenario run with line-scoped runtime overrides;
8. compute line impacts from typed base/scenario line price records;
9. compute carry impacts from typed cashflow records when `carry_days` is not
   `None`;
10. aggregate diagnostics from context preparation, scenario override
    preparation, line pricing, analytics, cashflow, and impact calculations.

The workflow must not:

- create or update `Curve`, `CurveBuildingDetails`, DataNode, or MetaTable rows;
- fetch portfolios, account holdings, or assets;
- hard-code quote side, market-data-set name, curve identifier, or provider
  resolver;
- produce pandas frames;
- swallow fatal context construction errors when `strict=True`.

## Curve Component Contract

The valuation workflow should not duplicate curve scenario logic. It should use
one curve component path:

```python
prepare_curve_scenario_runtime_overrides(
    position,
    curve_scenario,
    *,
    context,
    curve_quote_side=None,
    overnight_index_resolver=None,
    strict=False,
) -> ScenarioRuntimeOverrides
```

This function may live in `src/msm_pricing/scenarios/curves/engine.py` or a
small sibling module if `engine.py` is becoming too large. It should reuse the
current `LineCurveResolution`, `CurveScenarioResult` diagnostics, z-spread
overlay handling, shared-curve scenario handle cache, and existing
`build_scenario_curve_handle(...)` implementation.

Existing public curve functions should compose with it:

- `price_curve_scenario(...)` should prepare curve runtime overrides, then
  price with strict `price_scenario(...)` semantics as it does today.
- `price_resolved_curve_scenario(...)` should keep accepting caller-supplied
  `LineCurveResolution` records.
- `run_valuation_scenario_workflow(...)` should use the same runtime override
  preparation but price through partial-success `price_valuation_lines(...)`.

## Observed Z-Spread Anchoring

The donor computes observed z-spread from `observed_dirty_price` and mutates
line metadata with `observed_z_spread`. The canonical implementation should not
mutate metadata.

Implement a typed helper:

```python
@dataclass(frozen=True)
class ObservedZSpreadOverlay:
    line_index: int
    target_dirty_price: float
    z_spread_decimal: float | None
    curve_identifier: str | None
    status: Literal["computed", "skipped", "error"]
    message: str | None = None
    metadata_json: Mapping[str, object] = field(default_factory=dict)


def compute_observed_z_spread_overlays(
    position: ValuationPosition,
    *,
    context: PricingValuationContext,
    discount_curves_by_line: Mapping[int, object] | None = None,
    strict: bool = False,
) -> tuple[ObservedZSpreadOverlay, ...]:
    ...
```

Rules:

- accept dirty price metadata through documented keys such as
  `observed_dirty_price` or `observed_dirty_ccy`;
- return `ObservedZSpreadOverlay` records with the input dirty price, computed
  spread, selected curve identity, status, and optional diagnostic message;
- expose the overlays on
  `ValuationScenarioWorkflowResult.observed_z_spread_overlays`;
- also attach the computed spread to runtime scenario resolutions or line
  override context so pricing can apply the overlay;
- do not write back to `ValuationLine.metadata_json`;
- require a prepared context when an instrument needs index/fixing hydration;
- collect diagnostics in non-strict mode.

Existing curve scenario z-spread overlay support can continue reading
`observed_z_spread_decimal` from metadata, but the valuation workflow should
prefer the typed overlay result it just computed.

## Analytics, Cashflows, And Carry

The donor collects analytics and cashflows per line and computes carry impacts.
Promote the semantics, not the table layout.

`line_pricing.py` should collect:

- unit-scaled line prices;
- raw and scaled numeric analytics when `PreparedInstrument.analytics()` exists;
- unit-scaled cashflows when `PreparedInstrument.get_cashflows()` exists.

`impacts.py` should define:

```python
def line_impacts(
    base: ValuationRunResult,
    scenario: ValuationRunResult,
    *,
    scenario_name: str,
) -> tuple[ValuationLineImpact, ...]:
    ...

def carry_impacts(
    base_cashflows: Sequence[ValuationCashflow],
    scenario_cashflows: Sequence[ValuationCashflow],
    *,
    valuation_date: dt.datetime,
    carry_days: int,
    scenario_name: str,
) -> tuple[ValuationCarryImpact, ...]:
    ...
```

The carry helper should not assume a downstream column name such as
`source_label`. It should key by `line_index` and use typed cashflow payment
dates and amounts.

## Donor Parity Map

| Donor Behavior | Canonical Owner | Donor Refactor After Upstream |
| --- | --- | --- |
| Prepare one pricing context for a position. | `run_valuation_scenario_workflow(...)` and `PricingValuationContext`. | Remove local context preparation except for adapter defaults. |
| Resolve line curve needs and selected curve handles. | `msm_pricing.scenarios.curves` runtime override preparation. | Format `runtime_resolutions` into existing requirement tables. |
| Build bumped scenario handles. | Existing `build_scenario_curve_handle(...)` through curve component. | Stop rebuilding handles locally. |
| Reuse one scenario handle for shared curves. | Curve component. | Keep only regression tests against wrapper output. |
| Price base and scenario line by line with diagnostics. | `price_valuation_lines(...)`. | Wrapper maps typed line records to existing `price_breakdown` frames. |
| Continue when a line fails. | `price_valuation_lines(strict=False)`. | Wrapper maps diagnostics to existing error frames. |
| Compute observed z-spread from observed dirty price. | `compute_observed_z_spread_overlays(...)`. | Wrapper can still accept old metadata keys and pass them through. |
| Line impacts. | `impacts.line_impacts(...)`. | Wrapper converts typed impacts to DataFrames. |
| Cashflow carry impacts. | `impacts.carry_impacts(...)`. | Wrapper preserves current dashboard column names. |
| Curve node, par curve, effective-date tables. | `msm_pricing.scenarios.curves` public diagnostics plus existing curve observation helpers. | Wrapper builds tables from typed resolutions/context; not part of core valuation engine output. |
| `records_to_frame(...)`. | No canonical owner. | Remains downstream formatting. |

## Refactor Target For Fundcompetition Donor

After the ms-markets implementation, fundcompetition should reduce
`src/valuation_workflow` to formatting and compatibility wrappers.

Expected downstream shape:

```text
src/valuation_workflow/__init__.py
src/valuation_workflow/wrappers.py
src/valuation_workflow/formatting.py
```

The wrapper should:

- accept the current fundcompetition request parameters;
- construct `ValuationScenario` and `CurveScenario` inputs;
- pass Valmer-specific `overnight_index_resolver` or connector defaults from
  Valmer-owned code;
- call `msm_pricing.scenarios.valuation.run_valuation_scenario_workflow(...)`;
- convert typed outputs into the current DataFrame/table shapes expected by
  fundcompetition dashboards and APIs;
- keep old function names only as compatibility shims if downstream callers
  still import them.

The wrapper should not:

- build curve handles;
- price line instruments directly;
- mutate line metadata;
- own generic diagnostics;
- own key-node bumping logic;
- own partial-success valuation behavior.

## Implementation Phases

### Phase 1: Public Package And Models

- Add `src/msm_pricing/scenarios/valuation/`.
- Define typed input, result, diagnostic, runtime override, line price,
  analytics, cashflow, line impact, and carry impact models.
- Add lazy exports through `msm_pricing.scenarios` and `msm_pricing`.
- Add model tests for immutability/copy behavior and JSON-compatible dict
  conversion when needed.

### Phase 2: Partial-Success Line Pricing

- Implement `price_valuation_lines(...)`.
- Reuse `PricingValuationContext.prepare_for_position(...)` when no context is
  supplied.
- Validate context compatibility when a context is supplied.
- Support line-scoped curve handles.
- Collect price, analytics, and cashflow diagnostics independently.
- Add tests for successful lines, failed lines, missing analytics, missing
  cashflows, strict mode, and no submitted-instrument mutation.

### Phase 3: Curve Runtime Override Preparation

- Split the current curve scenario engine so runtime override preparation is
  public and reusable.
- Preserve existing `price_curve_scenario(...)` and
  `price_resolved_curve_scenario(...)` behavior.
- Ensure `overnight_index_resolver` is forwarded through every high-level path.
- Add tests proving shared-curve handles are built once and z-spread overlays
  stay line-local.

### Phase 4: Valuation Scenario Workflow Engine

- Implement `run_valuation_scenario_workflow(...)`.
- Support one or many `ValuationScenario` inputs.
- Build base run and scenario runs.
- Aggregate diagnostics without losing scenario and line context.
- Compute line impacts.
- Add tests covering no-shock equals base, non-empty shock changes only
  selected lines, unresolved shocks produce diagnostics in non-strict mode, and
  strict mode raises.

### Phase 5: Observed Z-Spread Overlay Helper

- Implement non-mutating observed z-spread overlay computation.
- Document accepted metadata keys.
- Use prepared context and explicit discount/z-spread-base handles.
- Add tests for fixed-rate and indexed/floating instruments, missing curves,
  missing dirty price, and no metadata mutation.

### Phase 6: Cashflow Carry Impacts

- Implement typed carry impact calculation from `ValuationCashflow` records.
- Add tests for date-window inclusion, missing dates, multiple legs per line,
  and scenario-vs-base differences.

### Phase 7: Donor Refactor

- In fundcompetition, replace local engine calls with
  `run_valuation_scenario_workflow(...)`.
- Keep table formatting in the donor project.
- Preserve the existing dashboard/API DataFrame column names through wrapper
  tests.
- Delete donor implementations that duplicate canonical ms-markets logic.

### Phase 8: Documentation, Examples, And Changelog

- Update pricing runtime docs with the valuation workflow contract.
- Update curve docs to explain the split between curve runtime overrides and
  valuation workflow pricing.
- Add an offline example under `examples/msm_pricing/`.
- Update tutorial pricing chapter.
- Update `CHANGELOG.md`.
- Keep this implementation plan wired through `mkdocs.yml`.

## Validation Plan

Run focused checks during implementation:

```bash
.venv/bin/ruff check src/msm_pricing/scenarios/valuation tests/msm_pricing/scenarios/valuation
.venv/bin/python -m pytest tests/msm_pricing/scenarios/valuation
.venv/bin/python -m pytest tests/msm_pricing/scenarios/curves
.venv/bin/python -m pytest tests/msm_pricing/test_valuation.py
python examples/msm_pricing/valuation_scenario_workflow.py
mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
git diff --check
```

If QuantLib-dependent curve tests are skipped in a local runtime, record the
skip reason and run the non-QuantLib valuation workflow tests separately.

## Design Decisions

- The first implementation uses direct `ValuationScenario.curve_scenario`
  instead of a `ValuationScenarioComponent` protocol. The valuation workflow is
  generic at the orchestration layer, but the only implemented shock source in
  this phase is explicitly curve-based. A component protocol should be added
  only when a real non-curve scenario implementation needs it.
- Curve resolution reporting remains represented by existing
  `LineCurveResolution` and `CurveScenarioDiagnostic` models in this phase.
  Do not add a new public `CurveResolutionReport` model up front. During the
  donor refactor, wrapper code should first try to build existing
  fundcompetition requirement/effective-date tables from
  `LineCurveResolution`, `CurveScenarioDiagnostic`, `CurveScenarioResult`, and
  `PricingValuationContext`. Add a richer public report model only if that
  wrapper work proves there are missing debugging fields that cannot be
  recovered cleanly from the existing typed results and context.
- Observed z-spread overlays should be returned explicitly through
  `ValuationScenarioWorkflowResult.observed_z_spread_overlays` and also used
  internally for runtime pricing overrides. Pricing needs the computed spread
  on runtime resolutions or line overrides, but dashboards and APIs need to
  inspect the calculation itself. The explicit tuple keeps that user-visible
  calculation out of mutable line metadata and out of hidden curve-handle
  internals.
