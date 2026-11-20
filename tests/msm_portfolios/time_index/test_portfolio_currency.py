"""The portfolio's currency, its FX source, the cash limit, and drifting weights (ADR 0059).

- The build configuration names the portfolio's currency (``valuation_asset_identifier``)
  and its one FX source (``fx_source_instance``); the ledger has no copy of either.
- With an FX source, prices quoted in another currency are converted at the last
  observed rate; without one, every asset must be priced in the portfolio's currency.
- Negative cash is not allowed, a fraction of NAV, or a fixed amount; the fixed amount
  needs a ledger.
- A portfolio without a ledger is valued from the shares ``PortfolioRebalance`` records,
  so its weights drift with prices between rebalances.

All times are Wednesday 2026-11-18 (NYSE session 14:30-21:00 UTC) unless stated.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from msm_portfolios.accounting import (
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
)
from msm_portfolios.configuration import BacktestingWeightsConfig, PortfolioBuildConfiguration
from msm_portfolios.rebalance_strategy import (
    ExecutionPolicy,
    ImmediateSignal,
    InstrumentExecutionSpec,
    PriceConversion,
    ProportionalExecutionCostModel,
    TargetWeightExecutionModel,
    observed_prices,
)
from msm_portfolios.time_index import PortfolioEngine
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.rebalance import (
    PortfolioRebalance,
    quote_currencies,
    read_rebalance_input,
)
from tests.support.accounting import _legacy_build_configuration, always_open_strategy
from tests.support.portfolio_values import asset_frame, portfolio_values_node_for_frames
from tests.support.rebalance import (
    HALTED_SELL,
    SWAP,
    PublishedTable,
    book,
    calendar,
    marks,
    position_deltas,
    prices,
    progress,
    rounded,
    signal_frame,
    stock_strategy,
    utc,
)


def run(
    strategy,
    signals: pd.DataFrame,
    price_rows: pd.DataFrame,
    *,
    conversion: PriceConversion | None = None,
    unit_value: float | None = None,
) -> pd.DataFrame:
    """Run the strategy once over Wednesday and Thursday, as PortfolioRebalance does."""
    calendar_input = read_rebalance_input(
        strategy.calendar_events_instance,
        dependency_name="calendar_events",
        contract=strategy.required_input_contract()["calendar_events"],
        start=utc("2026-11-18T00:00:00Z"),
        end=utc("2026-11-19T23:00:00Z"),
        seed_coordinates=strategy.dependency_seed_coordinates("calendar_events"),
    )
    return strategy.build_transitions(
        start=utc("2026-11-18T00:00:00Z"),
        end=utc("2026-11-19T23:00:00Z"),
        signal_observations=signals,
        observed_inputs={"calendar_events": calendar_input},
        previous_state=None,
        fill_prices=observed_prices(price_rows, price_column="close"),
        price_conversion=conversion,
        book_unit_value=unit_value,
    )


def immediate(**policy) -> ImmediateSignal:
    return ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        execution_policy=ExecutionPolicy(**policy),
    )


def fx_frame(*rows: tuple[str, str, float]) -> pd.DataFrame:
    """``(time, base currency, rate into USD)`` rows of an FX source."""
    return pd.DataFrame(
        [
            (utc(stamp), base, "USD", rate, f"fx-{position}")
            for position, (stamp, base, rate) in enumerate(rows)
        ],
        columns=[
            "time_index",
            "base_asset_identifier",
            "quote_asset_identifier",
            "rate",
            "source_revision",
        ],
    )


# --- The build configuration -----------------------------------------------------------


def build_with(strategy, **fields) -> PortfolioBuildConfiguration:
    base = _legacy_build_configuration()
    values = {name: getattr(base, name) for name in PortfolioBuildConfiguration.model_fields}
    values["backtesting_weights_configuration"] = BacktestingWeightsConfig(
        signal_weights_instance=base.backtesting_weights_configuration.signal_weights_instance,
        rebalance_strategy_instance=strategy,
    )
    return PortfolioBuildConfiguration(**{**values, **fields})


def ledger_configuration() -> PortfolioAccountingConfiguration:
    return PortfolioAccountingConfiguration(
        initial_nav=10_000.0,
        initial_state_time_index=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        position_valuation_model_instance=MarketPriceValuationModel(),
    )


def test_the_portfolio_currency_is_required_on_the_build_configuration_only() -> None:
    assert PortfolioBuildConfiguration.model_fields["valuation_asset_identifier"].is_required()
    assert "valuation_asset_identifier" not in PortfolioAccountingConfiguration.model_fields
    assert "fx_source" not in MarketPriceValuationModel.model_fields


def test_the_fx_source_is_part_of_the_portfolio_identity() -> None:
    strategy = always_open_strategy()
    without = build_with(strategy)
    with_fx = build_with(strategy, fx_source_instance=PublishedTable.build(
        "fx", fx_frame(), index=["time_index", "base_asset_identifier", "quote_asset_identifier"]
    ))

    assert "fx_source_instance" not in without.model_dump(mode="json")
    assert with_fx.model_dump(mode="json")["fx_source_instance"] != without.model_dump(
        mode="json"
    ).get("fx_source_instance")


def test_a_fixed_cash_limit_needs_a_ledger() -> None:
    strategy = always_open_strategy(
        execution_policy=ExecutionPolicy(negative_cash="fixed_amount", negative_cash_limit=500.0)
    )

    with pytest.raises(ValidationError, match="fixed-amount negative cash limit needs"):
        build_with(strategy)
    assert build_with(strategy, accounting_configuration=ledger_configuration())
    # A fraction of NAV needs no currency.
    assert build_with(
        always_open_strategy(
            execution_policy=ExecutionPolicy(
                negative_cash="fraction_of_nav", negative_cash_limit=0.5
            )
        )
    )


@pytest.mark.parametrize(
    "policy",
    [
        {"negative_cash_limit": 0.5},
        {"negative_cash": "fraction_of_nav"},
        {"negative_cash": "fixed_amount", "negative_cash_limit": 0.0},
    ],
)
def test_the_cash_limit_must_match_its_setting(policy) -> None:
    with pytest.raises(ValidationError):
        ExecutionPolicy(**policy)


# --- The fixed amount in PortfolioRebalance and in the ledger ---------------------------


def test_a_fixed_amount_is_converted_with_the_ledgers_initial_nav() -> None:
    """$5,000 of negative cash on a $10,000 ledger is half of the book's first NAV."""
    fixed = run(
        immediate(negative_cash="fixed_amount", negative_cash_limit=5_000.0),
        SWAP,
        HALTED_SELL,
        unit_value=10_000.0,
    )
    half = run(immediate(negative_cash="fraction_of_nav", negative_cash_limit=0.5), SWAP, HALTED_SELL)

    assert rounded(fixed) == rounded(half)
    with pytest.raises(ValueError, match="needs a portfolio with a ledger"):
        run(
            immediate(negative_cash="fixed_amount", negative_cash_limit=5_000.0),
            SWAP,
            HALTED_SELL,
        )


