# 0065. Every Portfolio Keeps A Ledger

## Status

Proposed (2026-11-24). Drafted at the owner's request on 2026-11-24, from the analysis of
[issue #133](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/133).
Nothing in it is implemented.

- The decisions marked (owner) were made by the owner on 2026-11-24. Everything else is a
  proposal.
- It would supersede two sections of
  [ADR 0042](0042-position-cash-flow-portfolio-accounting.md), "Backward Compatibility:
  Mandatory Release Contract" and "Disabled Accounting Preserves Configuration And
  Identity", and its rule that the weight-return engine is the default without accounting
  configuration.
- It would amend [ADR 0059](0059-portfolio-currency-fx-and-drifting-weights.md): decision 5
  (weights drift in the weights-only path) is removed, decision 3 loses its weights-only
  refusal, and its note on a ledger portfolio's two sizes is settled by decision 7 here.
- It would amend [ADR 0058](0058-trade-at-the-next-observed-price.md), decision 6: nothing
  is left to refuse an accounting configuration.
- It would amend [ADR 0060](0060-producers-publish-markets-reads-only-its-own-tables.md):
  `run_portfolio` runs the ledger (decision 6 here).
- It settles two of the known gaps of
  [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md): a ledger
  portfolio has two sizes, and a weights-only portfolio has none.

## Context

A portfolio comes in two kinds today. Both share the signal, the rebalance strategy and
`PortfolioRebalance`, which records the fills, and the ledger books exactly those fills
(ADR 0058, decision 6). They differ after the fills:

| | Without a ledger | With a ledger |
| --- | --- | --- |
| Run by | `run_portfolio`: `PortfolioWeights`, then `PortfoliosUpdater` | `PortfolioEngine` |
| Size | a book in units; bar strategies state `total_notional` | `initial_nav`, in the portfolio's currency |
| Books | the fills, and a commission on turnover | the fills, their execution costs, and what its lifecycle models book: dividends, coupons, funding, exercise, expiry, settlement |
| Output | weights and values, published to Markets' `PortfolioWeightsTS` and `PortfoliosTS` | the event ledger, in the producer's own table |

The first kind came first. ADR 0042 added the ledger as an option: leaving
`accounting_configuration` empty keeps the first kind, and the portfolios that existed then
had to keep their identity and history. The owner said on 2026-11-18 that there are no real
portfolios yet. The code calls `PortfoliosUpdater` "the legacy weight-only valuation path"
(`src/msm_portfolios/time_index/portfolios/__init__.py:105`).

A valuation source's prices are at the level its producer chose, adjusted for events or not.
Adjusted prices are the common case, and any asset can have them (owner). They already
carry every cash flow the asset pays, as if reinvested, and its splits: a stock's dividends,
a bond's coupons. Nothing else has to book those events. With unadjusted prices, both kinds
hide the same error:

- **Without a ledger,** nothing books a dividend. The price falls by it, and so does the
  value, with no error.
- **With a ledger and no dividend model,** the same happens.
  `lifecycle_event_model_instances` is empty by default
  (`src/msm_portfolios/accounting/configuration.py:52`), and nothing checks that a held
  asset's events have a model. ADR 0042's rule that missing inputs are errors covers only
  the models that are configured.
- **A matured bond** keeps its last price for ever in both. The value is marked
  `valuation_stale` with a warning (ADR 0058), not refused.

The ledger can't replace the first kind today:

- **It publishes nothing.** `project_portfolio_values`, `project_state` and
  `project_cash_flows` (`src/msm_portfolios/accounting/projections.py`) are called only by an
  example. `PortfolioStateTS` and `PortfolioCashFlowsTS` exist, and nothing writes them.
  ADR 0042 lists these projections as remaining work.
- **Nothing runs it.** `run_portfolio` refuses a ledger portfolio
  (`src/msm_portfolios/recipes.py:248`). Only examples and tests run `PortfolioEngine`.
- **A bar strategy gives it two sizes.** `initial_nav` sizes the ledger and
  `total_notional` sizes the strategy's book, and nothing says which wins (ADR 0059).

## Decision

### 1. Every portfolio keeps a ledger (owner)

There is one kind of portfolio, the one ADR 0042 calls position-aware. `PortfolioEngine`
books every portfolio. The portfolio without a ledger is retired, with every mechanism that
serves only it (decision 9).

`PortfolioBuildConfiguration.accounting_configuration` is required. A configuration without
it is refused like any configuration that lacks a required field. Nothing refuses an empty
one by name.

### 2. A portfolio refuses to run while it holds an asset with an event nothing books (owner)

Before it books anything, a run checks every asset the portfolio holds or is about to buy.
Every event that asset can have must be booked, either by a lifecycle model or by the price
(decision 4). Otherwise the run refuses, names each asset and event type that nothing books,
and writes nothing.

The run learns which events an asset can have from the asset's type (owner). Each asset
type states the event types its assets can have: for example dividends and splits for an
equity, coupons and redemption for a bond, exercise and expiry for an option. Markets' asset
type registry (`AssetTypeTable`) carries them.

- The run refuses an asset whose type has an event type nothing books.
- It needs no event data, so a missing row can't hide an event.
- On adjusted prices, the default (decision 4), the price books every cash flow and split,
  whatever the asset type. A stock needs no dividend model and a bond no coupon model, and
  the run doesn't refuse them.
- On unadjusted prices, an asset needs a model for each cash flow its type lists, even if it
  never pays. A dividend model whose source has no rows for a stock books nothing, which is
  right.
- An event that ends a position always needs a model, at either price level: a bond's
  redemption, an option's exercise or expiry. No price turns the position into cash.

### 3. Prices stay at their source's level (owner)

A valuation source's prices are at the level its producer chose, adjusted or unadjusted.
A price source never adjusts the prices it takes: `InterpolatedPrices` uses them as they
are.

### 4. The price source says which events its prices include

The level is a fact of the prices, so the source states it, not the portfolio. It is a
setting of the valuation source, `events_in_price`:

- `"adjusted"`, the default, means the prices carry every cash flow and split of the asset,
  for any asset type.
- A tuple names exactly the event types the prices carry: `("split",)` for prices adjusted
  for splits only, and `()` for unadjusted prices.

How the setting applies:

- For `InterpolatedPrices`, the setting describes the bars it reads. It passes the setting
  on and still adjusts nothing (decision 3).
- An event that ends a position is never in a price (decision 2), so `"adjusted"` doesn't
  cover it, and a tuple that names one is refused.
- An event type is booked when a lifecycle model books it or the source's
  `events_in_price` covers it.
- A configuration that does both for one event type is refused, because the event would be
  counted twice.

### 5. The ledger publishes the portfolio's weights and values

Projections of the ledger publish to Markets' `PortfolioWeightsTS` and `PortfoliosTS`,
through `PortfolioWeightsSeries` and `PortfolioValuesSeries` (ADR 0060). Each is a published
node, as `PortfolioWeights` and `PortfoliosUpdater` are today. Each reads the ledger, not the
rebalance state.

- **Values.** `close` is the NAV divided by `initial_nav`, so a portfolio starts at 1 as
  today. `return_` is its change, and `valuation_stale` comes from the ledger's stale
  valuations (ADR 0058). `project_portfolio_values` already computes `close`, the return and
  `calculated_close`.
- **Weights.** Each ledger event that changes a position gets a row for each asset. `weight`
  is the position's value divided by the NAV after the event. The price and volume columns
  keep their meaning.
- `PortfolioWeightsTS.held_shares` and `book_cash` are dropped. Only `PortfoliosUpdater`
  reads them, and the ledger holds the quantities.

### 6. `run_portfolio` runs the ledger

`run_portfolio` runs one portfolio's chain in order: prices, calendar events, rebalance,
`PortfolioEngine`, weights, values. It creates or updates the `Portfolio` row and answers as
it does today. `portfolio_preflight` no longer refuses a ledger portfolio.

### 7. One size: `initial_nav`

With a ledger, the book's unit is the NAV at the first rebalance, which is `initial_nav`
(ADR 0059, decision 3). `RebalanceStrategyBase.book_unit_value` already returns it.

- `SizedBarStrategy.total_notional` is retired. Its strategies take their size from
  `initial_nav`, as `ImmediateSignal` and `TimeWeighted` do with a ledger.
- A fixed-amount negative cash limit is allowed for every portfolio.

### 8. Costs come from the strategy's execution cost models

`PortfolioBuildConfiguration.execution_configuration` and its `commission_fee` (default
0.00018 of turnover) are retired. `PortfoliosUpdater` is their only reader. The ledger books
the costs of the strategy's `execution_cost_model_instances`. A portfolio that wants the old
fee states `ProportionalExecutionCostModel(rate=0.00018)`.

### 9. What is removed, in the same change

- `PortfoliosUpdater`, with its valuation from the rebalance book or from constant weights
  (`_calculate_portfolio_returns`, `_has_book`, `_book_cash_as_of`) and its refusal of
  accounting configurations.
- `PortfolioWeights`' projection from the rebalance state, which decision 5 replaces.
- The signal's price override, `get_asset_uid_to_override_portfolio_price`. Only
  `PortfoliosUpdater` reads it, and no signal overrides it.
- `total_notional` (decision 7), `execution_configuration` (decision 8), and the `None`
  case of `book_unit_value`.
- The refusal of a fixed-amount limit without accounting
  (`src/msm_portfolios/configuration.py:609`).
- Every example, test, guide and skill that builds a portfolio without a ledger is given one:
  `examples/`, `tests/`, `docs/knowledge/`, `docs/tutorial/` and `.agents/skills/ms_markets/`.
  The pinned identities in `tests/identity` are updated on purpose.

A new Alembic revision drops `PortfolioWeightsTS.held_shares` and `book_cash`, which revision
0030 added.

## Worked Example

A portfolio of $1,000,000 holds half AAPL and half MSFT. AAPL is at $200, so the portfolio
holds 2,500 shares. AAPL pays a dividend of $0.25 a share. An adjusted price carries it,
reinvested. An unadjusted close falls by about $0.25.

| Prices and models | Today | Under this ADR |
| --- | --- | --- |
| Adjusted (the default), no dividend model | The price carries the dividend, in both kinds. | Runs. The price carries the dividend, and nothing else books it. |
| Unadjusted (`events_in_price=()`), no dividend model | The value falls about $625 (0.000625 of the book) with no error, in both kinds. | Refused: AAPL and MSFT, dividend. Both are equities, whether or not MSFT paid in the window. |
| Unadjusted, with `DividendCashFlowModel` | With a ledger: a $625 receivable at entitlement, then the cash at payment. The NAV doesn't fall. | The same. |
| Adjusted, with `DividendCashFlowModel` | With a ledger: the dividend is counted twice, with no error. | Refused: the dividend would be counted twice. |

A bond works the same way with its coupons: on adjusted prices the price carries them, and
on unadjusted prices a lifecycle model books them. Its redemption needs a model at either level.

## Alternatives Considered

### Dated events in Markets

Markets would keep each asset's events: dividends, coupons, redemptions, splits and
expiries. The run would check the events of its held assets in its window. Markets has no
such table today. Bonds' coupons and maturities are in `BondAssetDetailsTable`, and
`DividendCashFlowModel` reads a dividend source that the producer declares.

It is exact, but it needs a new Markets dataset that providers fill. An event that no
provider recorded would pass unnoticed: a missing row would hide an event the same way a
missing model hides it today. The owner chose the asset type instead (decision 2).

## Consequences

- It breaks every portfolio configuration, so it ships in a major release. Every portfolio
  states `initial_nav`, `initial_state_time_index`, `position_valuation_model_instance` and
  the lifecycle models its assets need. Every portfolio's identity changes.
- A portfolio that holds an asset with an event nothing books ran before, and now refuses.
- Readers of `PortfoliosTS` and `PortfolioWeightsTS`, such as the Markets API's portfolio
  routes (`apps/v1/routers/portfolios.py`), see the same columns, without `held_shares` and
  `book_cash`.
- Each portfolio run gains `PortfolioEngine`'s update execution, because the engine is a
  MetaTables updater. In the joined run of
  [MetaTables#156](https://github.com/mainsequence-projects/MetaTables/issues/156), it is one
  more node per portfolio.

## Not Decided Here

- Which event types each asset type lists, how they are named, how each is marked as a cash
  flow, a split or the end of a position, and how a provider registers them for an asset
  type of its own.
- How a valuation source that is a `TimeIndexTableRef`, with no configuration of its own,
  states `events_in_price`.
- Whether `PortfolioStateTS` and `PortfolioCashFlowsTS` (positions, cash in each currency,
  completed cash flows) are published. Both tables exist in Markets, and nothing writes them.
- The rebalance's book doesn't see income the ledger books. The ledger sizes its own orders
  at its own NAV (ADR 0058, decision 6a), so after the first dividend the book's cash and the
  ledger's differ. Whether the book should read the ledger is not decided here.
- Income in accounts and funds ([ADR 0062](0062-capital-given-to-a-virtual-fund.md),
  decision 15) is unchanged.

## Not Verified

- Whether a ledger with no lifecycle models, priced at market and charged a proportional
  cost, gives the values `PortfoliosUpdater` gives today. The formulas were compared (ADR
  0059, decision 5, and `project_portfolio_values`), not two runs.
- Whether real portfolios exist now. The owner said there were none on 2026-11-18.
- Whether the ledger's replay accepts a back-adjusted price source, which rewrites its past
  prices at each event. Adjusted prices are the default, so this concerns most portfolios.
- What the engine's update execution costs in the hosted Production Environment. It was not
  measured.
