# msm_portfolios Knowledge

`msm_portfolios` owns portfolio construction and virtual-fund workflows. It is
kept outside the core `msm` package because portfolios behave like a small
application layer over assets, accounts, signals, rebalance strategies, and
portfolio DataNodes.

The package may depend on core `msm` tables such as assets and accounts, but
portfolio-specific tables, APIs, services, DataNodes, and examples belong here.

## Areas

- [Portfolios](portfolios/index.md): portfolio identity, asset linkage,
  metadata, signals, rebalance strategies, and canonical portfolio DataNodes.
- [Virtual Funds](virtualfunds/index.md): fund rows that bind accounts to
  portfolios, plus virtual-fund holdings storage.

## Package Boundary

User-facing portfolio rows should import from `msm_portfolios.api.*`.
Portfolio schema/bootstrap workflows should call `msm_portfolios.start_engine`.

Core market reference data remains in [`msm`](../msm/index.md). Pricing engines
and QuantLib-backed market-data configuration remain in
[`msm_pricing`](../msm_pricing/index.md).
