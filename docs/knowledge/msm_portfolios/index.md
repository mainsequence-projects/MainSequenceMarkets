# msm_portfolios Knowledge

`msm_portfolios` owns portfolio construction workflows. It is kept outside the
core `msm` package because portfolios behave like a small application layer
over assets, accounts, signals, rebalance strategies, and portfolio DataNodes.

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
- [Virtual Funds Boundary](virtualfunds/index.md): historical boundary note
  pointing to core `msm` virtual-fund documentation.

## Package Boundary

User-facing portfolio rows should import from `msm_portfolios.api.*`.
Portfolio schema/bootstrap workflows should call `msm_portfolios.start_engine`.

Core market reference data, account allocation, and virtual-fund state remain
in [`msm`](../msm/index.md). Pricing engines and QuantLib-backed market-data
configuration remain in
[`msm_pricing`](../msm_pricing/index.md).
