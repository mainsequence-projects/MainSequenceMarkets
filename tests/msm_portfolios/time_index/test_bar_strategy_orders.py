"""Bar strategies size the order at the decision and apply the cash setting (issue #90).

`TimeWeighted`, `VolumeParticipation`, `LiquidityConstrained` and
`TrailingAverageDailyVolumeParticipation` trade at their own bars. A new target is
sized once, at its decision: target weight x NAV / price, with the last bar of each
asset strictly before the earliest moment, the first of the strategy's bars strictly
after the signal (ADR 0058). Each bar then fills a slice of that fixed order, as the
strategy's own logic decides it (elapsed time, volume, liquidity, trailing daily
volume), and the slices never add up to more than the order. The execution policy's
cash setting applies to the fills as it does to `ImmediateSignal`'s: sells before buys,
buys limited to the cash plus the allowed negative cash, buys short of cash at one bar
filling the same fraction, and once the rebalance's sells have filled, what a buy
cannot pay is cut and cancelled (`insufficient_cash`).

The book's unit is the NAV at the portfolio's first rebalance, the ledger's initial NAV
(ADR 0065). For the three strategies sized in money or volume, a bar's capacity of `q`
shares is `q / unit` shares of the book.

All times are Wednesday 2026-11-18 UTC unless stated.
"""

from __future__ import annotations

import json
import uuid

import pandas as pd
import pytest

from msm_portfolios.configuration import compute_strategy_revision
from msm_portfolios.rebalance_strategy import (
    ExecutionPolicy,
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.storage import PortfolioRebalanceStateStorage
from tests.support.pinned_identities import _bound
from tests.support.rebalance import (
    IncrementalRebalance,
    PublishedTable,
    book,
    marks,
    position_deltas,
    signal_frame,
    stock_execution_model,
    utc,
)

KINDS = (
    "time_weighted",
    "volume_participation",
    "liquidity_constrained",
    "trailing_average_daily_volume",
)
BAR_INDEX = ["time_index", ASSET_IDENTIFIER]


def bars(*rows: tuple[str, str, float, float]) -> pd.DataFrame:
    """``(time, asset, price, volume)`` bars; a bar's available notional is price x volume."""
    frame = pd.DataFrame(
        [(utc(stamp), asset, price, volume) for stamp, asset, price, volume in rows],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    )
    frame["available_notional"] = frame["close"] * frame["volume"]
    return frame.set_index(BAR_INDEX)


def daily_liquidity(assets: tuple[str, ...]) -> pd.DataFrame:
    """Two completed days of $100,000,000: the daily cap never binds."""
    return pd.DataFrame(
        [
            (utc(stamp), asset, 100.0, 1_000_000.0)
            for stamp in ("2026-11-16T21:00Z", "2026-11-17T21:00Z")
            for asset in assets
        ],
        columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
    ).set_index(BAR_INDEX)


ASSETS = ("AAPL", "ILLQ", "MSFT")
DAILY = daily_liquidity(ASSETS)


def strategy(kind: str, frame: pd.DataFrame, **fields):
    """Each strategy trades 10% of a bar's volume, on a $10,000 book.

    ``TimeWeighted`` spreads an order evenly over the time from its earliest moment to
    12:30, the end of its window.
    """
    source = PublishedTable.build("bars", frame, index=BAR_INDEX)
    if kind == "time_weighted":
        return TimeWeighted(
            execution_bars_instance=source,
            rebalance_start="09:00",
            rebalance_end="12:30",
            **fields,
        )
    sized = fields
    if kind == "volume_participation":
        return VolumeParticipation(
            execution_bars_instance=source, max_percent_volume_in_bar=0.1, **sized
        )
    if kind == "liquidity_constrained":
        return LiquidityConstrained(
            liquidity_source_instance=source,
            price_column="close",
            max_liquidity_fraction=0.1,
            **sized,
        )
    return TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=PublishedTable.build("daily", DAILY, index=BAR_INDEX),
        execution_bars_instance=source,
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="09:00",
        execution_end="23:00",
        max_daily_participation=1.0,
        max_bar_participation=0.1,
        **sized,
    )


def inputs(strategy, frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        name: DAILY if name == "daily_liquidity" else frame
        for name in strategy.declared_dependencies()
    }


