# 0030. Explicit Portfolio Price Source Dependency

## Status

Accepted - implemented

This ADR defines the target architecture for portfolio price consumption in
`msm_portfolios`. It supersedes the current design where `PortfoliosDataNode`
builds an `InterpolatedPrices` DataNode internally from `AssetsConfiguration`.

Amendment: [ADR 0031](0031-generic-portfolio-valuation-source.md) supersedes
the `price_column: PriceTypeNames` part of this ADR. Portfolio core should
consume a generic valuation source and `valuation_column: str`, while
OHLC-specific enums remain in contributed price/bar helpers.

Implemented in the portfolio configuration contract, `PortfoliosDataNode`,
contributed signal configurations, the equal-weight portfolio example, docs,
skills, changelog, and focused portfolio tests.

## Context

`msm_portfolios` currently couples portfolio construction to price
interpolation. `PortfolioBuildConfiguration` contains an
`AssetsConfiguration`, and `AssetsConfiguration` contains `PricesConfiguration`.
During portfolio initialization, `PortfoliosDataNode` calls
`get_interpolated_prices_timeseries(...)` and creates an `InterpolatedPrices`
dependency internally.

That produces this hidden graph:

```text
+-----------------------+
| PortfolioConfiguration|
|-----------------------|
| AssetsConfiguration   |
| PricesConfiguration   |
+-----------+-----------+
            |
            | hidden construction
            v
+-----------------------+      reads       +-----------------------+
| InterpolatedPrices    |<-----------------| raw/source prices     |
| DataNode              |                  | DataNode/APIDataNode  |
+-----------+-----------+                  +-----------------------+
            |
            | hidden dependency
            v
+-----------------------+      consumes    +-----------------------+
| PortfoliosDataNode    |<-----------------| SignalWeights         |
+-----------------------+                  +-----------------------+
```

This hides a persistent price-processing DataNode and its dynamic storage table
behind portfolio configuration. It also makes portfolio extension harder because
users who already have a proper price graph cannot pass that graph directly.

The Main Sequence DataNode model is cleaner when each DataNode owns its own
update process and downstream nodes consume explicit dependencies. Persistent
price interpolation is an upstream price workflow. Portfolio construction is a
downstream calculation workflow.

## Problem

The current design has three competing sources of asset intent:

```text
SignalWeights output
  says which assets the portfolio wants to hold

Price source storage
  says which assets have market data available

AssetsConfiguration
  separately declares an asset universe and price pipeline configuration
```

This creates drift. A portfolio can end up with:

- signal weights for one universe,
- price data for a larger or smaller universe,
- a third static asset list in configuration.

The authoritative portfolio universe should come from the signal output, not
from the price table and not from `AssetsConfiguration`.

Price sources may contain more assets than the portfolio needs. That is normal.
A shared price store can contain BTC, ETH, SOL, SPY, and AAPL while one
portfolio only trades BTC and ETH. Extra prices must be ignored.

Price sources may not silently contain fewer required assets than the signal.
If a signal requires BTC and ETH, but the price source has only BTC, the
portfolio update must fail clearly unless ETH has no required exposure and no
previous holding that needs valuation or liquidation.

## Decision

`PortfoliosDataNode` will consume an explicit price source dependency. It must
not construct `InterpolatedPrices` internally.

The target graph is:

```text
                    +-----------------------+
                    | raw/source prices     |
                    | DataNode/APIDataNode  |
                    +-----------+-----------+
                                |
                                | optional upstream processing
                                v
+-----------------------+      +-----------------------+
| SignalWeights         |      | price source          |
| DataNode              |      | DataNode/APIDataNode  |
+-----------+-----------+      +-----------+-----------+
            |                              |
            | explicit dependency          | explicit dependency
            +--------------+---------------+
                           v
                 +-----------------------+
                 | PortfoliosDataNode    |
                 | portfolio calculation |
                 +-----------------------+
```

`InterpolatedPrices` remains useful, but it becomes a contributed price-source
DataNode that users build and pass explicitly. It is not owned by
`PortfoliosDataNode`.

