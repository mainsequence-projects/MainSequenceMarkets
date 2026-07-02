# Reusable Valuation, Portfolio, Scenario, And Analytics Implementation Plan

## Status

Planned

## Success Condition

`ms-markets` promotes reusable machinery that downstream projects currently
carry in local adapter modules, without copying project-specific code or
weakening the existing package boundaries.

The implementation is successful only when:

- `msm_pricing` exposes a strict helper for constructing transient
  `ValuationPosition` inputs from normalized rows;
- `msm_portfolios` and core `msm` expose reusable read services for portfolio
  weights, portfolio values, and asset reference details instead of forcing
  dashboards or applications to compile those queries locally;
- curve-keyed scenario pricing extends the existing prepared-context and
  `price_scenario(...)` path instead of becoming a parallel pricing engine;
- fixed-income spread analytics are available as optional analytics helpers
  without adding statistical packages to the core pricing runtime;
- downstream projects can delete their local generic adapters while retaining
  their own source-specific, vendor-specific, and UI-specific code;
- docs, examples, tutorials, changelog entries, and tests describe the public
  contracts that are implemented from this plan.

## Context

Several downstream projects need the same market-library support around
valuation inputs, portfolio snapshots, scenario pricing, and fixed-income
spread analytics. One downstream project currently carries a local
`local_ms_markets` adapter module with useful prototypes:

- build a `ValuationPosition` from tabular rows;
- read latest portfolio weights, portfolio values, and asset reference details;
- price curve-keyed scenarios and produce line or portfolio impact frames;
- compute spread z-scores, hedge ratios, and forecast cones.

Those prototypes are useful evidence, but they are not a library design. Some
helpers are only thin wrappers over existing `ms-markets` APIs. Other helpers
import project settings, assume a project quote-side default, include
dashboard/DataFrame convenience behavior, or encode diagnostic behavior that is
too permissive for a reusable pricing runtime.

Existing accepted ADRs define the boundaries this work must preserve:

- [ADR 0033](../../ADR/0033-pricing-valuation-position-boundary.md) defines
  `ValuationLine` and `ValuationPosition` as transient pricing baskets.
  `msm_pricing` must not own durable account or portfolio positions.
- [ADR 0036](../../ADR/0036-prepared-pricing-valuation-context.md) defines
  `PricingValuationContext` and `price_scenario(...)` as the prepared-context
  path for portfolio and scenario valuation.
- [ADR 0035](../../ADR/0035-pricing-curve-identity-and-market-data-curve-bindings.md)
  separates curve identity, curve construction, index conventions, and
  market-data-set curve selection.
- [ADR 0031](../../ADR/0031-generic-portfolio-valuation-source.md) makes portfolio
  construction consume generic valuation sources, not only OHLC market bars.

The library should absorb the reusable machinery where it belongs, but it
should not import a downstream module, copy project defaults, or turn local UI
helpers into core API contracts.

## Plan

Implement this work as four independent promotion tracks.

## Target File Locations

The work should stay inside the owning package folders. Do not create generic
library code under downstream project-local adapter folders such as
`src/fundcompetition/local_ms_markets`.

Planned and implemented locations:

```text
Track 1: Normalized valuation inputs
  src/msm_pricing/valuation.py
  src/msm_pricing/__init__.py
  tests/msm_pricing/test_valuation.py
  examples/msm_pricing/valuation_inputs.py
  docs/knowledge/msm_pricing/instruments.md
  docs/tutorial/05-pricing.md
  src/msm_pricing/README.md

Track 2: Portfolio and asset read services
  src/msm_portfolios/services/portfolio_reads.py
  src/msm_portfolios/services/__init__.py
  src/msm/services/assets/reference_details.py
  src/msm/services/assets/__init__.py
  src/msm/services/__init__.py
  tests/msm_portfolios/services/test_portfolio_reads.py
  tests/msm/services/assets/test_reference_details.py
  examples/msm_portfolios/portfolio_read_services.py
  docs/knowledge/msm_portfolios/portfolios/index.md
  docs/knowledge/msm/assets/index.md

Track 3: Curve-keyed scenario pricing
  src/msm_pricing/scenarios/__init__.py
  src/msm_pricing/scenarios/curves/__init__.py
  src/msm_pricing/scenarios/curves/models.py
  src/msm_pricing/scenarios/curves/key_node_bumps.py
  src/msm_pricing/scenarios/curves/engine.py
  src/msm_pricing/__init__.py
  tests/msm_pricing/scenarios/curves/test_key_node_bumps.py
  tests/msm_pricing/scenarios/curves/test_curve_scenarios.py
  tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py
  examples/msm_pricing/curve_scenario.py
  examples/msm_pricing/resolved_curve_scenario.py
  docs/knowledge/msm_pricing/instruments.md
  docs/knowledge/msm_pricing/curves.md
  docs/knowledge/msm_pricing/runtime_resolution.md

Track 4: Optional spread analytics namespace
  src/msm_pricing/analytics/__init__.py
  src/msm_pricing/analytics/spreads/__init__.py
  src/msm_pricing/analytics/spreads/base.py
  src/msm_pricing/analytics/spreads/fixed_income.py
  tests/msm_pricing/analytics/spreads/test_base.py
  tests/msm_pricing/analytics/spreads/test_fixed_income.py
  examples/msm_pricing/fixed_income_spread_analytics.py
  docs/knowledge/msm_pricing/analytics.md
  pyproject.toml
```

When implementation discovers that an existing module is the better home, use
the existing module only if it keeps the same package boundary. For example,
portfolio read helpers may extend an existing `msm_portfolios.services` module
instead of creating `portfolio_reads.py`, but they must not be placed in a
dashboard, FastAPI route, or project-local adapter as the only reusable
implementation.

### 1. Normalized Valuation Inputs

Add a public helper for building `ValuationPosition` from normalized valuation
rows.