def run(
    strategy,
    frame: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    unit_value: float | None = 10_000.0,
) -> pd.DataFrame:
    return strategy.build_transitions(
        start=utc("2026-11-18T00:00Z"),
        end=utc("2026-11-18T23:00Z"),
        signal_observations=signals,
        observed_inputs=inputs(strategy, frame),
        previous_state=None,
        book_unit_value=unit_value,
    )


def state(row) -> dict:
    return json.loads(row["strategy_state"])


def steps(result: pd.DataFrame, asset: str | None = None) -> list[tuple]:
    """``(time, asset, status, shares)`` of every row, in order."""
    if result.empty:
        return []
    ordered = result.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
    if asset is not None:
        ordered = ordered[ordered[ASSET_IDENTIFIER] == asset]
    return [
        (
            utc(row["time_index"]),
            row[ASSET_IDENTIFIER],
            row["execution_status"],
            pytest.approx(row["executed_quantity"], abs=1e-12),
        )
        for row in ordered.to_dict(orient="records")
    ]


# --- The order is fixed at the decision and filled in slices -----------------------------


ONE_ORDER = bars(
    ("2026-11-18T09:30Z", "AAPL", 100.0, 100.0),
    ("2026-11-18T10:30Z", "AAPL", 100.0, 100.0),
    ("2026-11-18T11:00Z", "AAPL", 102.0, 100.0),
    ("2026-11-18T11:30Z", "AAPL", 98.0, 100.0),
    ("2026-11-18T12:00Z", "AAPL", 101.0, 100.0),
    ("2026-11-18T12:30Z", "AAPL", 99.0, 100.0),
    ("2026-11-18T13:00Z", "AAPL", 100.0, 100.0),
)
TEN = signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.45})])
CAPACITY_SLICES = [
    (utc("2026-11-18T10:30Z"), "AAPL", "partial", pytest.approx(0.001)),
    (utc("2026-11-18T11:00Z"), "AAPL", "partial", pytest.approx(0.001)),
    (utc("2026-11-18T11:30Z"), "AAPL", "partial", pytest.approx(0.001)),
    (utc("2026-11-18T12:00Z"), "AAPL", "partial", pytest.approx(0.001)),
    (utc("2026-11-18T12:30Z"), "AAPL", "complete", pytest.approx(0.0005)),
]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            # A quarter of the order at each half hour from 10:30, its earliest moment,
            # to 12:30; nothing at 10:30 itself.
            "time_weighted",
            [
                (utc("2026-11-18T11:00Z"), "AAPL", "partial", pytest.approx(0.001125)),
                (utc("2026-11-18T11:30Z"), "AAPL", "partial", pytest.approx(0.001125)),
                (utc("2026-11-18T12:00Z"), "AAPL", "partial", pytest.approx(0.001125)),
                (utc("2026-11-18T12:30Z"), "AAPL", "complete", pytest.approx(0.001125)),
            ],
        ),
        # 10 of a bar's 100 shares is 10 / 10,000 of the book; the last slice is what
        # is left of the order.
        ("volume_participation", CAPACITY_SLICES),
        ("liquidity_constrained", CAPACITY_SLICES),
        ("trailing_average_daily_volume", CAPACITY_SLICES),
    ],
)
def test_the_slices_of_an_order_add_up_to_the_quantity_decided(kind, expected) -> None:
    """0.45 of a NAV of 1 at the 09:30 bar's 100: an order of 0.0045 of the book.

    That is 45 shares of a $10,000 book. The prices move while it fills, so the weights
    each slice reaches differ, but the shares add up to the order exactly.
    """
    result = run(strategy(kind, ONE_ORDER), ONE_ORDER, TEN)

    assert steps(result) == expected
    states = [state(row) for row in result.to_dict(orient="records")]
    assert [item["target_shares"] for item in states] == [pytest.approx(0.0045)] * len(states)
    assert [item["order_shares"] for item in states] == [pytest.approx(0.0045)] * len(states)
    assert result["executed_quantity"].sum() == pytest.approx(0.0045, abs=1e-15)
    filled = [item["filled_shares"] for item in states]
    assert filled == sorted(filled)
    assert max(filled) == pytest.approx(0.0045)
    assert all(value <= 0.0045 + 1e-15 for value in filled)
    assert states[-1]["remaining_shares"] == 0.0
    assert states[-1]["held_shares"] == pytest.approx(0.0045)
    # Each slice fills at its own bar's observed price, strictly after the signal.
    prices = ONE_ORDER.xs("AAPL", level=ASSET_IDENTIFIER)["close"]
    for row in result.to_dict(orient="records"):
        assert row["time_index"] > utc("2026-11-18T10:00Z")
        assert row["execution_price"] == prices.loc[row["time_index"]]
        assert row["event_source"] in {"execution_bars", "available_liquidity"}