Portfolio logic may still locally align a consumed price frame to the portfolio
rebalance index. That local alignment is part of portfolio calculation. It must
not create persistent interpolation storage or hide an upstream DataNode.

The portfolio should also make price gaps visible. If the consumed price source
has missing dates or requires local forward-fill during rebalance-index
alignment, the portfolio emits diagnostics that describe the gaps and the local
fill decisions. The interpolation part stays in the price/interpolation
DataNode.

## Current Construction Logic

The current implementation mixes portfolio calculation with price-source
construction:

```text
PortfolioConfiguration
  -> PortfolioBuildConfiguration
       -> AssetsConfiguration
            -> PricesConfiguration
                 source_time_index_meta_table_uid
                 upsample_frequency_id
                 intraday_bar_interpolation_rule

PortfoliosDataNode
  -> reads signal_weights_instance
  -> reads rebalance_strategy_instance
  -> calls get_interpolated_prices_timeseries(...)
       -> builds InterpolatedPrices internally
       -> resolves source prices from source_time_index_meta_table_uid
       -> derives configured interpolation storage
  -> declares dependencies: signal_weights + hidden bars_ts
  -> generates portfolio rebalance index
  -> interpolates signal weights to the rebalance index
  -> fetches prices for signal asset columns
  -> locally aligns consumed prices to the rebalance index
  -> applies rebalance logic
  -> calculates weights, returns, and portfolio value
```

Current responsibilities in practice:

```text
PortfoliosDataNode owns:
  - portfolio identity and output values
  - portfolio rebalance index generation
  - signal interpolation to the rebalance index
  - local price alignment for calculation
  - rebalance execution logic
  - return and portfolio value calculation

PortfoliosDataNode also currently owns, incorrectly:
  - constructing InterpolatedPrices
  - carrying source price UID in portfolio configuration
  - carrying interpolation policy in portfolio configuration
  - choosing dynamic interpolation storage through hidden construction
```

That second group is the architectural error this ADR removes.

## Target Construction Logic

The desired implementation separates price processing from portfolio
construction:

```text
Raw/source price DataNode or APIDataNode
  -> optional InterpolatedPrices DataNode
       -> owns persistent interpolation output and storage

SignalWeights DataNode
  -> owns investment intent and signal asset universe

PortfoliosDataNode
  -> receives explicit price_source_instance
  -> receives explicit signal_weights_instance
  -> receives portfolio-local price column and output frequency
  -> declares dependencies: signal_weights + price_source
  -> generates portfolio rebalance index
  -> reads signal output and derives required priced assets
  -> fetches only required assets from price_source
  -> locally aligns consumed prices to the rebalance index for calculation
  -> reports missing/stale/local-fill diagnostics when implemented
  -> applies rebalance logic
  -> calculates weights, returns, and portfolio value
```

Target responsibilities:

```text
Price/interpolation DataNode owns:
  - raw price ingestion or price normalization
  - persistent interpolation, if the user wants it
  - dynamic interpolation storage, if needed
  - source cadence and interpolation policy
  - explicit upstream source dependency resolution from either a live
    `DataNode`/`APIDataNode` instance or a registered source
    `TimeIndexMetaTable` UID

SignalWeights owns:
  - investment intent
  - signal output frame
  - candidate asset universe through get_asset_list(), when useful

PortfoliosDataNode owns:
  - portfolio calculation
  - required asset discovery from signal output and prior portfolio state
  - reading compatible prices from the explicit price source
  - local price alignment to the portfolio rebalance index
  - price quality diagnostics for the local alignment step
  - rebalance logic, fees, weights, returns, and portfolio value output
```

Portfolio local price alignment must remain a temporary calculation step. It
must not create persistent interpolation storage and must not replace the
external price/interpolation DataNode.

## Portfolio Universe Resolution

The portfolio universe is determined from signal intent.

For each update window, `PortfoliosDataNode` should derive required priced
assets from:

1. assets with non-zero signal weights in the window,
2. assets present in previous portfolio weights or holdings that still need
   valuation, return calculation, or liquidation,