Implementation location:

```text
src/msm_pricing/valuation.py
src/msm_pricing/__init__.py
tests/msm_pricing/test_valuation.py
examples/msm_pricing/valuation_inputs.py
```

The public surface lives with the valuation basket API under
`msm_pricing.valuation` and is re-exported from `msm_pricing`.

Target usage:

```python
from msm_pricing.valuation import build_valuation_position

position = build_valuation_position(
    rows,
    valuation_date=valuation_date,
    market_data_set="eod",
)
```

The row contract is intentionally minimal:

```text
instrument      required priceable InstrumentModel
units           required finite float
asset_uid       optional canonical AssetTable.uid
metadata_json   optional caller metadata
```

The helper must:

- require an explicit `valuation_date`;
- keep `market_data_set` at the `ValuationPosition` level;
- preserve input row order in the resulting valuation lines;
- validate that `units` is finite;
- fail clearly when a required field is missing;
- accept already loaded priceable instruments, not asset identifiers.

Asset identifier resolution and current-instrument loading remain separate
steps. Callers that start from asset identifiers should use existing asset and
pricing APIs such as batch asset resolution and
`load_instruments_from_assets(...)` before constructing valuation rows.

Rejected behavior:

- do not default `valuation_date` to the current clock;
- do not resolve assets, portfolios, account holdings, or instruments inside
  this helper;
- do not add line-level market-data-set overrides;
- do not add generic `source_type` or `source_uid` fields without a separate
  ADR-backed consumer.

### 2. Portfolio And Asset Read Services

Promote reusable portfolio and asset lookup queries into package-owned services
or repositories.

Planned implementation location:

```text
  src/msm_portfolios/services/portfolio_reads.py
  src/msm_portfolios/services/__init__.py
  src/msm/services/assets/reference_details.py
  src/msm/services/assets/__init__.py
  src/msm/services/__init__.py
  tests/msm_portfolios/services/test_portfolio_reads.py
  tests/msm/services/assets/test_reference_details.py
  examples/msm_portfolios/portfolio_read_services.py
```

Portfolio-owned read services belong under `msm_portfolios`, because portfolio
weights and portfolio values are portfolio workflow outputs. Core asset
reference reads belong under core `msm`, because `AssetTable` identity and
asset snapshots are core market reference data.

Initial portfolio service contracts:

```text
latest_portfolio_weights(
  portfolio_identifiers,
  weights_date=None,
  as_of=True,
  repository_context=None,
) -> rows or DataFrame

portfolio_values(
  portfolio_identifiers,
  start=None,
  end=None,
  latest_only=False,
  limit=None,
  repository_context=None,
) -> rows or DataFrame
```

Initial asset service contract:

```text
asset_reference_details(
  asset_identifiers,
  latest_snapshot=True,
  repository_context=None,
) -> rows or DataFrame
```

The implementation must:

- use `PortfolioTable.unique_identifier` as the storage-facing
  `portfolio_identifier`;
- keep `PortfolioTable.uid` as the canonical portfolio row identity;
- read shared storage tables with portfolio-scoped filters so rows from another
  portfolio cannot affect the requested portfolio;
- support exact-date and latest-at-or-before policies explicitly;
- use an explicit repository context, executor, or service boundary instead of
  relying on hidden row-class active context;
- return market-domain rows or DataFrames, not Command Center-specific
  `core.tabular_frame@v1` payloads.

Command Center frame conversion remains a separate consumer concern. If a
widget needs a tabular-frame response, that response should be built at the
Command Center/API boundary from the service output.

Rejected behavior:

- do not place these queries in dashboards or FastAPI route handlers as the
  only reusable implementation;
- do not use `PortfolioTable.published_index_uid` as portfolio storage
  identity;
- do not combine source reads with valuation-position construction in one
  low-level helper;
- do not expose private SQLAlchemy context internals as the public API.

### 3. Curve-Keyed Scenario Pricing

Promote curve scenario machinery by extending the existing prepared-context
scenario path.

Planned implementation location:

```text
src/msm_pricing/scenarios/__init__.py
src/msm_pricing/scenarios/curves/__init__.py
src/msm_pricing/scenarios/curves/models.py
src/msm_pricing/scenarios/curves/key_node_bumps.py
src/msm_pricing/scenarios/curves/engine.py
src/msm_pricing/__init__.py
tests/msm_pricing/scenarios/curves/test_key_node_bumps.py
tests/msm_pricing/scenarios/curves/test_curve_scenarios.py
examples/msm_pricing/curve_scenario.py
```

`msm_pricing.scenarios` is a namespace, not the implementation module for this
track. Curve-keyed scenarios belong under `msm_pricing.scenarios.curves` so
future scenario families, such as equities, volatility, commodities, or credit,
can be added as sibling packages without turning one flat module into a mixed
risk-factor API.

Additional donor analysis:

- `local_valmer/curve_bumps.py` contains generic curve bump semantics:
  `CurveBumpSpec`, tenor parsing, key-rate interpolation, and empty-shock
  detection. These are not Valmer-specific and belong in `msm_pricing`.
- `local_valmer/curve_key_nodes.py` contains generic key-node mechanics:
  deriving days-to-maturity from explicit days, maturity/pillar dates, or
  tenor labels; normalizing decimal and percent rate units; bumping supported
  rate/yield fields; and converting rate/yield key nodes to runtime curve
  observation nodes. These mechanics align with existing `CurveKeyNode`
  construction provenance in `msm_pricing.data_nodes.curves.key_nodes`.
- `local_ms_markets/curve_scenario.py` contains engine-level curve-keyed
  scenario behavior that should be adapted into `msm_pricing`, but not copied
  as-is because it imports a project default quote side and contains permissive
  diagnostic fallback behavior.