@pytest.mark.parametrize("kind", KINDS)
def test_the_order_is_sized_with_the_last_bar_before_the_earliest_moment(kind) -> None:
    """The 10:00:00 signal's earliest moment is the 10:30 bar, the first after it.

    It is sized at the 10:00 bar's 200: the last strictly before 10:30. Neither the 09:30
    bar nor the 10:30 bar it first fills at sizes it.
    """
    frame = bars(
        ("2026-11-18T09:30Z", "AAPL", 100.0, 1_000_000.0),
        ("2026-11-18T10:00Z", "AAPL", 200.0, 1_000_000.0),
        ("2026-11-18T10:30Z", "AAPL", 400.0, 1_000_000.0),
        ("2026-11-18T11:00Z", "AAPL", 400.0, 1_000_000.0),
    )
    result = run(
        strategy(kind, frame), frame, signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5})])
    )

    decision = state(result.iloc[0])
    assert decision["earliest_time_index"] == "2026-11-18T10:30:00+00:00"
    assert decision["decision_price"] == 200.0
    assert decision["decision_nav"] == 1.0
    assert decision["target_shares"] == pytest.approx(0.5 / 200.0)


def test_a_signal_outside_the_window_is_sized_at_the_bar_before_the_window_opens() -> None:
    """The window opens at 12:00: the earliest moment is the 12:00 bar.

    The 11:30 bar, outside the window, is the last before it and sizes the order.
    """
    frame = bars(
        ("2026-11-18T10:30Z", "AAPL", 300.0, 1_000_000.0),
        ("2026-11-18T11:30Z", "AAPL", 350.0, 1_000_000.0),
        ("2026-11-18T12:00Z", "AAPL", 400.0, 1_000_000.0),
    )
    result = run(
        strategy("volume_participation", frame, rebalance_start="12:00"),
        frame,
        signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5})]),
    )

    assert steps(result) == [
        (utc("2026-11-18T12:00Z"), "AAPL", "complete", pytest.approx(0.5 / 350.0))
    ]
    decision = state(result.iloc[0])
    assert decision["earliest_time_index"] == "2026-11-18T12:00:00+00:00"
    assert decision["decision_price"] == 350.0


def test_an_order_without_a_bar_before_its_earliest_moment_cannot_be_sized() -> None:
    frame = bars(("2026-11-18T10:30Z", "AAPL", 100.0, 100.0))

    with pytest.raises(ValueError, match="No observed price before the rebalance's earliest"):
        run(
            strategy("volume_participation", frame),
            frame,
            signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5})]),
        )


# --- The cash setting ---------------------------------------------------------------------


SALE_BARS = ("10:30", "11:00", "11:30", "12:00", "12:30")


def swap_bars(*, buy_price: float, buys=("ILLQ",), stamps=SALE_BARS) -> pd.DataFrame:
    """AAPL is bought at 09:30, then sold 20 shares a bar at ``stamps``.

    The assets bought at 10:30 and after have all the volume they need, at ``buy_price``.
    """
    rows = [("2026-11-18T09:00Z", asset, 100.0, 1_000_000.0) for asset in ("AAPL", *buys)]
    rows += [("2026-11-18T09:30Z", asset, 100.0, 1_000_000.0) for asset in ("AAPL", *buys)]
    for stamp in stamps:
        rows.append((f"2026-11-18T{stamp}Z", "AAPL", 100.0, 200.0))
        rows += [(f"2026-11-18T{stamp}Z", asset, buy_price, 1_000_000.0) for asset in buys]
    return bars(*rows)


def swap_signals(weights: dict[str, float]) -> pd.DataFrame:
    """All in AAPL at 09:10; the 10:00 target sells it for ``weights``."""
    return signal_frame(
        [("2026-11-18T09:10:00Z", {"AAPL": 1.0}), ("2026-11-18T10:00:00Z", weights)]
    )