@pytest.mark.parametrize(
    ("policy", "shares"),
    [
        ({}, 99.0),
        ({"negative_cash": "fixed_amount", "negative_cash_limit": 50.0}, 99.0),
        ({"negative_cash": "fixed_amount", "negative_cash_limit": 150.0}, 100.0),
        ({"negative_cash": "fraction_of_nav", "negative_cash_limit": 0.02}, 100.0),
    ],
)
def test_the_ledger_cuts_its_own_shortfall_down_to_the_cash_limit(policy, shares) -> None:
    """100 shares at 100 plus a 1% cost need $10,100 of a $10,000 NAV: $100 short."""
    strategy = stock_strategy(
        calendar(), execution_policy=ExecutionPolicy(**policy)
    ).model_copy(
        update={"execution_cost_model_instances": (ProportionalExecutionCostModel(rate=0.01),)}
    )
    price_rows = prices(("AAPL", "2026-11-18T14:45Z", 100.0), ("AAPL", "2026-11-18T15:01Z", 100.0))
    state = run(
        strategy,
        signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 1.0})]),
        price_rows,
        unit_value=10_000.0,
    )

    ledger = book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    assert position_deltas(ledger) == [(utc("2026-11-18T15:01Z"), "AAPL", shares, 100.0)]


# --- Prices in another currency --------------------------------------------------------