- `local_ms_markets/curve_scenario.py` also contains a reusable explicit
  curve-resolution workflow that is not covered by the first
  `price_curve_scenario(...)` implementation: callers can already have
  base/scenario curve handles per position line and need generic machinery to
  price the base position and shocked position without asking
  `PricingValuationContext` to resolve or rebuild those curves again.
- `local_valmer/curve_scenarios.py` contains both a generic runtime conversion
  shape and a Valmer TIIE/OIS special rebuild. The generic conversion belongs
  in `msm_pricing`; the TIIE/OIS branch that imports
  `valmer_connectors.instruments.rates_curves` remains connector-owned.

The implementation must build on:

```python
from msm_pricing.valuation import PricingValuationContext, price_scenario
```

It must not introduce a second pricing loop that bypasses
`PricingValuationContext` or duplicates `price_scenario(...)`.

The public model should represent these concepts:

```text
CurveBumpSpec / CurveShock
  parallel_bp
  keyrate_bp
  metadata_json

CurveScenario
  name
  shocks_by_curve_identifier
  default_shock

ResolvedLineCurve
  line_index
  role_key
  selector
  curve_identifier
  base_handle
  scenario_handle

CurveScenarioResult
  base_total
  scenario_total
  impact_total
  base_breakdown
  scenario_breakdown
  line_impacts
  optional grouped impacts
  curve_shocks
  errors
```

Initial implementation may require callers to pass resolved line-curve handles
or resolved line-curve descriptors. A later implementation may add a resolver
that derives those descriptors from `PricingValuationContext` and
`PricingMarketDataSetCurveBinding`, but that resolver must preserve the
set-based preparation guarantees from ADR 0036.

The library needs two public curve-scenario workflows, not one overloaded
function:

```text
price_curve_scenario(...)
  Context-resolved workflow. The helper resolves curve rows, observations,
  build details, base handles, and scenario handles from a
  PricingValuationContext.

price_resolved_curve_scenario(...)
  Caller-resolved workflow. The caller supplies explicit line-curve
  resolutions containing base handles and optional scenario handles. The helper
  only selects the correct runtime handle per line, preserves z-spread overlays,
  delegates pricing to price_scenario(...), and reports scenario impacts.
```

Do not hide both workflows behind optional arguments on
`price_curve_scenario(...)`. The preflight contract is different: the
context-resolved workflow validates backend curve observations and build
details, while the resolved-handle workflow validates the caller-supplied
runtime handles and line-to-curve mappings.

Generic key-node bump helpers must:

- operate on copies of source key-node dictionaries and never mutate submitted
  `key_nodes`;
- parse tenor labels such as `28D`, `2W`, `3M`, and `5Y` into approximate
  days only for bump interpolation, not for persisted curve identity;
- determine days-to-maturity from `days_to_maturity`, `maturity_date`,
  `pillar_date`, or `tenor`, using the effective curve date when dates are
  present;
- normalize rate units explicitly, supporting decimal and percent values and
  rejecting missing or unsupported units;
- bump only supported rate/yield fields, such as `yield`, rate-like `quote`
  values, and `implied_rate`; price quotes such as clean prices must stay
  source-specific unless a producer provides a separate semantic adapter;
- convert bumped rate/yield key nodes into runtime curve observation nodes that
  match `CurveBuildingDetails.quote_convention` and `rate_unit`. Do not
  hardcode `zero` nodes when the runtime build details require `forward`
  quotes.

Generic scenario curve-handle construction must:

- build scenario handles from bumped key nodes through
  `build_curve_from_curve_observation(...)` or the same resolver-backed
  observation contract used by `PricingValuationContext`;
- preserve the source observation's `curve_identifier`, effective timestamp,
  `key_nodes`, and optional metadata as derived runtime state only;
- support source build details whose persisted `quote_convention` or
  `rate_unit` point at source key-node conventions only when the output
  runtime convention is explicit in `builder_payload`;
- rebuild each shocked `Curve.unique_identifier` at most once per scenario and
  reuse the handle for every line/role that selected the shared curve;
- produce line-scoped base and scenario handle maps for
  `price_scenario(...)`, instead of pricing lines in a parallel loop.

The scenario helper must:

- apply shocks to derived runtime handles and scenario key-node copies only;
- keep `CurveTable`, `CurveBuildingDetails`, `DiscountCurvesNode`
  observations, and `key_nodes` immutable;
- use `Curve.unique_identifier` as the scenario shock key;
- keep quote side an explicit argument or context setting, not a project
  setting import;
- support strict preflight behavior by default;
- expose any diagnostic/partial-pricing mode explicitly;
- use `apply_z_spread_to_curve(...)` only for runtime overlays when a line's
  observed z-spread should be preserved under a scenario curve.

The reusable machinery here is line-level curve handle selection. It should be
implemented as generic scenario machinery, not as a private project-specific
helper. Its responsibility is:

- receive all resolved curve candidates for one valuation line;
- deduplicate candidates by `Curve.unique_identifier` so a shared curve is
  shocked once and reused;
- choose the one runtime handle that can be passed through the current
  `reset_curve(...)` override contract;
- use an explicit role-preference policy, for example projection/floating
  curves before discount/z-spread-base curves for floating instruments, and
  z-spread-base or discount curves before projection curves for fixed-rate
  instruments;
- build both base and scenario line-handle maps for
  `msm_pricing.valuation.price_scenario(...)`;
- apply observed decimal z-spread overlays to the selected runtime handle only,
  without mutating the base curve, scenario curve, submitted instrument, or
  prepared context;
- fail or emit structured diagnostics when a non-empty shock exists for a
  related curve that cannot be selected under the current single-reset-curve
  instrument contract.

This selection policy is not a curve resolver and not a connector adapter. It
assumes curve rows or handles have already been resolved, and it answers only:
"given the curve candidates for this position line, which base handle and which
scenario handle should be passed to pricing?"

