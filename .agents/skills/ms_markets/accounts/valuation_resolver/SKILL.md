---
name: mainsequence-markets-account-valuation-resolver
description: Use this skill when implementing, reviewing, or documenting valuation resolvers used by ms-markets account virtual-fund allocation planners.
---

# Account Valuation Resolver

Use this skill when account allocation logic needs NAV, target notional
conversion, or other valuation metrics before planning virtual-fund allocation.

The resolver is a workflow boundary. It keeps pricing, derivative valuation,
FX conversion, and risk metrics out of the account allocation planner.

## Owning Context

Read with:

1. `.agents/skills/ms_markets/accounts/account_workflow/SKILL.md`
2. `docs/ADR/0029-account-holdings-virtual-fund-allocation-policy.md`
3. `docs/knowledge/msm/virtualfunds/index.md`
4. `src/msm/services/accounts/account_virtual_allocations.py`

## Protocol

The resolver receives named metric requests:

```python
requested_metrics = [{"name": "nav"}]
```

Do not use a tuple of bare strings. The dict shape leaves room for metric
parameters without changing the call signature.

The call boundary is:

```python
valuation_result = valuation_resolver(
    requested_metrics=requested_metrics,
    source_holdings=source_holdings,
    target_notional_demands=target_notional_demands,
    valuation_time=valuation_time,
    valuation_asset_uid=valuation_asset_uid,
    valuation_policy=valuation_policy,
)
```

Input meanings:

- `source_holdings`: resolved account holding lines as
  `HoldingValuationInput`, including `asset_uid`, `asset_identifier`,
  positive `quantity`, and `direction`.
- `target_notional_demands`: resolved target rows needing quantity conversion,
  represented as `TargetNotionalDemand`.
- `valuation_time`: timezone-aware UTC datetime for the valuation.
- `valuation_asset_uid`: `AssetTable.uid` of the numeraire asset. This is not
  an ISO code, ticker, or provider symbol.
- `valuation_policy`: stale-data, tolerance, and resolver-specific rules.

Output meanings:

- `AllocationValuation.metrics`: mapping from metric name to
  `ValuationMetricResult`.
- each metric result has a `total` and optional `lines`.
- lines may be per asset, source holding, target row, or another resolver-owned
  trace key.
- `target_quantity_demands`: converted target demands when notional target rows
  need asset quantities.
- `diagnostics`: warnings or errors the caller can expose in the allocation
  plan.

For account virtual-fund allocation, `nav` is required unless the caller
provides `account_nav` directly.

## Rules

- Use `AssetTable.uid` for valuation identity. Provider symbols, ISO currency
  codes, and tickers are resolver internals.
- Return all requested metrics by name. If a metric cannot be computed, return
  a diagnostic or raise a clear error at the resolver boundary.
- Preserve signs. Source holdings use positive quantity plus `direction`;
  target quantity demands use signed quantity.
- Do not fetch hidden latest data unless `valuation_policy` explicitly allows
  that stale-data mode.
- Do not write MetaTables or DataNode storage from the resolver.
- Do not execute trades, rebalance holdings, borrow, or synthesize source
  holdings.
- Keep the resolver batch-oriented. It should receive all source holdings and
  target demands needed for one plan, not make one platform query per row when
  a vector or filter query is available.

## Minimal Output

For simple NAV-only allocation, return:

```python
AllocationValuation(
    metrics={
        "nav": ValuationMetricResult(
            metric="nav",
            total=ValuationMetricValue(
                value=640000.0,
                valuation_asset_uid=usd_asset.uid,
                as_of=valuation_time,
            ),
            lines=(
                ValuationMetricLine(
                    line_key="BTC",
                    asset_uid=btc_asset.uid,
                    asset_identifier="example-asset-btc",
                    value=600000.0,
                    valuation_asset_uid=usd_asset.uid,
                    as_of=valuation_time,
                ),
            ),
        ),
    },
    valuation_asset_uid=usd_asset.uid,
)
```