@pytest.mark.parametrize(
    ("buy_price", "expected"),
    [
        (
            # Each bar's sale pays for the same value of ILLQ; the last sale pays for
            # the rest.
            100.0,
            [
                (utc("2026-11-18T10:30Z"), "ILLQ", "partial", pytest.approx(0.002)),
                (utc("2026-11-18T11:00Z"), "ILLQ", "partial", pytest.approx(0.002)),
                (utc("2026-11-18T11:30Z"), "ILLQ", "partial", pytest.approx(0.002)),
                (utc("2026-11-18T12:00Z"), "ILLQ", "partial", pytest.approx(0.002)),
                (utc("2026-11-18T12:30Z"), "ILLQ", "complete", pytest.approx(0.002)),
            ],
        ),
        (
            # Sized at 100, ILLQ fills at 105: each sale buys 0.2 / 105 of it. Once the
            # last sale has filled, what is left of the order is cut: 95.24% filled.
            105.0,
            [
                (utc("2026-11-18T10:30Z"), "ILLQ", "partial", pytest.approx(0.2 / 105.0)),
                (utc("2026-11-18T11:00Z"), "ILLQ", "partial", pytest.approx(0.2 / 105.0)),
                (utc("2026-11-18T11:30Z"), "ILLQ", "partial", pytest.approx(0.2 / 105.0)),
                (utc("2026-11-18T12:00Z"), "ILLQ", "partial", pytest.approx(0.2 / 105.0)),
                (utc("2026-11-18T12:30Z"), "ILLQ", "cancelled", pytest.approx(0.2 / 105.0)),
            ],
        ),
    ],
)
def test_a_cash_limited_buy_is_spread_over_the_bars_its_sales_pay_for(
    buy_price, expected
) -> None:
    """Fully invested in AAPL, the 10:00 target is all ILLQ, which has the volume.

    No negative cash is allowed: at each bar the sale of 20 AAPL is booked first and its
    cash pays for ILLQ; the rest of the buy waits for the next sale.
    """
    frame = swap_bars(buy_price=buy_price)
    result = run(strategy("volume_participation", frame), frame, swap_signals({"ILLQ": 1.0}))

    assert steps(result, "ILLQ") == expected
    assert steps(result, "AAPL")[1:] == [
        (utc(f"2026-11-18T{stamp}Z"), "AAPL", status, pytest.approx(-0.002))
        for stamp, status in (
            ("10:30", "partial"),
            ("11:00", "partial"),
            ("11:30", "partial"),
            ("12:00", "partial"),
            ("12:30", "complete"),
        )
    ]
    for row in result.to_dict(orient="records"):
        assert state(row)["cash"] >= -1e-12
    last = state(result[result[ASSET_IDENTIFIER] == "ILLQ"].iloc[-1])
    if buy_price == 100.0:
        assert last["cancel_reason"] is None
        assert last["held_shares"] == pytest.approx(0.01)
    else:
        assert last["cancel_reason"] == "insufficient_cash"
        assert last["held_shares"] == pytest.approx(1.0 / 105.0)
        assert last["filled_shares"] / last["order_shares"] == pytest.approx(100.0 / 105.0)
        assert last["cancelled_shares"] == pytest.approx(0.01 - 1.0 / 105.0)
        assert last["cash"] == pytest.approx(0.0, abs=1e-12)


def test_negative_cash_lets_a_buy_run_ahead_of_its_sales() -> None:
    """With half the NAV of negative cash, ILLQ buys 0.7 of NAV at 10:30.

    Its cash is then -0.5, the limit: each later sale pays for 0.2 more until the order
    is complete.
    """
    frame = swap_bars(buy_price=100.0)
    result = run(
        strategy(
            "volume_participation",
            frame,
            execution_policy=ExecutionPolicy(
                negative_cash="fraction_of_nav", negative_cash_limit=0.5
            ),
        ),
        frame,
        swap_signals({"ILLQ": 1.0}),
    )

    assert steps(result, "ILLQ") == [
        (utc("2026-11-18T10:30Z"), "ILLQ", "partial", pytest.approx(0.007)),
        (utc("2026-11-18T11:00Z"), "ILLQ", "partial", pytest.approx(0.002)),
        (utc("2026-11-18T11:30Z"), "ILLQ", "complete", pytest.approx(0.001)),
    ]
    assert state(result[result[ASSET_IDENTIFIER] == "ILLQ"].iloc[0])["cash"] == pytest.approx(
        -0.5
    )