The helper may expose line-level and group-level impact frames, but those
frames are valuation outputs. They must not become portfolio source-selection
logic.

Rejected behavior:

- do not import project settings such as a local default curve quote side;
- do not import `valmer_connectors` or any connector package from
  `msm_pricing`;
- do not promote Valmer-specific TIIE/OIS reconstruction into the core pricing
  library;
- do not silently fall back to latest observations unless the caller selects an
  explicit latest-observation policy;
- do not allow default empty shocks to be treated as objects with missing
  `parallel_bp` or `keyrate_bp` fields;
- do not catch context preparation failures and continue in normal strict
  pricing mode;
- do not hardcode zero-rate observation nodes when `CurveBuildingDetails`
  requires forward-rate nodes;
- do not mutate submitted instruments or prepared context state across
  scenarios.

### 4. Optional Spread Analytics Namespace

Promote reusable spread analytics as optional analytics, not core pricing
runtime. `spreads` must be a namespace, not one flat fixed-income module,
because spread analytics can later cover equity pairs, index spreads,
commodity/calendar spreads, and option volatility or skew spreads.

Planned implementation location:

```text
src/msm_pricing/analytics/__init__.py
src/msm_pricing/analytics/spreads/__init__.py
src/msm_pricing/analytics/spreads/base.py
src/msm_pricing/analytics/spreads/fixed_income.py
tests/msm_pricing/analytics/spreads/test_base.py
tests/msm_pricing/analytics/spreads/test_fixed_income.py
examples/msm_pricing/fixed_income_spread_analytics.py
docs/knowledge/msm_pricing/analytics.md
pyproject.toml
```

The target package area is:

```text
msm_pricing.analytics.spreads
msm_pricing.analytics.spreads.base
msm_pricing.analytics.spreads.fixed_income
```

`base.py` is for cross-asset primitives only:

- aligned spread series construction from caller-supplied arrays/Series;
- z-score and rolling z-score matrices;
- pair history frame construction;
- pair-level statistical metrics;
- generic hedge-ratio estimation from price/return series;
- generic mean-reversion or forecast-cone helpers when the required optional
  dependencies are installed.

`fixed_income.py` is for fixed-income-specific spread analytics:

- leg-level carry/roll/downside metrics;
- DV01 and hedge-ratio calculations;
- curve-spread or z-spread relative-value metrics that depend on duration,
  DV01, yield, or curve-specific concepts.

Future modules should be siblings, not additions to `fixed_income.py`, for
example:

```text
src/msm_pricing/analytics/spreads/equity.py
src/msm_pricing/analytics/spreads/index.py
src/msm_pricing/analytics/spreads/commodities.py
src/msm_pricing/analytics/spreads/options.py
```

Option spread analytics should be asset-agnostic when possible. A commodity
option spread is still an option spread if the analytics only need option
prices, implied volatilities, deltas, expiries, and strikes; commodity-specific
convenience logic can live in a future `commodities.py` adapter if it needs
calendar, contract-roll, or underlier-specific semantics.

The helpers must:

- operate on caller-supplied pandas or numpy data;
- avoid backend row reads;
- avoid project-specific asset, curve, or vendor assumptions;
- keep cross-asset statistical primitives separate from asset-class-specific
  spread interpretation;
- keep dependency-heavy functionality behind an optional extra such as
  `ms-markets[pricing-analytics]` or `ms-markets[analytics]`;
- degrade clearly when an optional dependency such as `arch` is not installed.

Rejected behavior:

- do not add `scipy` or `arch` to the core `pricing` extra unless a separate
  packaging decision approves it;
- do not mix statistical forecast helpers into instrument pricers;
- do not make analytics helpers responsible for resolving portfolio or curve
  data from platform storage.

## Explicit Non-Promotions

The following downstream helper shapes should not be promoted as standalone
library APIs:

- thin wrappers around existing asset batch resolution APIs;
- thin wrappers around `load_instruments_from_assets(...)`;
- a separate one-line wrapper over `PreparedInstrument.z_spread(...)`;
- Command Center `core.tabular_frame@v1` normalization from arbitrary JSON into
  pandas DataFrames as part of financial market logic;
- project-specific dirty-price, quote-side, or vendor translation assumptions;
- connector-specific curve rebuilds such as Valmer TIIE/OIS construction that
  import connector packages;
- source-specific clean-price-to-rate or vendor quote translation for curve
  key nodes unless expressed as an explicit producer adapter outside core
  `msm_pricing`.

Those helpers can remain in downstream projects or be replaced by existing
library APIs. If Command Center needs generic tabular-frame parsing, that
belongs in the SDK or Command Center helper layer, not in `msm_pricing` or
`msm_portfolios` core.

## Implementation Plan

### Stage 1: Plan And Public Contract Review

- [x] Record this implementation plan.
- [ ] Confirm final public names for valuation-row construction, portfolio read
  services, asset reference details, curve scenario models, and analytics
  package extras before implementation begins.
- [x] Identify existing internal or public helpers that will be consolidated to
  avoid duplicate implementations.

### Stage 2: Valuation Inputs

- [x] Add the valuation input builder and any typed row model.
- [x] Add tests for required columns, finite units, order preservation,
  explicit valuation date, market-data-set placement, optional asset UID, and
  metadata propagation.
- [x] Document the workflow in pricing docs and the tutorial.
- [x] Add a small pricing example that builds a `ValuationPosition` from
  normalized rows.

### Stage 3: Portfolio And Asset Reads

- [x] Add portfolio read services for latest weights and portfolio values.
- [x] Add asset reference detail reads for canonical asset identity plus latest
  snapshot details.
- [x] Consolidate overlapping private account allocation or public API query
  logic onto the new services where appropriate.
- [x] Add tests for exact-date and latest-at-or-before policies,
  multi-portfolio isolation, identifier handling, and explicit repository
  context usage.