3. any explicit portfolio target asset used to override the calculated
   portfolio value series.

The signal DataNode may expose a candidate universe through `get_asset_list()`.
That is useful for preflight, update statistics, and dependency setup, but the
actual signal output frame remains authoritative for the update window.

Price source semantics:

```text
signal required universe      = {BTC, ETH}
price source available assets = {BTC, ETH, SOL, SPY}
result                        = use BTC and ETH, ignore SOL and SPY

signal required universe      = {BTC, ETH}
price source available assets = {BTC}
result                        = warn/diagnose and follow alignment policy
```

Price gaps must be reported with diagnostics that name:

- missing or stale asset identifiers,
- the price source DataNode/storage identifier,
- the update date range,
- the price column requested,
- the alignment policy that was applied,
- whether the portfolio continued or failed.

The portfolio should not silently hide price quality issues. Once interpolation
is externalized, filling or accepting gaps becomes the user's price-source and
portfolio-policy responsibility. Portfolio code should surface those facts and
only fail when the configured policy says the price frame is unusable.

## Price Source Contract

A portfolio price source must be a `DataNode` or `APIDataNode` whose storage can
be read by time and `asset_identifier`.

Minimum contract:

```text
index:
  time_index
  asset_identifier

required column:
  configured price column, for example close

optional columns:
  open
  high
  low
  volume
  vwap
  trade_count
  interpolated
```

The price source may be:

- `InterpolatedPrices`,
- another `msm_portfolios` contributed price DataNode,
- a project-defined DataNode,
- an `APIDataNode` pointing to a compatible registered storage table.

`PortfolioBuildConfiguration` should store the price source instance, not a
source storage UID plus interpolation policy. If a user wants persistent
interpolation, they build that interpolation node before building the
portfolio.

`InterpolatedPrices` itself may be built from either:

- `source_price_instance`, when the raw/source price `DataNode` or
  `APIDataNode` already exists in the current graph,
- `source_time_index_meta_table_uid`, when the source is an already registered
  compatible storage table and should be attached through
  `APIDataNode.build_from_table_uid(...)`.

In both cases, `InterpolatedPrices.dependencies()` exposes the resolved source
object. The UID path is an attachment convenience; it must not hide the source
dependency once the node is constructed.

## Portfolio Configuration Boundary

Core portfolio construction should not require `AssetsConfiguration`.

Target portfolio build configuration:

```text
PortfolioBuildConfiguration
  signal_weights_instance
  price_source_instance
  price_column
  portfolio_prices_frequency
  price_alignment_policy
  execution_configuration
  rebalance_strategy_instance
```

`price_alignment_policy` covers portfolio-local behavior such as:

- reindexing prices to the portfolio rebalance index,
- reporting local forward-fill during alignment,
- whether to extend to now,
- how to report missing or stale prices,
- when missing or stale prices should fail the update.

This policy object is implemented as `PriceAlignmentPolicy`.

`AssetsConfiguration` may remain temporarily as a helper for contributed signal
or price nodes, but it should not be part of the core portfolio configuration
contract.

## Signal Boundary

Signals own investment intent. A signal should make its intended universe
discoverable through its output frame and, where useful, through
`get_asset_list()`.

Contributed signals that need prices should receive a price source explicitly.
They should not construct `InterpolatedPrices` internally.

This applies at least to:

- fixed weights,
- external weights,
- market-cap weights,
- ETF replication,
- intraday trend,
- any future signal that reads prices or market data.

Signals may depend on one price source while the portfolio consumes another,
but that must be explicit in the dependency graph.

## Consequences

Positive consequences:

- The portfolio dependency graph becomes visible and inspectable.
- Users extending portfolios can pass their own price DataNode or APIDataNode.
- Persistent interpolation storage is prepared and run as a price workflow, not
  as a side effect of portfolio construction.
- `PortfoliosDataNode` becomes focused on portfolio calculation.
- `AssetsConfiguration` stops being a third source of asset-universe truth.
- Missing and stale prices can be diagnosed against actual signal requirements
  without forcing portfolio code to own persistent interpolation.