def test_the_book_converts_prices_at_the_last_observed_fx_rate() -> None:
    """A EUR stock at 100: sized at 1.10 USD per EUR, filled when the rate is 1.20."""
    conversion = PriceConversion(
        valuation_asset_identifier="USD",
        currencies={"SAP": "EUR"},
        fx_rates=fx_frame(("2026-11-18T14:00Z", "EUR", 1.10), ("2026-11-18T15:00:30Z", "EUR", 1.20)),
    )
    result = run(
        immediate(),
        signal_frame([("2026-11-18T15:00:00Z", {"SAP": 0.5})]),
        prices(("SAP", "2026-11-18T14:45Z", 100.0), ("SAP", "2026-11-18T15:01Z", 100.0)),
        conversion=conversion,
    )

    [row] = result.to_dict(orient="records")
    state = json.loads(row["strategy_state"])
    # 0.5 x NAV 1 / 110 USD per share, worth 120 USD each at the fill.
    assert row["execution_price"] == 100.0
    assert state["decision_price"] == pytest.approx(110.0)
    assert state["fx_rate"] == pytest.approx(1.20)
    assert row["executed_quantity"] == pytest.approx(0.5 / 110.0)
    assert row["weight_after"] == pytest.approx(0.5 * 120.0 / 110.0)


def test_an_fx_rate_never_observed_raises() -> None:
    conversion = PriceConversion(
        valuation_asset_identifier="USD",
        currencies={"SAP": "EUR"},
        fx_rates=fx_frame(("2026-11-18T16:00Z", "EUR", 1.10)),
    )
    with pytest.raises(ValueError, match="No FX rate from EUR into USD"):
        run(
            immediate(),
            signal_frame([("2026-11-18T15:00:00Z", {"SAP": 0.5})]),
            prices(("SAP", "2026-11-18T14:45Z", 100.0), ("SAP", "2026-11-18T15:01Z", 100.0)),
            conversion=conversion,
        )


def priced_in(*currencies: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [(utc("2026-11-18T15:01Z"), asset, 100.0, currency) for asset, currency in currencies],
        columns=["time_index", ASSET_IDENTIFIER, "close", "price_asset_identifier"],
    )


def test_the_quote_currency_column_is_required_with_an_fx_source() -> None:
    with pytest.raises(ValueError, match="must have a price_asset_identifier column"):
        quote_currencies(
            prices(("SAP", "2026-11-18T15:01Z", 100.0)),
            valuation_asset_identifier="USD",
            fx_declared=True,
        )
    assert quote_currencies(
        priced_in(("SAP", "EUR"), ("AAPL", "USD")),
        valuation_asset_identifier="USD",
        fx_declared=True,
    ) == {"SAP": "EUR", "AAPL": "USD"}


def test_without_an_fx_source_every_asset_is_in_the_portfolios_currency() -> None:
    assert quote_currencies(
        prices(("AAPL", "2026-11-18T15:01Z", 100.0)),
        valuation_asset_identifier="USD",
        fx_declared=False,
    ) == {}
    assert quote_currencies(
        priced_in(("AAPL", "USD")), valuation_asset_identifier="USD", fx_declared=False
    ) == {"AAPL": "USD"}
    with pytest.raises(ValueError, match="needs fx_source_instance"):
        quote_currencies(
            priced_in(("SAP", "EUR")), valuation_asset_identifier="USD", fx_declared=False
        )


def test_portfolio_rebalance_reads_the_portfolios_fx_source() -> None:
    signal = PublishedTable.build("signal", signal_frame([]), index=["time_index"])
    source = PublishedTable.build(
        "prices", priced_in(("SAP", "EUR")), index=["time_index", ASSET_IDENTIFIER]
    )
    fx = PublishedTable.build(
        "fx", fx_frame(), index=["time_index", "base_asset_identifier", "quote_asset_identifier"]
    )
    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = object()
    node.signal_weights = signal
    node.valuation_source = source
    node.fx_source = fx
    events = calendar()
    node.rebalance_strategy = ImmediateSignal(
        calendar_events_instance=events, calendar_identifier="XNYS"
    )

    assert node.dependencies() == {
        "valuation_source": source,
        "fx_source": fx,
        "calendar_events": events,
    }


