"""The execution policy owns the choices of trading at the next observed price (ADR 0058).

The facts hold whatever the policy says: a fill uses an observed price strictly after
its signal, at or after the earliest moment, inside a session. These tests run each
choice the policy makes: sizing time, the negative cash limit, sells before buys,
pro-rata allocation of too little cash, cut-and-cancel, and calendar gating; then
how the ledger books what ``PortfolioRebalance`` recorded.

All times are Wednesday 2026-11-18 (NYSE session 14:30-21:00 UTC) unless stated. A
price at 14:45 is the last before every decision.
"""

from __future__ import annotations

import json
import uuid

import pandas as pd
import pytest

from msm_portfolios.rebalance_strategy import (
    ExecutionPolicy,
    ImmediateSignal,
    ProportionalExecutionCostModel,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.storage import PortfolioRebalanceStateStorage
from tests.support.pinned_identities import _bound
from tests.support.rebalance import (
    HALTED_SELL,
    SWAP,
    IncrementalRebalance,
    PublishedTable,
    book,
    calendar,
    marks,
    position_deltas,
    prices,
    progress,
    rounded,
    run_strategy,
    signal_frame,
    stock_strategy,
    utc,
)


def immediate(**policy) -> ImmediateSignal:
    return ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        execution_policy=ExecutionPolicy(**policy),
    )


def run(strategy, signals, price_rows: pd.DataFrame) -> pd.DataFrame:
    return run_strategy(
        strategy,
        signals=signals,
        prices=price_rows,
        start="2026-11-18T00:00:00Z",
        end="2026-11-19T23:00:00Z",
    )


def steps(result: pd.DataFrame) -> list[tuple[pd.Timestamp, str, str, float, float]]:
    """``(time, asset, status, shares, weight_after)`` of every row, in order."""
    ordered = result.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
    return [
        (
            utc(row["time_index"]),
            row[ASSET_IDENTIFIER],
            row["execution_status"],
            pytest.approx(row["executed_quantity"], abs=1e-12),
            pytest.approx(row["weight_after"], abs=1e-12),
        )
        for row in ordered.to_dict(orient="records")
    ]


def state_of(result: pd.DataFrame, time_index: str, asset: str) -> dict:
    row = result[
        (result["time_index"] == utc(time_index)) & (result[ASSET_IDENTIFIER] == asset)
    ].iloc[0]
    return json.loads(row["strategy_state"])


def test_the_defaults_are_the_owners_decisions() -> None:
    assert ExecutionPolicy().model_dump() == {
        "sizing": "at_decision",
        "negative_cash": "not_allowed",
        "negative_cash_limit": 0.0,
        "sells_before_buys": True,
        "cash_shortfall_allocation": "pro_rata",
        "uncovered_buys": "cut_and_cancel",
        "calendar_gating": "portfolio_calendar",
    }


def test_a_sell_at_the_same_instant_pays_for_the_buy() -> None:
    """Fully invested in AAPL; the new target is all ILLQ. Both trade at 16:01."""
    swap_prices = prices(
        ("AAPL", "2026-11-18T14:45Z", 100.0),
        ("ILLQ", "2026-11-18T14:45Z", 50.0),
        ("AAPL", "2026-11-18T15:01Z", 100.0),
        ("AAPL", "2026-11-18T16:01Z", 100.0),
        ("ILLQ", "2026-11-18T16:01Z", 50.0),
        ("ILLQ", "2026-11-18T16:02Z", 50.0),
    )

    sells_first = run(immediate(), SWAP, swap_prices)
    buys_first = run(immediate(sells_before_buys=False), SWAP, swap_prices)

    assert steps(sells_first) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.01, 1.0),
        (utc("2026-11-18T16:01Z"), "AAPL", "complete", -0.01, 0.0),
        (utc("2026-11-18T16:01Z"), "ILLQ", "complete", 0.02, 1.0),
    ]
    # Booked first, the buy finds no cash while the sell is pending: it waits for
    # its next price, after the sell filled.
    assert steps(buys_first) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.01, 1.0),
        (utc("2026-11-18T16:01Z"), "AAPL", "complete", -0.01, 0.0),
        (utc("2026-11-18T16:02Z"), "ILLQ", "complete", 0.02, 1.0),
    ]


