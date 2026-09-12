"""Offline dividend entitlement, settlement, and multi-currency valuation example.

Run with:
    uv run --extra portfolios python examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
"""

from __future__ import annotations

import pandas as pd

from msm_portfolios.accounting import (
    DividendCashFlowModel,
    MarketPriceValuationModel,
    PortfolioAccounting,
    project_cash_flows,
    project_portfolio_values,
    project_state,
)


def build_example() -> dict[str, pd.DataFrame]:
    """Buy EUR shares, earn a dividend, sell, then settle the retained claim."""

    prices = pd.DataFrame(
        [
            ("2026-01-02T10:00:00Z", "STOCK-EUR", 50.0, "EUR", "price-1"),
            ("2026-01-03T10:00:00Z", "STOCK-EUR", 49.0, "EUR", "price-2"),
            ("2026-01-04T10:00:00Z", "STOCK-EUR", 49.0, "EUR", "price-3"),
            ("2026-01-05T10:00:00Z", "STOCK-EUR", 49.0, "EUR", "price-4"),
        ],
        columns=[
            "time_index",
            "asset_identifier",
            "price",
            "price_asset_identifier",
            "source_revision",
        ],
    )
    fx = pd.DataFrame(
        [
            (time_index, "EUR", "USD", 1.10, revision)
            for time_index, revision in (
                ("2026-01-02T10:00:00Z", "fx-1"),
                ("2026-01-03T10:00:00Z", "fx-2"),
                ("2026-01-04T10:00:00Z", "fx-3"),
                ("2026-01-05T10:00:00Z", "fx-4"),
            )
        ],
        columns=[
            "time_index",
            "base_asset_identifier",
            "quote_asset_identifier",
            "rate",
            "source_revision",
        ],
    )
    executions = pd.DataFrame(
        [
            (
                "2026-01-02T10:00:00Z",
                "buy-10-shares",
                "1",
                "STOCK-EUR",
                10.0,
                "shares",
                50.0,
                "EUR",
            ),
            (
                "2026-01-04T10:00:00Z",
                "sell-10-shares",
                "1",
                "STOCK-EUR",
                -10.0,
                "shares",
                49.0,
                "EUR",
            ),
        ],
        columns=[
            "time_index",
            "execution_identifier",
            "source_revision",
            "asset_identifier",
            "quantity_delta",
            "quantity_unit",
            "execution_price",
            "price_asset_identifier",
        ],
    )
    dividends = pd.DataFrame(
        [
            (
                "2026-01-03T10:00:00Z",
                "dividend-2026-01",
                "1",
                "2026-01-01T09:00:00Z",
                "STOCK-EUR",
                "2026-01-03T10:00:00Z",
                "2026-01-05T10:00:00Z",
                1.0,
                "EUR",
            )
        ],
        columns=[
            "time_index",
            "source_event_identifier",
            "source_revision",
            "observed_at",
            "asset_identifier",
            "entitlement_time_index",
            "payment_time_index",
            "amount_per_unit",
            "settlement_asset_identifier",
        ],
    )

    accounting = PortfolioAccounting(
        portfolio_identifier="mock-eur-stock-portfolio",
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-01T10:00:00Z",
        valuation_model=MarketPriceValuationModel(maximum_staleness=pd.Timedelta(days=3)),
    )
    ledger = accounting.run(
        valuation_observations=prices,
        fx_observations=fx,
        execution_facts=executions,
        lifecycle_models=(DividendCashFlowModel(),),
        lifecycle_inputs={DividendCashFlowModel.model_identifier: {"dividends": dividends}},
        valuation_times=("2026-01-05T10:00:00Z",),
    )
    return {
        "ledger": ledger,
        "cash_flows": project_cash_flows(ledger),
        "portfolio_values": project_portfolio_values(ledger, initial_nav=1_000.0),
        "state": project_state(ledger),
        "positions": accounting.state.positions,
        "cash": accounting.state.cash,
        "obligations": accounting.state.obligations,
    }


def main() -> None:
    result = build_example()
    summaries = result["ledger"].query("record_kind == 'valuation_summary'")
    print("Event-level USD NAV and recognized P&L:")
    print(
        summaries[["time_index", "event_type", "recognized_pnl", "nav_after"]].to_string(
            index=False
        )
    )
    print("\nEnding positions (the shares were sold):")
    print(result["positions"].to_string(index=False))
    print("\nEnding obligations (the dividend receivable was settled):")
    print(result["obligations"].to_string(index=False))
    print("\nEnding USD and EUR cash:")
    print(result["cash"].to_string(index=False))
    print("\nCompleted cash-flow projection:")
    print(
        result["cash_flows"]
        .reset_index()[["time_index", "cash_flow_type", "asset_identifier", "amount"]]
        .to_string(index=False)
    )
    print("\nUSD portfolio-value projection:")
    print(
        result["portfolio_values"]
        .reset_index()[["time_index", "close", "return"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
