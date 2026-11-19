# 0059. Portfolio Currency, FX, Cash Limits And Drifting Weights

## Status

Accepted (2026-11-18). The owner decided the five points held by
[ADR 0058](0058-trade-at-the-next-observed-price.md) in
[issue #89](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/89) on
2026-11-18. Implemented on the same branch for `development` as ADR 0058.

- It completes ADR 0058, decision 9: the execution policy's cash setting and its
  cross-currency assumption.
- It changes the weights-only valuation of [ADR 0040](0040-portfolio-temporal-ownership.md):
  weights drift with prices between rebalances.
- Sizing at the decision and the cash setting for the strategies with their own bars are
  [issue #90](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/90).

## Context

ADR 0058 left these open:

- The ledger's `PortfolioAccountingConfiguration` named the portfolio's currency
  (`valuation_asset_identifier`); `PortfolioRebalance` and the weights path had none, so
  they read every price as if it were in one currency.
- `MarketPriceValuationModel` declared its own `fx_source`; nothing else could convert a
  price quoted in another currency.
- The cash setting allowed negative cash only as a fraction of NAV.
- `PortfoliosUpdater` valued a portfolio without a ledger from constant weights between
  rebalances: `return = sum(weight x asset return)`, which rebalances back to target at every
  price without trading or cost.

## Decision

### 1. The portfolio's currency is on the build configuration (owner)

`PortfolioBuildConfiguration.valuation_asset_identifier` is required. NAV, cash and every
value are in it. It replaces `PortfolioAccountingConfiguration.valuation_asset_identifier`,
with no duplicate: `PortfolioEngine` copies it into its configuration, and
`PortfolioEngine.calculate_backtest` takes it as an argument. The ledger's `initial_nav` is
in it.

### 2. One FX source for the portfolio (owner)

`PortfolioBuildConfiguration.fx_source_instance` is optional and hash-bearing. It is
indexed by `time_index`, `base_asset_identifier` and `quote_asset_identifier`, with a `rate`
(one unit of the base is `rate` units of the quote). `PortfolioRebalance`, the ledger
(`PortfolioEngine`, which passes it to the valuation and execution models) and the weights
path read it; `MarketPriceValuationModel.fx_source` is removed.

- With an FX source, the valuation source must have a `price_asset_identifier` column
  naming each price's currency, or the portfolio is refused when its prices are read.
- Without one, every asset is priced in the portfolio's currency. A
  `price_asset_identifier` naming another currency is refused; there is no silent
  conversion and no silent fallback.
- A price in another currency is converted at the last rate observed at or before the time
  it is used: a decision uses the last rate before its earliest moment, a fill the last rate
  at its time, a valuation the last rate at the valuation time. A rate never observed
  raises. FX is assumed to have endless liquidity: no FX trade is modelled.

`PortfolioRebalance` reads the rates from the newest recorded rebalance's earliest moment,
with each currency's last rate before it, and passes a `PriceConversion` to the strategy.
The book is in the portfolio's currency; a row's `execution_price` is the observed price in
its own currency, and its `strategy_state` records the `fx_rate` used.

### 3. Negative cash: not allowed, a fraction of NAV, or a fixed amount (owner)

`ExecutionPolicy.negative_cash` is `not_allowed` (the default), `fraction_of_nav` or
`fixed_amount`, with its limit in `negative_cash_limit` (0 when not allowed; a fraction, or
an amount in the portfolio's currency).

A fixed amount exists only for a portfolio with a ledger. The weights-only path has no NAV in
currency: `PortfolioBuildConfiguration` refuses a fixed amount without
`accounting_configuration`. With a ledger, the book's unit is the NAV at the first
rebalance, which is the ledger's `initial_nav`: `PortfolioRebalance` converts the amount
into the book's unit with it. The ledger enforces the same floor in currency.

### 4. Cash across currencies is counted in the portfolio's currency (owner)

The ledger's own cut (ADR 0058, decision 9) counts every cash balance, in every currency,
in the portfolio's currency at the last observed rate. The buys of an instant, in whatever
currency they settle, then share what is left down to the policy's floor, pro rata.

### 5. Weights drift in the weights-only path (owner)

`PortfoliosUpdater` values a portfolio without a ledger from the shares `PortfolioRebalance`
records. `PortfolioWeights` projects each row's `held_shares` and the book's cash
(`book_cash`) from its `strategy_state` into two new nullable columns
(`PortfolioWeightsStorage`, Alembic revision 0030). The portfolio's value at a valuation
time is the book's cash plus each asset's shares at its price then, converted into the
portfolio's currency; its return is that value's change. Fills are self-financing at their
price, so weights drift with prices between rebalances. The commission fee is charged on
turnover as before.

Rows without a book (weights supplied directly, or the strategies with their own bars until
#90) carry no shares and are valued from constant weights as before; rows with and without a
book are never mixed in one valuation.

## Worked Example

Half in BTC bought at 100, half cash. BTC is 100, 110, 121 on three days.

| Day | Value from shares | Return | Constant weight 0.5 |
| --- | --- | --- | --- |
| 1 | 0.5 + 0.005 x 100 = 1.000 | | |
| 2 | 0.5 + 0.005 x 110 = 1.050 | 5.00% | 5.00% |
| 3 | 0.5 + 0.005 x 121 = 1.105 | 5.24% | 5.00% |

## Consequences

- Every portfolio build configuration names its currency; portfolio identities change.
- A portfolio with assets in another currency declares one FX source and a valuation source
  with `price_asset_identifier`; the ledger's valuation model no longer declares one.
- A provider with its own `PortfolioWeightsTS` instances adds `held_shares` and `book_cash`
  in a revision of its own; registration verifies contract columns.
- The weights path's value of a portfolio whose strategy records a book changes: it no
  longer rebalances back to target at every price.

## Not Decided Here

- Sizing at the decision and the cash setting for `TimeWeighted`, `VolumeParticipation`,
  `LiquidityConstrained` and the trailing-ADV strategy: #90. Until then they record no
  shares, and the weights path values them from constant weights.

## Implementation Notes

### 2026-11-18: branch for `development`

- `PortfolioBuildConfiguration.valuation_asset_identifier` and `fx_source_instance`; the
  fixed-amount check. `PortfolioEngineConfiguration.valuation_asset_identifier` and
  `fx_source_instance`; `PortfolioEngine` depends on the FX source as `fx`.
- `PriceConversion` (`msm_portfolios.rebalance_strategy`); `quote_currencies` and
  `read_fx_rates` (`time_index/portfolios/rebalance.py`); `build_transitions(...,
  price_conversion=..., book_unit_value=...)`.
- `ExecutionPolicy.negative_cash`, `negative_cash_allowance` and `cash_floor`;
  `AccountingExecutionContext.cash_floor`.
- `PortfolioWeightsStorage.held_shares` and `book_cash`, Alembic revision 0030;
  `PortfoliosUpdater` values from them.
- Tests: `tests/msm_portfolios/time_index/test_portfolio_currency.py`.

## Not Verified

- A run on hosted data, and the migration on a deployed database.