Tradeoffs:

- Users must construct a price source explicitly.
- Examples need one more visible step.
- Existing contributed signals need refactoring because several currently
  create price nodes internally.
- Backward compatibility requires either a staged deprecation path or a clear
  breaking-change release.

Rejected alternative:

Keep `PricesConfiguration` in `PortfolioBuildConfiguration` and make it easier
to prepare dynamic interpolation storage. This improves setup mechanics but
keeps the wrong ownership boundary: portfolio construction would still own
price interpolation.

## Example Migration Scope

The examples must move with this architecture. They should not be left showing
the old hidden interpolation pattern after the core code changes.

Current example behavior:

```text
examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
  -> prepares dynamic interpolated price storage as a portfolio prerequisite

examples/msm_portfolios/portfolio_equal_weights_example.py
  -> builds AssetsConfiguration
  -> builds PricesConfiguration
  -> passes source_time_index_meta_table_uid into portfolio configuration
  -> PortfoliosDataNode internally builds InterpolatedPrices
```

Target example behavior:

```text
examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
  -> becomes a price-source preparation example only
  -> prepares or verifies the explicit InterpolatedPrices storage

examples/msm_portfolios/portfolio_equal_weights_example.py
  -> builds source prices
  -> builds or attaches InterpolatedPrices explicitly
  -> builds SignalWeights explicitly
  -> builds PortfoliosDataNode with price_source_instance and signal_weights_instance
  -> shows that the portfolio consumes only the signal-required asset subset
```

Any account or portfolio example that imports the equal-weight portfolio helper
must keep using the public helper after the refactor. It must not rebuild the
old `AssetsConfiguration`/`PricesConfiguration` path locally.

## Implementation Tasks

### Stage 1: Configuration Contract

- [x] Add a portfolio price-source field to `PortfolioBuildConfiguration`, for
  example `price_source_instance`.
- [x] Add a portfolio-local price column field, for example `price_column`, to
  replace `AssetsConfiguration.price_type` inside core portfolio construction.
- [x] Add a portfolio-local price alignment policy for forward-fill, missing
  price diagnostics, failure behavior, and rebalance-index alignment.
- [x] Remove `AssetsConfiguration` from the core `PortfolioBuildConfiguration`
  path.
- [x] Keep `AssetsConfiguration` only as a contributed helper where still
  useful, or remove it if all usages can be replaced cleanly.

### Stage 2: PortfoliosDataNode Refactor

- [x] Remove the internal call to `get_interpolated_prices_timeseries(...)` from
  `PortfoliosDataNode`.
- [x] Store the explicit price source dependency on the portfolio node during
  configuration initialization.
- [x] Update `PortfoliosDataNode.dependencies()` so it returns the explicit
  price source and the signal weights node.
- [x] Update portfolio price fetching to use the explicit price source.
- [x] Keep local price alignment to the rebalance index inside portfolio
  calculation.
- [x] Emit diagnostics when the consumed price source has missing dates, stale
  observations, or requires local forward-fill during alignment.
- [x] Make failure policy-controlled: continue when alignment can produce a
  usable frame inside tolerance, fail in strict mode or when a required asset has
  no usable price.

### Stage 3: Signal Universe And Validation

- [x] Define the canonical signal universe resolution rule in code and docs:
  signal output is authoritative; `get_asset_list()` is preflight only.
- [x] Add a helper that derives required priced assets from signal output,
  previous portfolio weights, and any portfolio value override asset.
- [x] Add clear missing-price diagnostics naming missing assets, price source,
  date range, price column, alignment policy, and continue/fail outcome.
- [x] Add tests where price source contains extra assets and portfolio ignores
  them.
- [x] Add tests where price source misses required signal assets and portfolio
  emits diagnostics while continuing under a permissive policy.
- [x] Add tests where price source misses required signal assets and portfolio
  fails under strict policy.

### Stage 4: InterpolatedPrices As Explicit Price Source

- [x] Keep `InterpolatedPrices` under the contributed price-source package.
- [x] Ensure `InterpolatedPrices` can be constructed and run independently of
  `PortfoliosDataNode`.