- [x] Document the service boundaries in portfolio and asset docs.

### Stage 4: Curve Scenarios

This is a large refactor and must be implemented as separate, reviewable
sub-stages. Do not land it as one opaque port from the downstream project.

#### Stage 4.1: Public Scenario Models And Import Surface

- [x] Create `src/msm_pricing/scenarios/` as a scenario namespace package, with
  `src/msm_pricing/scenarios/curves/` owning curve-specific scenario models.
  Do not put these models in a connector package, a flat catch-all module, or a
  FastAPI/dashboard layer.
- [x] Keep `src/msm_pricing/scenarios/__init__.py` domain-neutral. It may
  expose stable namespace-level conveniences later, but it must not become a
  dumping ground for equity, curve, volatility, and commodity scenario models.
- [x] Create `src/msm_pricing/scenarios/curves/models.py` for public
  curve-scenario models and lightweight result shaping.
- [x] Add `CurveBumpSpec` with fields `parallel_bp: float = 0.0`,
  `keyrate_bp: Mapping[str | int, float] = {}`, and
  `metadata_json: dict[str, Any] = {}`.
- [x] Add `CurveBumpSpec.keyrate_days_bp()` to normalize tenor/int keys to
  positive integer day keys, preserving only usable keys and rejecting invalid
  non-empty key-rate inputs with actionable errors.
- [x] Add `CurveBumpSpec.total_bp_for_days(days_to_maturity)` with linear
  interpolation across key-rate nodes and flat extrapolation outside the first
  and last key-rate maturities.
- [x] Add `CurveBumpSpec.is_empty()` with an explicit zero-basis-point
  tolerance so default/empty shocks are real no-op objects, not missing fields.
- [x] Add `CurveScenario` with `name`, `shocks_by_curve_identifier`, and
  `default_shock`. `shock_for(curve_identifier)` must key by
  `Curve.unique_identifier`, never by `Curve.uid`, index UID, role key, or
  provider-local curve name.
- [x] Add `ResolvedLineCurve` / `LineCurveResolution` with `line_index`,
  `role_key`, `selector_type`, `selector_key`, `quote_side`,
  `curve_uid`, `curve_identifier`, `base_handle`, optional
  `scenario_handle`, and optional `observed_z_spread_decimal`.
- [x] Add `CurveScenarioResult` with `base_market_value`,
  `scenario_market_value`, `market_value_delta`, `line_impacts`,
  `curve_shocks`, `errors`, and the raw `price_scenario(...)` result payload.
- [x] Re-export only stable public names from `src/msm_pricing/__init__.py`.
  Keep lower-level key-node helpers available through their owning submodule
  unless there is a clear public-user reason to re-export them.

#### Stage 4.2: Typing, Docstrings, And Public API Quality Gate

- [x] Add module docstrings to every new public module under
  `src/msm_pricing/scenarios/curves/`. The docstrings must explain the package
  boundary: `msm_pricing.scenarios.curves` owns transient curve-scenario
  runtime mechanics; `msm_pricing.data_nodes.curves` owns persisted curve data
  and key-node provenance; connector-specific curve rebuilds stay outside core.
- [x] Give every public class, method, and function exported from
  `src/msm_pricing/scenarios/curves/__init__.py` explicit typed signatures and
  return annotations. Do not expose untyped public callables.
- [x] Avoid `Any` in public signatures. If `Any` is unavoidable for QuantLib
  handles, backend row objects, or duck-typed observations, keep it at the
  boundary and document the accepted object shape in the docstring.
- [x] Add class docstrings for `CurveBumpSpec`, `CurveScenario`,
  `ResolvedLineCurve` / `LineCurveResolution`, and `CurveScenarioResult` that
  state identity rules, units, mutability expectations, and whether the model is
  an input, an internal resolution record, or an output.
- [x] Add method/function docstrings for `is_empty()`,
  `keyrate_days_bp()`, `total_bp_for_days(...)`, `shock_for(...)`,
  `tenor_to_days(...)`, `bump_key_nodes(...)`,
  `key_nodes_to_curve_observation_nodes(...)`, scenario-handle construction,
  and `price_curve_scenario(...)`.
- [x] In those docstrings, state units explicitly: bumps are basis points,
  output curve rates are decimal rates, percent key-node inputs are normalized
  to decimals, and tenor-to-day conversion is approximate runtime support rather
  than a persisted convention.
- [x] In those docstrings, state mutation behavior explicitly: submitted
  instruments, prepared valuation contexts, persisted curve observations, and
  submitted key-node dictionaries must not be mutated.
- [x] Public result models must document which fields are base valuation,
  scenario valuation, diagnostics, and raw delegated `price_scenario(...)`
  payloads.
- [x] Treat docstring, typing, and public export review as a blocking
  acceptance gate for Stage 4. The implementation is not complete if the
  behavior works but the public API is undocumented or partially typed.

#### Stage 4.3: Generic Key-Node Bump Mechanics

- [x] Create `src/msm_pricing/scenarios/curves/key_node_bumps.py` for
  source-key-node bump mechanics that are generic across curve producers and
  specific to curve-scenario construction.
- [x] Implement `tenor_to_days(tenor)` for labels like `28D`, `2W`, `3M`, and
  `5Y`. The conversion is approximate and must be documented as scenario
  interpolation support only, not a persisted curve convention.
- [x] Implement `key_node_maturity_date(node)` to read `maturity_date` or
  `pillar_date` and normalize timestamp-like values to UTC datetimes.
- [x] Implement `key_node_days_to_maturity(node, effective_curve_date=...)`
  with this precedence: explicit `days_to_maturity`, maturity/pillar date
  minus effective curve date, then tenor label.
- [x] Implement rate-unit helpers that accept only explicit `decimal` /
  `decimals` and `percent` / `percentage` units. Missing units must fail
  instead of silently assuming decimals.
