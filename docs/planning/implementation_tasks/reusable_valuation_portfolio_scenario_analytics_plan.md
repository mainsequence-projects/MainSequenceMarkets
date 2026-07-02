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

### 1. Normalized Valuation Inputs

Add a public helper for building `ValuationPosition` from normalized valuation
rows.

The public surface should live with the valuation basket API, for example under
`msm_pricing.valuation` and re-exported from `msm_pricing` only if the import
remains clear.

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

The implementation must build on:

```python
from msm_pricing.valuation import PricingValuationContext, price_scenario
```

It must not introduce a second pricing loop that bypasses
`PricingValuationContext` or duplicates `price_scenario(...)`.

The public model should represent these concepts:

```text
CurveShock
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

The scenario helper must:

- apply shocks to derived runtime handles only;
- keep `CurveTable`, `CurveBuildingDetails`, `DiscountCurvesNode`
  observations, and `key_nodes` immutable;
- use `Curve.unique_identifier` as the scenario shock key;
- keep quote side an explicit argument or context setting, not a project
  setting import;
- support strict preflight behavior by default;
- expose any diagnostic/partial-pricing mode explicitly;
- use `apply_z_spread_to_curve(...)` only for runtime overlays when a line's
  observed z-spread should be preserved under a scenario curve.

The helper may expose line-level and group-level impact frames, but those
frames are valuation outputs. They must not become portfolio source-selection
logic.

Rejected behavior:

- do not import project settings such as a local default curve quote side;
- do not silently fall back to latest observations unless the caller selects an
  explicit latest-observation policy;
- do not allow default empty shocks to be treated as objects with missing
  `parallel_bp` or `keyrate_bp` fields;
- do not catch context preparation failures and continue in normal strict
  pricing mode;
- do not mutate submitted instruments or prepared context state across
  scenarios.

### 4. Optional Fixed-Income Spread Analytics

Promote generic spread analytics as optional analytics, not core pricing
runtime.

The target package area is:

```text
msm_pricing.analytics.spreads
```

The initial helper set may include:

- spread z-score matrix construction;
- pair history frame construction;
- pair-level spread metrics;
- leg-level carry/roll/downside metrics;
- DV01 and hedge-ratio calculations;
- Ornstein-Uhlenbeck style forecast cones;
- optional AR(1)/GARCH forecast cones when optional dependencies are present.

The helpers must:

- operate on caller-supplied pandas or numpy data;
- avoid backend row reads;
- avoid project-specific asset, curve, or vendor assumptions;
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
- project-specific dirty-price, quote-side, or vendor translation assumptions.

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
- [ ] Identify existing internal or public helpers that will be consolidated to
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

- [ ] Add portfolio read services for latest weights and portfolio values.
- [ ] Add asset reference detail reads for canonical asset identity plus latest
  snapshot details.
- [ ] Consolidate overlapping private account allocation or public API query
  logic onto the new services where appropriate.
- [ ] Add tests for exact-date and latest-at-or-before policies,
  multi-portfolio isolation, identifier handling, and explicit repository
  context usage.
- [ ] Document the service boundaries in portfolio and asset docs.

### Stage 4: Curve Scenarios

- [ ] Add typed curve scenario and result models.
- [ ] Add a curve scenario helper that delegates line pricing to the existing
  prepared-context and `price_scenario(...)` path.
- [ ] Add shock application helpers for parallel and key-rate bumps without
  mutating persisted curve data.
- [ ] Add strict preflight and explicit diagnostic behavior tests.
- [ ] Add tests proving scenario handles and z-spread overlays do not leak
  across lines, scenarios, or submitted instruments.
- [ ] Document the scenario workflow in pricing docs and examples.

### Stage 5: Optional Spread Analytics

- [ ] Add the optional analytics package and packaging extra.
- [ ] Add pure-data tests for z-score matrices, pair metrics, DV01/hedge
  ratios, and forecast-cone behavior.
- [ ] Add tests for missing optional dependencies.
- [ ] Document the optional dependency boundary and add a focused example.

## Validation Requirements

Each implementation stage must run validation scaled to the touched code:

- `git diff --check`;
- focused ruff checks for touched Python modules;
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
