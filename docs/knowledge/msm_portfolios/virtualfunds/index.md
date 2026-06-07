# Virtual Funds Boundary

Virtual funds are no longer owned by `msm_portfolios`.

They are core `msm` account-allocation state because they allocate real
`AccountHoldingsStorage` rows into account-owned virtual views. The current
canonical documentation is:

[Core Virtual Funds](../../msm/virtualfunds/index.md)

`msm_portfolios` remains the portfolio construction engine. It can provide the
portfolio weights or portfolio DataNodes used by the account allocation
workflow, but it does not own `VirtualFundTable`,
`VirtualFundHoldingsSetTable`, `VirtualFundHoldingsStorage`, or the allocation
planner.