- [x] Implement `key_node_decimal_rate(node)` for supported rate/yield fields:
  `yield`, rate-like `quote` values where `quote_type` is a rate convention,
  and `implied_rate`.
- [x] Implement `bump_key_node_rate(node, bump_bp=...)` and
  `bump_key_nodes(key_nodes, bump_spec, effective_curve_date=...)` as copy-based
  transforms. They must return new dictionaries and leave submitted key-node
  objects unchanged.
- [x] Reject unsupported quote shapes such as clean prices in the generic
  helper. Clean-price-to-rate conversion is source/vendor interpretation and
  belongs in a producer or connector adapter.
- [x] Implement `key_nodes_to_curve_observation_nodes(...)` that converts
  bumped rate/yield key nodes into resolver-compatible observation nodes using
  the runtime `CurveBuildingDetails.quote_convention`:
  `zero_rate` produces `{"days_to_maturity": ..., "zero": ...}` and
  `forward_rate` produces `{"days_to_maturity": ..., "forward": ...}`.
- [x] Implement a small helper to derive runtime build details when persisted
  build details use source placeholders such as `quote_convention="key_node_quote"`
  or `rate_unit="key_node_unit"`. Runtime output convention/unit must come from
  explicit `builder_payload` keys; missing output convention/unit must fail.
- [x] Export key-node bump helpers from
  `src/msm_pricing/scenarios/curves/__init__.py` only after the helper contract
  is tested. Do not export them from `msm_pricing.data_nodes.curves`; they are
  scenario mechanics, not DataNode storage contracts.

#### Stage 4.4: Scenario Curve Handle Construction

- [x] Create `src/msm_pricing/scenarios/curves/engine.py` for handle
  construction and prepared-context integration. This module may import
  QuantLib, `CurveBumpSpec`, `PricingValuationContext`,
  `build_curve_from_curve_observation(...)`, and `apply_z_spread_to_curve(...)`.
  It must not import project settings or connector packages.
- [x] Add a helper that builds one scenario curve handle from a `Curve` row,
  `CurveBuildingDetails`, one curve observation, a `CurveBumpSpec`, and an
  effective curve date.
- [x] For empty shocks, reuse the base handle rather than rebuilding an
  equivalent curve.
- [x] For non-empty shocks, read source `key_nodes` from the already prepared
  curve observation, apply copy-based key-node bumps, convert the bumped
  key nodes to runtime observation `nodes`, then call
  `build_curve_from_curve_observation(...)`.
- [x] Preserve base observation data as immutable input. The scenario
  observation object may include copied bumped `key_nodes`, runtime `nodes`,
  original `curve_identifier`, original/effective timestamp, and copied
  metadata, but it must not be written back to storage.
- [x] Build each distinct shocked `Curve.unique_identifier` at most once per
  scenario. Multiple lines, roles, or selectors that resolve to the same curve
  must share the same scenario handle.
- [x] Leave connector-specific rebuilds, including Valmer TIIE/OIS curve
  construction, outside `msm_pricing`. If a connector needs that behavior, it
  should call the generic scenario API with connector-built scenario handles or
  a connector-owned handle builder.
- [x] Export stable curve-scenario helpers from
  `src/msm_pricing/scenarios/curves/__init__.py` after naming is finalized.
  Package-level `msm_pricing` exports are optional conveniences and should be
  limited to the user-facing entry point.

#### Stage 4.5: Integration With Prepared Valuation Context

- [x] Add a public helper, tentatively `price_curve_scenario(...)`, that accepts
  a `ValuationPosition`, a `CurveScenario`, and either a prepared
  `PricingValuationContext` or enough arguments to prepare one once.
- [x] The helper must call `PricingValuationContext.prepare_for_position(...)`
  at most once when no context is provided.
- [x] The helper must validate a provided context with
  `context.validate_position_compatibility(position)` before constructing
  scenario handles.
- [x] The helper must derive or accept line-curve resolutions and produce the
  two maps required by existing `price_scenario(...)`:
  `line_curve_handles={line_index: ...}` and
  `scenario_curve_handles={line_index: ...}`.
- [x] The helper must forward generic OIS helper reconstruction context such as
  `overnight_index` and `overnight_index_resolver` into scenario handle
  construction instead of forcing connectors to use a local scenario workaround.
- [x] The helper must delegate actual base/scenario line pricing to
  `msm_pricing.valuation.price_scenario(...)`. It must not duplicate the
  pricing loop from the downstream donor module.
- [x] If only one reset curve can be applied to a line with the current
  `price_scenario(...)` override contract, selection must be explicit and
  deterministic, for example role preference
  `projection`, `floating`, `discount`, `z_spread_base` for floating/indexed
  instruments and `z_spread_base`, `discount`, `projection`, `floating` for
  fixed-rate instruments.
- [x] Do not silently drop a non-empty shocked related curve that cannot be
  applied to a line. Strict mode must raise; diagnostic mode may collect a
  structured warning/error.
- [x] Apply `apply_z_spread_to_curve(...)` only to runtime handles when a line
  provides an observed decimal continuous z-spread. Do not modify persisted
  curve observations or submitted instruments.

#### Stage 4.6: Strict Preflight And Diagnostic Mode

- [x] Strict mode is the default. It must fail before pricing when a non-empty
  curve shock has no matching curve resolution, no base handle, no curve row,
  no build details, no prepared observation, no usable `key_nodes`, unsupported
  rate units, unsupported quote types, or missing output runtime
  quote-convention/unit.
- [x] Add an explicit diagnostic mode, for example
  `diagnostic_mode="collect"` or `strict=False`, only if needed. Diagnostic
  mode must be visible at the call site and must return structured `errors`
  with `stage`, `line_index`, `curve_identifier`, `role_key`, `severity`, and
  `message`.