@pytest.mark.parametrize(
    ("msm_volume", "msm_slice"),
    [
        # MSFT has the volume for all of its order at every bar.
        (1_000_000.0, None),
        # MSFT can trade 20 shares a bar: it competes with that slice, not its order.
        (200.0, 0.002),
    ],
)
def test_buys_competing_for_cash_fill_the_same_fraction_at_each_bar(
    msm_volume, msm_slice
) -> None:
    """The 10:00 target sells AAPL for 0.6 of ILLQ and 0.4 of MSFT, both at 105.

    Each bar's sale pays for 0.2 of NAV. ILLQ and MSFT share it: each fills the same
    fraction of what it would trade at that bar. Once the last sale has filled, both
    are cut, each by the same fraction.
    """
    frame = swap_bars(buy_price=105.0, buys=("ILLQ", "MSFT"))
    frame.loc[
        (frame.index.get_level_values("time_index") >= utc("2026-11-18T10:30Z"))
        & (frame.index.get_level_values(ASSET_IDENTIFIER) == "MSFT"),
        "volume",
    ] = msm_volume
    result = run(
        strategy("volume_participation", frame),
        frame,
        swap_signals({"ILLQ": 0.6, "MSFT": 0.4}),
    )
    buys = result[result[ASSET_IDENTIFIER].isin(["ILLQ", "MSFT"])]

    assert sorted(set(buys["time_index"])) == [
        utc(f"2026-11-18T{stamp}Z") for stamp in ("10:30", "11:00", "11:30", "12:00", "12:30")
    ]
    for time_index, at_bar in buys.groupby("time_index"):
        fractions = []
        for row in at_bar.to_dict(orient="records"):
            row_state = state(row)
            open_before = abs(row["executed_quantity"]) + abs(row_state["remaining_shares"])
            if row["execution_status"] == "cancelled":
                open_before += abs(row_state["cancelled_shares"])
            wanted = open_before
            if row[ASSET_IDENTIFIER] == "MSFT" and msm_slice is not None:
                wanted = min(open_before, msm_slice)
            fractions.append(abs(row["executed_quantity"]) / wanted)
        assert fractions[0] == pytest.approx(fractions[1]), time_index
        # What the buys pay at a bar is the cash its sale freed.
        paid = (at_bar["executed_quantity"] * at_bar["execution_price"]).sum()
        assert paid == pytest.approx(0.2)
    last = buys[buys["time_index"] == utc("2026-11-18T12:30Z")]
    assert set(last["execution_status"]) == {"cancelled"}
    assert {state(row)["cancel_reason"] for row in last.to_dict("records")} == {
        "insufficient_cash"
    }
    assert state(result.sort_values("time_index").iloc[-1])["cash"] == pytest.approx(
        0.0, abs=1e-12
    )


def test_the_trailing_daily_cap_counts_what_filled_not_what_the_bar_allowed() -> None:
    """ILLQ's bar allows 10% of 1,000,000 shares; the cash of each sale buys 20 of them."""
    frame = swap_bars(buy_price=100.0)
    result = run(
        strategy("trailing_average_daily_volume", frame), frame, swap_signals({"ILLQ": 1.0})
    )
    illiquid = result[result[ASSET_IDENTIFIER] == "ILLQ"]

    consumed = [state(row)["bar"]["daily_notional_consumed"] for row in illiquid.to_dict("records")]
    # $2,000 of a $10,000 book at each of the five bars.
    assert consumed == pytest.approx([2_000.0, 4_000.0, 6_000.0, 8_000.0, 10_000.0])


# --- A halted asset ------------------------------------------------------------------------