def test_a_buy_waits_for_the_cash_of_a_halted_sell() -> None:
    result = run(immediate(), SWAP, HALTED_SELL)

    assert steps(result) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.01, 1.0),
        (utc("2026-11-18T18:01Z"), "AAPL", "complete", -0.01, 0.0),
        (utc("2026-11-18T18:02Z"), "ILLQ", "complete", 0.02, 1.0),
    ]


def test_negative_cash_lets_a_buy_fill_part_before_the_sell() -> None:
    """With 50% of NAV of negative cash, ILLQ buys half at 16:01, the rest after the sale."""
    result = run(immediate(negative_cash="fraction_of_nav", negative_cash_limit=0.5), SWAP, HALTED_SELL)

    assert steps(result) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.01, 1.0),
        (utc("2026-11-18T16:01Z"), "ILLQ", "partial", 0.01, 0.5),
        (utc("2026-11-18T18:01Z"), "AAPL", "complete", -0.01, 0.0),
        (utc("2026-11-18T18:02Z"), "ILLQ", "complete", 0.01, 1.0),
    ]
    assert state_of(result, "2026-11-18T16:01Z", "ILLQ")["cash"] == pytest.approx(-0.5)
    assert state_of(result, "2026-11-18T18:02Z", "ILLQ")["cash"] == pytest.approx(0.0)


def test_negative_cash_resumes_across_runs() -> None:
    """The partial fill, the cash and the open order carry from one run to the next."""
    signals = PublishedTable.build(
        "signals", SWAP, index=["time_index", "signal_uid", ASSET_IDENTIFIER]
    )
    published = PublishedTable.build(
        "prices", HALTED_SELL, index=["time_index", ASSET_IDENTIFIER]
    )
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=immediate(negative_cash="fraction_of_nav", negative_cash_limit=0.5),
            signals=signals,
            prices=published,
            storage=storage,
        )
        first = runner.run("2026-11-18T16:30:00Z")
        second = runner.run("2026-11-18T17:30:00Z")
        third = runner.run("2026-11-18T18:30:00Z")
        whole = runner.persisted.reset_index()

    assert len(first) == 2 and second.empty and len(third) == 2
    in_one_run = run(immediate(negative_cash="fraction_of_nav", negative_cash_limit=0.5), SWAP, HALTED_SELL)
    assert rounded(whole) == rounded(in_one_run)
    assert [json.loads(state)["cash"] for state in whole["strategy_state"]] == pytest.approx(
        [json.loads(state)["cash"] for state in in_one_run["strategy_state"]]
    )


def test_a_buy_cash_cannot_cover_is_cut_and_the_rest_cancelled() -> None:
    """$200 sized at 100 for ILLQ; it fills at 105, so $210 would be needed.

    AAPL's sale is not part of this rebalance, so no cash is coming: ILLQ buys what
    the $200 allows, 95.24% of its order, and the rest is cancelled with a reason.
    """
    result = run(
        immediate(),
        signal_frame(
            [
                ("2026-11-18T15:00:00Z", {"AAPL": 0.8}),
                ("2026-11-18T16:00:00Z", {"AAPL": 0.8, "ILLQ": 0.2}),
            ]
        ),
        prices(
            ("AAPL", "2026-11-18T14:45Z", 100.0),
            ("ILLQ", "2026-11-18T14:45Z", 100.0),
            ("AAPL", "2026-11-18T15:01Z", 100.0),
            ("ILLQ", "2026-11-18T16:01Z", 105.0),
        ),
    )

    bought = 0.2 / 105.0
    assert steps(result) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.008, 0.8),
        (utc("2026-11-18T16:01Z"), "ILLQ", "cancelled", bought, 0.2),
    ]
    state = state_of(result, "2026-11-18T16:01Z", "ILLQ")
    assert state["order_shares"] == pytest.approx(0.002)
    assert state["fill_fraction"] == pytest.approx(200.0 / 210.0)
    assert state["cancelled_shares"] == pytest.approx(0.002 - bought)
    assert state["cancel_reason"] == "insufficient_cash"
    assert state["cash"] == pytest.approx(0.0, abs=1e-12)