- [x] Context preparation failures must not be swallowed in normal strict mode.
  The downstream donor behavior that continues after a pricing-context error is
  acceptable only as explicit diagnostic behavior.
- [x] Missing latest observations must not silently fall back to another date.
  Any latest-at-or-before policy must be explicit and must report the effective
  curve date used for each scenario handle.

#### Stage 4.7: Test Plan

- [x] Add `tests/msm_pricing/scenarios/curves/test_key_node_bumps.py` covering:
  tenor parsing; positive-day validation; maturity-date and pillar-date
  resolution; UTC date normalization; decimal and percent normalization;
  missing/unsupported unit failures; parallel bumps; interpolated key-rate
  bumps; copy/no-mutation behavior; supported `yield`, rate-like `quote`, and
  `implied_rate` fields; rejected clean-price quote fields; zero-rate node
  output; and forward-rate node output.
- [x] Add `tests/msm_pricing/scenarios/curves/test_curve_scenarios.py`
  covering: empty scenario no-op behavior; one shocked curve shared across
  multiple lines/roles; missing scenario handle strict failure;
  connector-import exclusion; project-setting import exclusion; z-spread
  overlay applied only to runtime handles; no mutation of submitted
  instruments; no mutation of prepared context caches; no mutation of submitted
  key nodes; and delegation to `price_scenario(...)`.
- [x] Add a regression test that proves a non-empty shock for a curve resolved
  by multiple line roles rebuilds one scenario handle and reuses it by
  `Curve.unique_identifier`.
- [x] Add a regression test that proves the helper does not hardcode `zero`
  observation nodes when build details require `forward_rate`.
- [x] Add a regression test that proves Valmer-specific TIIE/OIS reconstruction
  is not imported or referenced from `msm_pricing`.
- [x] Keep tests offline where possible by using fake `Curve`,
  `CurveBuildingDetails`, observations, and simple instruments. Use platform
  integration tests only if the implementation truly needs backend resolution.

#### Stage 4.8: Documentation, Example, And Changelog

- [x] Document the user-facing curve scenario workflow primarily in
  `docs/knowledge/msm_pricing/curves.md`. Add a dedicated section for curve
  scenario inputs, `Curve.unique_identifier` shock lookup, supported key-node
  rate fields, supported rate units, unsupported source quote conversions,
  parallel bumps, key-rate interpolation, runtime output nodes, and the
  connector boundary.
- [x] Document prepared-context integration in
  `docs/knowledge/msm_pricing/runtime_resolution.md`: curve scenarios create
  transient runtime handles layered on top of `PricingValuationContext`, do not
  mutate market-data-set bindings, and delegate line pricing to
  `price_scenario(...)`.
- [x] Document the instrument/user workflow in
  `docs/knowledge/msm_pricing/instruments.md`: build a `ValuationPosition`,
  prepare or pass a `PricingValuationContext`, create a `CurveScenario`, call
  `price_curve_scenario(...)`, and interpret `CurveScenarioResult`.
- [x] Add a short package-level pointer in `src/msm_pricing/README.md` showing
  the public import path under `msm_pricing.scenarios.curves` and explaining
  when to use it instead of calling `price_scenario(...)` directly.
- [x] Update `docs/tutorial/05-pricing.md` with the minimal user workflow once
  the API names are final, linking to the concept docs and example.
- [x] Add `examples/msm_pricing/curve_scenario.py` showing a small offline
  scenario with a prepared position, one curve keyed by
  `Curve.unique_identifier`, a parallel bump, generated scenario handles, and a
  call that ultimately delegates to `price_scenario(...)`.
- [x] Keep public docstrings as the API-reference source for the new models and
  helpers. The prose docs should explain workflows and boundaries; docstrings
  should explain signatures, argument units, return values, mutation behavior,
  and failure modes.
- [x] Add a changelog entry only when the public code is implemented, not for
  this planning expansion alone.

#### Stage 4.9: Resolved Curve Scenario Pricing Entry Point

The initial curve-scenario implementation covers the context-resolved workflow.
Downstream projects also need a generic caller-resolved workflow where a
position already has explicit base and scenario curve handles per line. This is
the reusable part of the downstream `local_ms_markets/curve_scenario.py` file
that should still move into `msm_pricing`.

Target public function and input types:

```python
from collections.abc import Mapping, Sequence
from typing import TypeAlias

from msm_pricing.scenarios.curves import (
    CurveScenario,
    CurveScenarioResult,
    LineCurveResolution,
)
from msm_pricing.valuation import PricingValuationContext, ValuationPosition

LineCurveResolutionInput: TypeAlias = (
    Sequence[LineCurveResolution]
    | Mapping[int, LineCurveResolution | Sequence[LineCurveResolution]]
)


def price_resolved_curve_scenario(
    position: ValuationPosition,
    scenario: CurveScenario,
    *,
    line_curve_resolutions: LineCurveResolutionInput,
    context: PricingValuationContext | None = None,
    curve_quote_side: str | None = None,
    strict: bool = True,
) -> CurveScenarioResult:
    ...
```

`LineCurveResolutionInput` accepts either a flat sequence of typed
`LineCurveResolution` records or a mapping keyed by `line_index` for callers
that already group curve roles per position line. The implementation must
normalize this input into `dict[int, tuple[LineCurveResolution, ...]]` before
building the base and scenario handle maps for `price_scenario(...)`.

Implementation requirements:

- [x] Add `price_resolved_curve_scenario(...)` under
  `src/msm_pricing/scenarios/curves/engine.py` and export it from
  `src/msm_pricing/scenarios/curves/__init__.py`.
- [x] Add a concrete public type alias for `LineCurveResolutionInput` or an
  equivalent explicitly typed input model. Do not document or implement this
  API with an untyped `resolutions` placeholder.
- [x] Keep `price_curve_scenario(...)` as the context-resolved entry point.
  Do not add a hidden optional mode to it for explicit resolved handles.