def with_halt(frame: pd.DataFrame, asset: str, stamps: tuple[str, ...]) -> pd.DataFrame:
    halted = frame.index.isin([(utc(stamp), asset) for stamp in stamps])
    return frame[~halted]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            # 10 shares a bar, none while halted; it resumes after the halt.
            "volume_participation",
            [
                (utc("2026-11-18T10:30Z"), "AAPL", "partial", pytest.approx(0.001)),
                (utc("2026-11-18T11:00Z"), "AAPL", "partial", pytest.approx(0.001)),
                (utc("2026-11-18T12:30Z"), "AAPL", "partial", pytest.approx(0.001)),
                (utc("2026-11-18T13:00Z"), "AAPL", "partial", pytest.approx(0.001)),
                (utc("2026-11-18T13:30Z"), "AAPL", "complete", pytest.approx(0.0005)),
            ],
        ),
        (
            # Its clock runs through the halt: at 12:30 it catches up to all of it.
            "time_weighted",
            [
                (utc("2026-11-18T11:00Z"), "AAPL", "partial", pytest.approx(0.001125)),
                (utc("2026-11-18T12:30Z"), "AAPL", "complete", pytest.approx(0.003375)),
            ],
        ),
    ],
)
def test_a_halted_asset_fills_nothing_and_resumes_its_order_after_the_halt(
    kind, expected
) -> None:
    """AAPL has no bars at 11:30 and 12:00; MSFT trades through the halt."""
    stamps = ("09:30", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30")
    frame = with_halt(
        bars(
            *(
                (f"2026-11-18T{stamp}Z", asset, 100.0, 100.0)
                for stamp in stamps
                for asset in ("AAPL", "MSFT")
            )
        ),
        "AAPL",
        ("2026-11-18T11:30Z", "2026-11-18T12:00Z"),
    )
    result = run(strategy(kind, frame), frame, TEN)

    assert steps(result) == expected


def test_a_halted_sale_makes_the_buy_wait_for_its_cash() -> None:
    """AAPL's sale is halted at 11:30 and 12:00: ILLQ has bars but no cash, and waits."""
    frame = with_halt(
        swap_bars(buy_price=100.0, stamps=(*SALE_BARS, "13:00", "13:30")),
        "AAPL",
        ("2026-11-18T11:30Z", "2026-11-18T12:00Z"),
    )
    result = run(strategy("volume_participation", frame), frame, swap_signals({"ILLQ": 1.0}))

    assert steps(result, "ILLQ") == [
        (utc(f"2026-11-18T{stamp}Z"), "ILLQ", status, pytest.approx(0.002))
        for stamp, status in (
            ("10:30", "partial"),
            ("11:00", "partial"),
            ("12:30", "partial"),
            ("13:00", "partial"),
            ("13:30", "complete"),
        )
    ]


# --- The book: resumed runs, the weights path and the ledger -------------------------------


def resume_bars() -> pd.DataFrame:
    """AAPL and ILLQ every half hour from 09:00 to 13:30, prices moving."""
    stamps = [f"{hour:02d}:{minute:02d}" for hour in range(9, 14) for minute in (0, 30)]
    rows = []
    for position, stamp in enumerate(stamps):
        rows.append((f"2026-11-18T{stamp}Z", "AAPL", 100.0 + position, 200.0))
        rows.append((f"2026-11-18T{stamp}Z", "ILLQ", 50.0 - position, 300.0))
    return bars(*rows)


def incremental(kind: str, run_times: list[str]) -> pd.DataFrame:
    """Run ``PortfolioRebalance`` at each of ``run_times`` and return what it stored."""
    frame = resume_bars()
    built = strategy(kind, frame)
    signals = PublishedTable.build(
        "signals",
        signal_frame(
            [
                ("2026-11-18T09:10:00Z", {"AAPL": 1.0}),
                ("2026-11-18T10:00:00Z", {"AAPL": 0.2, "ILLQ": 0.8}),
            ]
        ),
        index=["time_index", "signal_uid", ASSET_IDENTIFIER],
    )
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=built,
            signals=signals,
            prices=PublishedTable.build("prices", frame, index=BAR_INDEX),
            storage=storage,
        )
        for run_time in run_times:
            runner.run(run_time)
    return runner.persisted.reset_index()


def approximate(value):
    if isinstance(value, dict):
        return {key: approximate(item) for key, item in value.items()}
    if isinstance(value, float):
        return pytest.approx(value, abs=1e-12)
    return value