def test_buys_at_one_instant_share_too_little_cash_pro_rata() -> None:
    """$1,000,000 of cash; two buys sized at $500,000 each fill at 105: $525,000 each.

    Each fills 1,000,000 / 1,050,000 = 95.24% of its order; the rest is cancelled.
    """
    result = run(
        immediate(),
        signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 0.5, "ILLQ": 0.5})]),
        prices(
            ("AAPL", "2026-11-18T14:45Z", 100.0),
            ("ILLQ", "2026-11-18T14:45Z", 100.0),
            ("AAPL", "2026-11-18T15:01Z", 105.0),
            ("ILLQ", "2026-11-18T15:01Z", 105.0),
        ),
    )

    share = 0.005 / 1.05
    assert steps(result) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "cancelled", share, 0.5),
        (utc("2026-11-18T15:01Z"), "ILLQ", "cancelled", share, 0.5),
    ]
    for asset in ("AAPL", "ILLQ"):
        state = state_of(result, "2026-11-18T15:01Z", asset)
        assert state["fill_fraction"] == pytest.approx(1.0 / 1.05)
        assert state["cancel_reason"] == "insufficient_cash"


@pytest.mark.parametrize(
    ("sizing", "shares", "weight"),
    [
        # 0.5 x NAV 1 / 100 at the decision; worth 0.55 at 110.
        ("at_decision", 0.005, 0.55),
        # 0.5 x NAV 1 / 110 at the fill.
        ("at_fill", 0.5 / 110.0, 0.5),
    ],
)
def test_shares_are_sized_at_the_decision_or_at_the_fill(sizing, shares, weight) -> None:
    result = run(
        immediate(sizing=sizing),
        signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 0.5})]),
        prices(("AAPL", "2026-11-18T14:45Z", 100.0), ("AAPL", "2026-11-18T15:01Z", 110.0)),
    )

    assert steps(result) == [(utc("2026-11-18T15:01Z"), "AAPL", "complete", shares, weight)]


@pytest.mark.parametrize(
    ("gating", "fill_time"),
    [("portfolio_calendar", "2026-11-19T14:31Z"), ("none", "2026-11-18T21:30Z")],
)
def test_calendar_gating_can_be_turned_off(gating, fill_time) -> None:
    """A signal after Wednesday's close; a price is observed after hours at 21:30."""
    result = run(
        immediate(calendar_gating=gating),
        signal_frame([("2026-11-18T21:15:00Z", {"AAPL": 0.5})]),
        prices(
            ("AAPL", "2026-11-18T20:00Z", 100.0),
            ("AAPL", "2026-11-18T21:30Z", 100.0),
            ("AAPL", "2026-11-19T14:31Z", 100.0),
        ),
    )

    assert [time for time, *_ in steps(result)] == [utc(fill_time)]


# --- The ledger books what PortfolioRebalance recorded --------------------------------------


@pytest.mark.parametrize(("sizing", "shares"), [("at_decision", 50.0), ("at_fill", 45.0)])
def test_the_ledger_sizes_when_the_policy_says(sizing, shares) -> None:
    """NAV $10,000, target 0.5: 5,000 / 100 at the decision, or 5,000 / 110 at the fill."""
    strategy = stock_strategy(
        calendar(), execution_policy=ExecutionPolicy(sizing=sizing)
    )
    price_rows = prices(("AAPL", "2026-11-18T14:45Z", 100.0), ("AAPL", "2026-11-18T15:01Z", 110.0))
    state = run(strategy, signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 0.5})]), price_rows)

    ledger = book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    assert position_deltas(ledger) == [(utc("2026-11-18T15:01Z"), "AAPL", shares, 110.0)]


