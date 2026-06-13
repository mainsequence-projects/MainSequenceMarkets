# 0031. Generic Portfolio Valuation Source

## Status

Accepted - implemented

This ADR amends [ADR 0030](0030-explicit-portfolio-price-source-dependency.md).
ADR 0030 correctly moved portfolio construction to explicit upstream
dependencies, but it kept the core portfolio input named and typed as a
market-price column. That is too narrow for portfolio construction.

## Context

`PortfolioBuildConfiguration` currently accepts a `price_source_instance` and a
`price_column` constrained by `PriceTypeNames`:

```text
PriceTypeNames.CLOSE -> close
PriceTypeNames.OPEN  -> open
PriceTypeNames.VWAP  -> vwap
```

That works for bar-based examples, but it incorrectly makes `msm_portfolios`
look like it can only value portfolios from OHLC/VWAP market bars.

Portfolio construction does not fundamentally require OHLC data. It requires a
numeric valuation series for each asset in the portfolio universe. That
valuation can come from many sources:

```text
fair_value
mid
mark_price
nav
settlement_price
model_value
dirty_price
clean_price
custom_provider_value
```

The existing design creates a bad boundary:

```text
Portfolio core
  asks for price_column: close | open | vwap

User valuation source
  may publish any numeric value column
```

The portfolio engine should not force users to reshape a valid valuation source
into an OHLC-shaped table just to satisfy portfolio configuration.

## Decision

Portfolio core will consume a generic valuation source, not a market-bar source.

The target core contract is:

```text
PortfolioBuildConfiguration
  valuation_source_instance      DataNode | APIDataNode
  valuation_column               str = "close"
  price_alignment_policy         PriceAlignmentPolicy
  portfolio_prices_frequency     str | None
  execution_configuration
  backtesting_weights_configuration
```

`valuation_column` is a strict string column name. It defaults to `"close"` so
bar-based workflows remain natural, but it is not constrained to `close`,
`open`, or `vwap`.

The portfolio DataNode must validate the selected column against the consumed
source frame:

```text
if valuation_column not in valuation_source_frame.columns:
  fail with a clear error naming the source and available columns
```

The source frame remains asset-indexed and time-indexed. This ADR changes the
value column semantics, not the identity contract:

```text
valuation source frame
  time_index
  asset_identifier
  <valuation_column>

SignalWeights
  time_index
  signal_uid
  asset_identifier
  weight

PortfoliosDataNode
  consumes both
  calculates portfolio weights and portfolio value series
```

## Boundaries

This ADR does not make portfolio core responsible for interpolation, market-data
normalization, or provider-specific valuation construction.

Those remain upstream responsibilities:

```text
source bars / model values / vendor valuations
  -> optional upstream transformation DataNode
  -> valuation_source_instance
  -> PortfoliosDataNode
```

Contributed price helpers may keep OHLC-specific fields when they truly operate
on price bars. Portfolio core must not require OHLC enums.

Specific signals or rebalance strategies may require OHLC fields. If they do,
that requirement belongs to that signal or strategy, and the strategy must
validate it explicitly. The portfolio engine itself only requires the configured
valuation column.

## Naming

Use valuation terminology in portfolio core:

```text
price_source_instance -> valuation_source_instance
price_column          -> valuation_column
price_type            -> valuation_column
```

Avoid compatibility shims unless a later implementation decision explicitly
requires a staged migration. The preferred library direction is strict API
cleanup.

Storage names are a separate concern:

- `PortfolioWeightsStorage.price_current` and `price_before` are currently
  valuation facts, even if the names are price-specific.
- `PortfoliosStorage.close` is currently the portfolio output value, even if the
  name is market-bar-specific.

The first implementation may keep storage column names to avoid bundling this
API cleanup with a larger physical schema migration. If storage is renamed, do
it as an explicit schema task with migrations, docs, and examples.

## Target Flow