- [x] Ensure dynamic interpolation storage preparation remains an explicit
  price workflow step, not a portfolio side effect.
- [x] Update helper names and docs so they describe price-source preparation,
  not portfolio schema preparation.
- [x] Verify that `InterpolatedPrices` can be passed directly as the portfolio
  price source.
- [x] Verify that an `APIDataNode` pointing to compatible interpolated storage
  can also be passed as the portfolio price source.

### Stage 5: Contributed Signal Refactor

- [x] Refactor fixed-weight signal configuration so it does not require
  `AssetsConfiguration` for portfolio core behavior.
- [x] Refactor external weights so the asset universe comes from explicit
  weights or signal output, not portfolio `AssetsConfiguration`.
- [x] Refactor market-cap signals so any required market-cap or price source is
  passed explicitly as a dependency.
- [x] Refactor ETF replication so both the ETF price source and basket price
  source are explicit dependencies.
- [x] Refactor intraday trend so it receives its price source explicitly.
- [x] Remove internal calls to `get_interpolated_prices_timeseries(...)` from
  contributed signals.
- [x] Add tests proving each contributed signal exposes its dependency graph
  explicitly.

### Stage 6: Examples

- [x] Update
  `examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` so it is
  explicitly a price-source preparation example, not a portfolio-core
  bootstrap requirement.
- [x] Update `examples/msm_portfolios/portfolio_equal_weights_example.py` so it
  visibly builds source prices -> `InterpolatedPrices` -> `SignalWeights` ->
  `PortfoliosDataNode`.
- [x] Update `examples/msm_portfolios/portfolio_equal_weights_run.py` so the
  run path assumes explicit price-source preparation and does not imply
  `PortfoliosDataNode` creates interpolation storage.
- [x] Update account examples that reuse the equal-weight portfolio helper so
  they keep using the public helper instead of rebuilding portfolio price
  configuration locally.
- [x] Add a test where the price source has more assets than the signal and the
  portfolio consumes only the signal-required subset.
- [x] Add an example or test where missing or stale required prices are reported
  clearly and the portfolio continues under a permissive policy.
- [x] Add an example or test where missing required prices fail clearly under
  strict policy.
- [x] Remove examples that imply portfolio config owns price interpolation.

### Stage 7: Documentation And Skills

- [x] Update `docs/knowledge/msm_portfolios/portfolios/index.md` to document
  explicit price sources and signal-derived universe resolution.
- [x] Update tutorials to show explicit price-source construction before
  portfolio construction.
- [x] Update `mainsequence-markets-portfolio-workflow` skill to route price
  interpolation work to the price-source workflow, not portfolio core.
- [x] Update any price-source skill or docs to explain `InterpolatedPrices` as a
  reusable upstream DataNode.
- [x] Update the changelog once implementation begins.

### Stage 8: Compatibility And Removal

- [x] Decide whether to provide a temporary adapter from old
  `AssetsConfiguration`/`PricesConfiguration` to explicit `price_source_instance`.
- [x] Retain the contributed `get_interpolated_prices_timeseries(...)` helper as
  a non-core transition path; portfolio core and contributed signals no longer
  call it.
- [x] No portfolio-core adapter is provided; the core configuration change is a
  breaking contract change for this package boundary.
- [x] Remove any remaining portfolio-core references to
  `PricesConfiguration.source_time_index_meta_table_uid`.

## Completion Criteria

This ADR is complete only when:

- `PortfoliosDataNode` no longer constructs `InterpolatedPrices` internally.
- Portfolio configuration accepts an explicit price source dependency.
- The portfolio universe is derived from signal output and previous portfolio
  state, not from `AssetsConfiguration`.
- Price sources may safely contain extra assets.
- Missing and stale required prices are surfaced clearly; continuation or
  failure follows the configured alignment policy.
- Fixed weights, external weights, market-cap, ETF replication, and intraday
  trend signals no longer hide price-source construction.
- Documentation and examples show the explicit dependency graph.