def test_the_ledger_books_the_filled_part_of_its_own_order_and_the_cancellation() -> None:
    """NAV $10,000. ILLQ's order is 0.2 x 10,000 / 100 = 20 shares; 95.24% filled: 19."""
    strategy = stock_strategy(calendar(), assets=("AAPL", "ILLQ"))
    price_rows = prices(
        ("AAPL", "2026-11-18T14:45Z", 100.0),
        ("ILLQ", "2026-11-18T14:45Z", 100.0),
        ("AAPL", "2026-11-18T15:01Z", 100.0),
        ("ILLQ", "2026-11-18T16:01Z", 105.0),
    )
    state = run(
        strategy,
        signal_frame(
            [
                ("2026-11-18T15:00:00Z", {"AAPL": 0.8}),
                ("2026-11-18T16:00:00Z", {"AAPL": 0.8, "ILLQ": 0.2}),
            ]
        ),
        price_rows,
    )

    ledger = book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    assert position_deltas(ledger) == [
        (utc("2026-11-18T15:01Z"), "AAPL", 80.0, 100.0),
        (utc("2026-11-18T16:01Z"), "ILLQ", 19.0, 105.0),
    ]
    [illiquid] = progress(ledger, "ILLQ")
    assert illiquid["execution_status"] == "cancelled"
    assert illiquid["strategy_state"]["cancel_reason"] == "insufficient_cash"


def test_the_ledger_records_a_cancellation_that_filled_nothing() -> None:
    """Fully invested in AAPL with no negative cash: the ILLQ buy has no cash at all."""
    strategy = stock_strategy(calendar(), assets=("AAPL", "ILLQ"))
    price_rows = prices(
        ("AAPL", "2026-11-18T14:45Z", 100.0),
        ("ILLQ", "2026-11-18T14:45Z", 100.0),
        ("AAPL", "2026-11-18T15:01Z", 100.0),
        ("ILLQ", "2026-11-18T16:01Z", 100.0),
    )
    state = run(
        strategy,
        signal_frame(
            [
                ("2026-11-18T15:00:00Z", {"AAPL": 1.0}),
                ("2026-11-18T16:00:00Z", {"AAPL": 1.0, "ILLQ": 0.1}),
            ]
        ),
        price_rows,
    )
    cancelled = state[state[ASSET_IDENTIFIER] == "ILLQ"].iloc[0]
    assert cancelled["execution_status"] == "cancelled"
    assert cancelled["executed_quantity"] == 0.0
    assert pd.isna(cancelled["execution_price"])

    ledger = book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    assert [asset for _time, asset, _delta, _price in position_deltas(ledger)] == ["AAPL"]
    [illiquid] = progress(ledger, "ILLQ")
    assert illiquid["execution_status"] == "cancelled"
    assert illiquid["strategy_state"]["cancel_reason"] == "insufficient_cash"


def test_the_ledger_cuts_a_buy_its_own_costs_leave_uncovered() -> None:
    """A 1% cost is the ledger's alone: 100 shares at 100 would need $10,100."""
    strategy = stock_strategy(calendar()).model_copy(
        update={
            "execution_cost_model_instances": (ProportionalExecutionCostModel(rate=0.01),),
        }
    )
    price_rows = prices(("AAPL", "2026-11-18T14:45Z", 100.0), ("AAPL", "2026-11-18T15:01Z", 100.0))
    state = run(
        strategy,
        signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 1.0})]),
        price_rows,
    )

    ledger = book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    # 10,000 / 10,100 of the order, rounded down: 99 shares, $9,900 plus $99 of cost.
    assert position_deltas(ledger) == [(utc("2026-11-18T15:01Z"), "AAPL", 99.0, 100.0)]
    [apple] = progress(ledger, "AAPL")
    assert apple["ledger_cut"] == {"quantity": 1.0, "reason": "insufficient_cash"}
