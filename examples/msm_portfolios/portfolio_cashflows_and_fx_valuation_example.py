"""Offline dividend entitlement, settlement, and multi-currency valuation example.

Run with:
    uv run --extra portfolios python examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
"""

from __future__ import annotations

import pandas as pd

from msm_portfolios.accounting import (
    DividendCashFlowModel,
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
    project_cash_flows,
    project_portfolio_values,
    project_state,
)
from msm_portfolios.data_nodes import PortfolioEngine
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    TargetWeightExecutionModel,
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
    signals = pd.DataFrame(
        [
            (
                "2026-01-02T10:00:00Z",
                "mock-stock-signal",
                "STOCK-EUR",
                0.55,
            ),
            (
                "2026-01-04T10:00:00Z",
                "mock-stock-signal",
                "STOCK-EUR",
                0.0,
            ),
        ],
        columns=[
            "time_index",
            "signal_uid",
            "asset_identifier",
            "signal_weight",
        ],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
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

    accounting_configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-01T10:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(
            maximum_staleness=pd.Timedelta(days=3)
        ),
        lifecycle_event_model_instances=(DividendCashFlowModel(),),
    )
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="STOCK-EUR",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="EUR",
                    settlement_style="cash",
                    terms_version="mock-stock-v1",
                ),
            ),
            maximum_staleness=pd.Timedelta(days=3),
        )
    )
    accounting = PortfolioEngine.calculate_backtest(
        portfolio_identifier="mock-eur-stock-portfolio",
        accounting_configuration=accounting_configuration,
        rebalance_strategy=strategy,
        signal_observations=signals,
        rebalance_inputs={},
        valuation_observations=prices,
        fx_observations=fx,
        lifecycle_inputs={DividendCashFlowModel.model_identifier: {"dividends": dividends}},
        valuation_times=("2026-01-05T10:00:00Z",),
    )
    ledger = accounting.ledger
    return {
        "ledger": ledger,
        "cash_flows": project_cash_flows(ledger),
        "portfolio_values": project_portfolio_values(ledger, initial_nav=1_000.0),
        "state": project_state(ledger),
        "positions": accounting.state.positions,
        "cash": accounting.state.cash,
        "obligations": accounting.state.obligations,
        "execution_progress": accounting.state.execution_progress,
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