- [x] Reuse the existing `ResolvedLineCurve` / `LineCurveResolution` model as
  the caller-supplied descriptor, or add a clearly named sibling model only if
  the explicit-handle workflow needs different required fields.
- [x] Accept a sequence or mapping of line-curve resolutions that can represent
  multiple curve roles per line, including shared curves used by several
  lines.
- [x] Validate in strict mode that each non-empty shocked selected curve has a
  `scenario_handle`; diagnostic mode may fall back to the base handle only with
  an explicit structured diagnostic.
- [x] Extract the current role-selection logic from the context-resolved path
  into a shared internal helper, for example
  `_line_curve_handle_maps_from_resolutions(...)`, so both public workflows
  select handles with the same policy.
- [x] Use the downstream explicit-handle selection workflow as behavioral
  evidence, but remove project-specific concerns: no project default quote side
  import, no permissive context-failure fallback, and no DataFrame-specific
  result contract in the core selection helper.
- [x] Selection must be deterministic and documented. For floating/indexed
  instruments prefer `projection`, `floating`, `discount`,
  `z_spread_base`; for fixed-rate instruments prefer `z_spread_base`,
  `discount`, `projection`, `floating`.
- [x] Preserve observed z-spread overlays by applying
  `apply_z_spread_to_curve(...)` to the selected base/scenario runtime handles
  immediately before building the maps passed to `price_scenario(...)`.
- [x] Delegate all pricing to `msm_pricing.valuation.price_scenario(...)`.
  Do not reintroduce the downstream parallel pricing loop that prepares and
  prices lines itself.
- [x] Return the same `CurveScenarioResult` shape as the context-resolved
  workflow so consumers can compare base/scenario market value, line impacts,
  curve shocks, diagnostics, and raw delegated payload consistently.

Resolved workflow preflight requirements:

- [x] Fail clearly when `line_curve_resolutions` contains no curves but the
  scenario has a non-empty default shock.
- [x] Fail clearly when a non-empty shock names a curve identifier that is not
  present in any supplied resolution.
- [x] Fail clearly when a selected shocked curve has no scenario handle.
- [x] Emit a structured diagnostic when a non-selected related curve has a
  non-empty shock that cannot be applied through the single `reset_curve(...)`
  override available to the instrument.
- [x] Keep strict mode as the default. Any diagnostic/partial-pricing behavior
  must be visible at the call site with `strict=False`.

Tests:

- [x] Add `tests/msm_pricing/scenarios/curves/test_resolved_curve_scenarios.py`
  covering an empty no-op scenario, a single shocked curve, one shared shocked
  curve reused across multiple lines, multiple roles on one line, missing
  scenario handle strict failure, non-selected shocked related-curve
  diagnostics, and observed z-spread overlay isolation.
- [x] Add a regression test that proves `price_resolved_curve_scenario(...)`
  does not prepare or resolve backend curve observations when explicit handles
  are supplied.
- [x] Add a regression test that proves the resolved workflow and the
  context-resolved workflow produce equivalent delegated `price_scenario(...)`
  inputs when given equivalent `ResolvedLineCurve` records.

Documentation and example:

- [x] Document the two-workflow choice in
  `docs/knowledge/msm_pricing/runtime_resolution.md`: use
  `price_curve_scenario(...)` when `msm_pricing` should resolve/build curves
  from a prepared context; use `price_resolved_curve_scenario(...)` when an
  application or connector already produced explicit base/scenario handles.
- [x] Add an example at `examples/msm_pricing/resolved_curve_scenario.py`
  showing a small offline position, explicit base/scenario curve handles,
  `LineCurveResolution` records, and a call to
  `price_resolved_curve_scenario(...)`.
- [x] Update downstream migration guidance so project-local files like
  `local_ms_markets/curve_scenario.py` can become compatibility wrappers or be
  removed after the resolved entry point is available.

### Stage 5: Optional Spread Analytics

- [x] Add the optional analytics package, spread namespace, and packaging extra.
- [x] Add cross-asset spread primitives under
  `src/msm_pricing/analytics/spreads/base.py`.
- [x] Add fixed-income-specific spread analytics under
  `src/msm_pricing/analytics/spreads/fixed_income.py`.
- [x] Add pure-data tests for z-score matrices, pair metrics, generic hedge
  ratios, fixed-income DV01 hedge ratios, and forecast-cone behavior.
- [x] Add tests for missing optional dependencies.
- [x] Document the optional dependency boundary, cross-asset spread namespace,
  fixed-income module boundary, and future sibling module policy.
- [x] Add a focused fixed-income spread analytics example.

## Validation Requirements

Each implementation stage must run validation scaled to the touched code:

- `git diff --check`;
- focused ruff checks for touched Python modules;
- explicit review that new public functions, classes, methods, and exports have
  typed signatures, return annotations, and docstrings covering units,
  mutation behavior, failure modes, and connector boundaries;
- focused pytest coverage for the implemented behavior;
- `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site` when docs
  or MkDocs navigation change;
- example smoke checks when examples are added or changed.

The complete plan implementation is not finished until documentation, examples,
tutorials, changelog entries, and tests are aligned with the public APIs that
were actually implemented.

## Consequences

Positive consequences:

- downstream projects can depend on stable `ms-markets` services instead of
  maintaining local generic adapters;
- pricing retains a clear transient valuation boundary;
- portfolio composition and portfolio storage reads remain owned by
  `msm_portfolios`;
- curve scenarios reuse the prepared-context architecture instead of
  fragmenting pricing behavior;
- statistical analytics stay available without bloating the core runtime.

Tradeoffs:

- the work must be implemented in several packages rather than copied as one
  folder;
- public names and return shapes need deliberate review before code changes;
- curve scenarios require careful tests around mutable QuantLib handles and
  scenario isolation;
- optional analytics packaging adds dependency and documentation maintenance.