```text
+-----------------------------+
| ValuationSource DataNode    |
|-----------------------------|
| time_index                  |
| asset_identifier            |
| fair_value / close / nav    |
+--------------+--------------+
               |
               | explicit dependency
               v
+-----------------------------+       +-----------------------------+
| PortfoliosDataNode          |<------| SignalWeights DataNode      |
|-----------------------------|       |-----------------------------|
| valuation_column="fair_value"|      | signal_uid                  |
| local alignment policy      |       | asset_identifier            |
+--------------+--------------+       | weight                      |
               |                      +-----------------------------+
               v
+-----------------------------+       +-----------------------------+
| PortfolioWeightsStorage     |       | PortfoliosStorage           |
| portfolio x asset x time    |       | portfolio x time            |
+-----------------------------+       +-----------------------------+
```

## Consequences

Positive consequences:

- Users can build portfolios from non-OHLC valuation sources.
- Portfolio core becomes independent from market-bar terminology.
- Price/bar helpers stay useful without leaking their assumptions into core
  portfolio construction.
- Extension authors can publish valuation DataNodes with domain-specific column
  names and pass them directly to portfolio workflows.

Tradeoffs:

- Existing examples and docs using `price_column=PriceTypeNames.CLOSE` must be
  updated.
- Rebalance strategies that currently receive `price_type` need an interface
  cleanup.
- Some physical storage names will remain semantically awkward until a dedicated
  storage rename/migration is performed.

## Implementation Tasks

### Stage 1: Configuration Contract

- [x] Replace `PortfolioBuildConfiguration.price_column: PriceTypeNames` with
  `valuation_column: str = "close"`.
- [x] Rename `PortfolioBuildConfiguration.price_source_instance` to
  `valuation_source_instance`.
- [x] Remove `PriceTypeNames` from portfolio-core configuration imports and
  validation.
- [x] Remove `PriceTypeNames` entirely because no contributed helper still needs
  the enum after the valuation-column refactor.

### Stage 2: Portfolio DataNode Logic

- [x] Rename internal `PortfoliosDataNode.price_column` usage to
  `valuation_column`.
- [x] Validate `valuation_column` directly against the consumed source frame.
- [x] Update missing-data diagnostics to say `valuation_column` and
  `valuation_source`, not `price_column` and `price_source`.
- [x] Preserve local alignment behavior from ADR 0030, but make it valuation
  source alignment rather than price source alignment.
- [x] Ensure portfolio output still writes the existing storage schema until a
  separate storage rename is approved.

### Stage 3: Rebalance And Signal Interfaces

- [x] Update rebalance strategy interfaces from `price_type` to
  `valuation_column`.
- [x] Update contributed strategies that only need a valuation series to accept
  any numeric column.
- [x] Keep OHLC-specific validation local to strategies that truly require OHLC
  fields.
- [x] Add focused tests proving a non-OHLC valuation column drives portfolio
  returns.

### Stage 4: Examples

- [x] Update the equal-weight portfolio example to use
  `valuation_source_instance` and `valuation_column`.
- [x] Add or modify an example that uses a non-OHLC valuation column such as
  `fair_value`.
- [x] Ensure the example does not rename `fair_value` to `close` just to satisfy
  portfolio core.

### Stage 5: Documentation And Skills

- [x] Update `docs/knowledge/msm_portfolios/portfolios/index.md` to describe
  generic valuation sources.
- [x] Update tutorial text that currently implies portfolio construction is tied
  to price bars.
- [x] Update `docs/ADR/0030-explicit-portfolio-price-source-dependency.md` to
  point to this amendment.
- [x] Update the portfolio workflow skill to use valuation terminology.
- [x] Update changelog once implementation lands.

### Stage 6: API Review

- [x] Review FastAPI portfolio schemas and responses for
  `backtest_table_price_column_name` and decide whether to rename it to a
  valuation-column field.
- [x] Keep the persisted `backtest_table_price_column_name` field unchanged in
  this implementation to avoid bundling the valuation-source API cleanup with a
  physical MetaTable migration. `PortfoliosDataNode` writes the configured
  `valuation_column` into that existing field.

## Success Criteria

The refactor is complete when a user can pass a `DataNode` or `APIDataNode` with
an asset-indexed numeric column such as `fair_value`, configure:

```python
PortfolioBuildConfiguration(
    valuation_source_instance=fair_value_node,
    valuation_column="fair_value",
    ...
)
```

and run `PortfoliosDataNode` without the source needing `close`, `open`, or
`vwap`.