def test_the_ledger_counts_cash_across_currencies_in_the_portfolios() -> None:
    """USD cash buys a EUR stock at 50 EUR, 2 USD per EUR; a 1% cost leaves it short.

    100 shares cost 5,000 EUR plus 50 EUR of cost: 10,100 USD of a 10,000 USD NAV. The
    buy is cut to 99 shares, counting the USD cash in USD.
    """
    strategy = ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="SAP",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="EUR",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        ),
        execution_cost_model_instances=(ProportionalExecutionCostModel(rate=0.01),),
    )
    rates = fx_frame(("2026-11-18T14:00Z", "EUR", 2.0))
    price_rows = prices(("SAP", "2026-11-18T14:45Z", 50.0), ("SAP", "2026-11-18T15:01Z", 50.0))
    state = run(
        strategy,
        signal_frame([("2026-11-18T15:00:00Z", {"SAP": 1.0})]),
        price_rows,
        conversion=PriceConversion(
            valuation_asset_identifier="USD", currencies={"SAP": "EUR"}, fx_rates=rates
        ),
    )
    valuations = marks(price_rows).assign(price_asset_identifier="EUR")

    ledger = PortfolioEngine.calculate_backtest(
        portfolio_identifier="eur-stock",
        accounting_configuration=PortfolioAccountingConfiguration(
            initial_nav=10_000.0,
            initial_state_time_index="2026-11-18T00:00:00Z",
            position_valuation_model_instance=MarketPriceValuationModel(
                maximum_staleness=dt.timedelta(days=1)
            ),
        ),
        valuation_asset_identifier="USD",
        rebalance_strategy=strategy,
        rebalance_state=state,
        valuation_observations=valuations,
        fx_observations=rates,
    ).ledger

    assert position_deltas(ledger) == [(utc("2026-11-18T15:01Z"), "SAP", 99.0, 50.0)]
    [stock] = progress(ledger, "SAP")
    assert stock["ledger_cut"] == {"quantity": 1.0, "reason": "insufficient_cash"}


# --- Weights drift in the weights-only path --------------------------------------------


def book_weights(rows: list[tuple[str, str, float, float, float, float]]) -> pd.DataFrame:
    """``(time, asset, weight, weight_before, held_shares, book_cash)`` rows."""
    frame = pd.DataFrame(
        rows,
        columns=[
            "time_index",
            ASSET_IDENTIFIER,
            "weight",
            "weight_before",
            "held_shares",
            "book_cash",
        ],
    )
    frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
    return frame.set_index(["time_index", ASSET_IDENTIFIER])


def test_weights_drift_with_prices_between_rebalances() -> None:
    """Half in BTC bought at 100, half cash. BTC goes 100, 110, 121.

    The portfolio is 1.00, 1.05, 1.105: returns 5% then 5.24%. Holding the weight at
    0.5 would have rebalanced back to target at every price: 5% then 5%.
    """
    days = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    valuations = asset_frame(
        [(day.isoformat(), "btc", price) for day, price in zip(days, [100.0, 110.0, 121.0])]
    )
    weights = book_weights([(days[0].isoformat(), "btc", 0.5, 0.0, 0.005, 0.5)])
    node = portfolio_values_node_for_frames(
        valuations=valuations, weights=weights, timestamps=days
    )

    values = node._calculate_portfolio_workflow_values()

    assert values["return"].tolist() == pytest.approx([0.0, 0.05, 1.105 / 1.05 - 1.0])


def test_weights_without_a_book_cannot_mix_with_a_book() -> None:
    days = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
    valuations = asset_frame([(day.isoformat(), "btc", 100.0) for day in days])
    weights = book_weights(
        [
            (days[0].isoformat(), "btc", 0.5, 0.0, 0.005, 0.5),
            (days[1].isoformat(), "btc", 0.6, 0.5, None, None),
        ]
    )
    node = portfolio_values_node_for_frames(
        valuations=valuations, weights=weights, timestamps=days
    )

    with pytest.raises(ValueError, match="mix rows with and without"):
        node._calculate_portfolio_workflow_values()


def test_the_weights_path_values_foreign_prices_in_the_portfolios_currency() -> None:
    """A EUR asset held through a rate change: the value moves with the rate."""
    days = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
    valuations = asset_frame([(day.isoformat(), "sap", 100.0) for day in days]).assign(
        price_asset_identifier="EUR"
    )
    weights = book_weights([(days[0].isoformat(), "sap", 1.0, 0.0, 0.01 / 1.1, 0.0)])
    node = portfolio_values_node_for_frames(
        valuations=valuations, weights=weights, timestamps=days
    )
    node.fx_source = PublishedTable.build(
        "fx",
        fx_frame((days[0].isoformat(), "EUR", 1.1), (days[1].isoformat(), "EUR", 1.21)),
        index=["time_index", "base_asset_identifier", "quote_asset_identifier"],
    )

    values = node._calculate_portfolio_workflow_values()

    assert values["return"].tolist() == pytest.approx([0.0, 0.1])