def comparable(rows: pd.DataFrame) -> list[tuple]:
    ordered = rows.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
    return [
        (
            utc(row["time_index"]),
            row[ASSET_IDENTIFIER],
            row["execution_status"],
            pytest.approx(row["executed_quantity"], abs=1e-12),
            pytest.approx(row["weight_after"], abs=1e-12),
            approximate(state(row)),
        )
        for row in ordered.to_dict(orient="records")
    ]


@pytest.mark.parametrize("kind", KINDS)
def test_a_resumed_run_equals_one_full_run(kind) -> None:
    """Runs between the bars rebuild the book from the rows they stored."""
    full = incremental(kind, ["2026-11-18T14:00:00Z"])
    resumed = incremental(
        kind,
        [
            "2026-11-18T09:15:00Z",
            "2026-11-18T09:45:00Z",
            "2026-11-18T10:15:00Z",
            "2026-11-18T10:45:00Z",
            "2026-11-18T11:00:00Z",
            "2026-11-18T11:45:00Z",
            "2026-11-18T12:15:00Z",
            "2026-11-18T12:45:00Z",
            "2026-11-18T14:00:00Z",
        ],
    )

    assert set(full[ASSET_IDENTIFIER]) == {"AAPL", "ILLQ"}
    assert comparable(resumed) == comparable(full)


def test_the_position_ledger_books_each_slice_of_the_order_it_decided() -> None:
    """The ledger decides 45 shares at 09:30's 100 and trades each recorded slice of them.

    Its own order is 0.45 x $10,000 / 100; each fill trades the part of it the book's
    fill traded, at the bar's price and time.
    """
    built = strategy("volume_participation", ONE_ORDER).model_copy(
        update={"execution_model_instance": stock_execution_model(("AAPL",))}
    )
    rebalance_state = run(built, ONE_ORDER, TEN)

    ledger = book(
        built,
        rebalance_state,
        marks(ONE_ORDER.reset_index()),
        initial_state="2026-11-18T00:00:00Z",
    )

    assert position_deltas(ledger) == [
        (utc("2026-11-18T10:30Z"), "AAPL", 10.0, 100.0),
        (utc("2026-11-18T11:00Z"), "AAPL", 10.0, 102.0),
        (utc("2026-11-18T11:30Z"), "AAPL", 10.0, 98.0),
        (utc("2026-11-18T12:00Z"), "AAPL", 10.0, 101.0),
        (utc("2026-11-18T12:30Z"), "AAPL", 5.0, 99.0),
    ]


# --- The execution policy -------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_bar_strategies_have_the_execution_policy_with_the_same_defaults(kind) -> None:
    built = strategy(kind, ONE_ORDER)
    immediate = ImmediateSignal.model_fields["execution_policy"]

    assert type(built).model_fields["execution_policy"].annotation is immediate.annotation
    assert built.fill_policy() == ExecutionPolicy()
    assert built.fill_policy() is built.execution_policy
    # The policy is part of the strategy's identity.
    other = strategy(kind, ONE_ORDER, execution_policy=ExecutionPolicy(sells_before_buys=False))
    assert compute_strategy_revision(other) != compute_strategy_revision(built)


def test_a_fixed_cash_amount_is_converted_with_the_ledgers_initial_nav() -> None:
    """$5,000 of negative cash on a $10,000 book is half of the book's first NAV."""
    frame = swap_bars(buy_price=100.0)
    fixed = run(
        strategy(
            "volume_participation",
            frame,
            execution_policy=ExecutionPolicy(
                negative_cash="fixed_amount", negative_cash_limit=5_000.0
            ),
        ),
        frame,
        swap_signals({"ILLQ": 1.0}),
    )
    half = run(
        strategy(
            "volume_participation",
            frame,
            execution_policy=ExecutionPolicy(
                negative_cash="fraction_of_nav", negative_cash_limit=0.5
            ),
        ),
        frame,
        swap_signals({"ILLQ": 1.0}),
    )

    assert steps(fixed) == steps(half)
    # Without the book's unit, the ledger's initial NAV, the amount has no currency.
    with pytest.raises(ValueError, match="needs the book's unit"):
        run(
            strategy(
                "time_weighted",
                frame,
                execution_policy=ExecutionPolicy(
                    negative_cash="fixed_amount", negative_cash_limit=5_000.0
                ),
            ),
            frame,
            swap_signals({"ILLQ": 1.0}),
            unit_value=None,
        )
