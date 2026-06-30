# msm_portfolios

`msm_portfolios` owns portfolio construction workflows. It is kept outside the
core `msm` package because portfolios behave like a small application layer
over assets, accounts, signals, rebalance strategies, and portfolio DataNodes.

It is an optional package built on top of `msm`; read [Core Concepts](../../concepts.md)
first for the shared runtime model (row objects, `start_engine(...)`,
migrations-before-runtime).

The package may depend on core `msm` tables such as assets, accounts, and
portfolio identity, but portfolio-specific metadata, calculation DataNodes, and
examples belong here. Virtual-fund identity and holdings allocation belong to
core `msm` account allocation.

Install portfolio workflows with the `ms-markets[portfolios]` extra. That extra
owns portfolio-only runtime helpers such as `pandas-market-calendars`; the core
`ms-markets` install does not require them.

## Areas

- [Portfolios](portfolios/index.md): portfolio identity, asset linkage,
  metadata, signals, rebalance strategies, and canonical portfolio DataNodes.

Virtual funds are **not** owned by `msm_portfolios`. They are core `msm`
account-allocation state; see
[Core Account Virtual Funds](../msm/accounts/virtual_funds.md). `msm_portfolios`
can supply the portfolio weights or DataNodes the allocation workflow consumes,
but it does not own `VirtualFundTable`, `VirtualFundHoldingsSetTable`,
`VirtualFundHoldingsStorage`, or the allocation planner.

## Package Boundary

User-facing portfolio rows should import from `msm_portfolios.api.*`.
Portfolio schema/bootstrap workflows should call `msm_portfolios.start_engine`.

Core market reference data, account allocation, and virtual-fund state remain
in [`msm`](../msm/index.md). Pricing engines and QuantLib-backed market-data
configuration remain in
[`msm_pricing`](../msm_pricing/index.md).

## Related Concepts

- [Core Concepts](../../concepts.md) — the shared runtime model.
- [Portfolios](portfolios/index.md) — the portfolio construction reference.
- [Accounts](../msm/accounts/index.md) and
  [Virtual Funds](../msm/accounts/virtual_funds.md) — how account allocation
  consumes portfolios.
- [msm_pricing](../msm_pricing/index.md) — valuation of portfolio constituents.
