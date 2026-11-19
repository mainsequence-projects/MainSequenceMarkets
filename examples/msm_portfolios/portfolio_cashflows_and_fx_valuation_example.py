"""Offline dividend entitlement, settlement, and multi-currency valuation example.

Run with:
    uv run --extra portfolios python examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py
"""

from __future__ import annotations

import pandas as pd

from metatables import TimeIndexMetaTable, TimeIndexTableRef
from msm_portfolios.accounting import (
    DividendCashFlowModel,
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
    project_cash_flows,
    project_portfolio_values,
    project_state,
)
from msm_portfolios.time_index import PortfolioEngine, normalize_portfolio_event_ledger_frame
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    PriceConversion,
    TargetWeightExecutionModel,
    observed_prices,
)

CALENDAR_EVENTS_TABLE = TimeIndexTableRef(
    output_table=TimeIndexMetaTable.model_construct(
        uid="00000000-0000-4000-8000-0000000000c1",
        data_source_uid="00000000-0000-4000-8000-0000000000d1",
    )
)


def always_open_calendar_events(first: str, published_until: str) -> pd.DataFrame:
    """CRYPTO_24_7 session events as ``PortfolioCalendarEvents`` publishes them.

    Each session opens at 00:00 UTC and closes when the next one opens. Events are
    published only up to ``published_until``, as the updater publishes up to its
    run time. A real graph declares a ``PortfolioCalendarEvents`` updater; this
    offline example passes the rows directly.
    """
    rows = []
    until = pd.Timestamp(published_until)
    for day in pd.date_range(pd.Timestamp(first, tz="UTC"), until.floor("D"), freq="D"):
        local_date = day.date().isoformat()
        rows.append((day, "CRYPTO_24_7", "regular", "market_open", local_date))
        rows.append(
            (day + pd.Timedelta(days=1), "CRYPTO_24_7", "regular", "market_close", local_date)
        )
    frame = pd.DataFrame(
        rows,
        columns=["time_index", "calendar_identifier", "session_label", "event_type", "local_date"],
    )
    frame = frame[frame["time_index"] <= until]
    return frame.set_index(["time_index", "calendar_identifier", "session_label", "event_type"])


def build_example() -> dict[str, pd.DataFrame]:
    """Buy EUR shares, earn a dividend, sell, then settle the retained claim."""

    prices = pd.DataFrame(
        [
            # A rebalance sizes its shares from the last prices before its earliest moment.
            ("2026-01-01T10:00:00Z", "STOCK-EUR", 50.0, "EUR", "price-0"),
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
                ("2026-01-01T10:00:00Z", "fx-0"),
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
    # Each signal trades at the first price observed strictly after it.
    signals = pd.DataFrame(
        [
            (
                "2026-01-02T09:00:00Z",
                "mock-stock-signal",
                "STOCK-EUR",
                0.55,
            ),
            (
                "2026-01-04T09:00:00Z",
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
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-01T10:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(
            maximum_staleness=pd.Timedelta(days=3)
        ),
        lifecycle_event_model_instances=(DividendCashFlowModel(),),
    )
    # The mock prices are observed every day, weekends included, so the fixture
    # trades on a 24/7 calendar and each rebalance is at its signal's time. On an
    # exchange calendar the Sunday signal would rebalance at Monday's open.
    strategy = ImmediateSignal(
        calendar_events_instance=CALENDAR_EVENTS_TABLE,
        calendar_identifier="CRYPTO_24_7",
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
        )
    )
    # PortfolioRebalance records each fill at the next observed price; the ledger
    # books exactly those fills. Offline, the strategy runs directly.
    rebalance_state = strategy.build_transitions(
        start=pd.Timestamp("2026-01-01T10:00:00Z"),
        end=pd.Timestamp("2026-01-05T10:00:00Z"),
        signal_observations=signals,
        observed_inputs={
            "calendar_events": always_open_calendar_events(
                "2026-01-01", published_until="2026-01-05T10:00:00Z"
            )
        },
        previous_state=None,
        fill_prices=observed_prices(prices, price_column="price"),
        # The stock is quoted in EUR and the portfolio is in USD: the rebalance's book
        # converts each price at the last observed rate (ADR 0059).
        price_conversion=PriceConversion(
            valuation_asset_identifier="USD",
            currencies={"STOCK-EUR": "EUR"},
            fx_rates=fx,
        ),
    )
    accounting = PortfolioEngine.calculate_backtest(
        portfolio_identifier="mock-eur-stock-portfolio",
        accounting_configuration=accounting_configuration,
        valuation_asset_identifier="USD",
        rebalance_strategy=strategy,
        rebalance_state=rebalance_state,
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
    ledger = result["ledger"]
    normalized = normalize_portfolio_event_ledger_frame(ledger)
    pd.testing.assert_frame_equal(normalized, normalize_portfolio_event_ledger_frame(ledger.copy()))
    duplicate = ledger.iloc[[0]].copy()
    duplicate["time_index"] = pd.to_datetime(duplicate["time_index"], utc=True) + pd.Timedelta(
        days=1
    )
    try:
        normalize_portfolio_event_ledger_frame(pd.concat([ledger, duplicate], ignore_index=True))
    except ValueError as exc:
        print(f"Cross-time duplicate rejected: {exc}")
    else:
        raise AssertionError("A duplicate economic record must not pass ledger validation.")
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
