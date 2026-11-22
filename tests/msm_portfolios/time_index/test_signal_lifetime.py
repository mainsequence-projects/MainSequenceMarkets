"""A signal older than its strategy's lifetime is disregarded (issue #114).

``RebalanceStrategyBase.signal_lifetime`` is decided by the owner (execution engine
ADR 0001, "Points Outside The Engine's Architecture"). The clock is economic time: an
event at ``t`` acts on the latest signal, which is too old when
``t - signal time_index > signal_lifetime``; a signal exactly that old is still valid.
The last signal is the only candidate. A rebalance whose signal passes its lifetime
keeps what it filled, drops the rest of its orders and ends ``expired``.

All times are 2026-11-18 (a Wednesday; NYSE session 14:30-21:00 UTC) unless stated.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from metatables.updaters.configuration import serialize_argument
from msm_portfolios.configuration import compute_strategy_revision
from msm_portfolios.rebalance_strategy import (
    CalendarEventSignal,
    ExecutionPolicy,
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)
from msm_portfolios.rebalance_strategy.base import TERMINAL_EXECUTION_STATUSES
from msm_portfolios.time_index import compute_portfolio_configuration_hash
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.storage import PortfolioRebalanceStateStorage
from tests.support.pinned_identities import (
    LIBRARY_SIGNALS,
    _bound,
    _portfolio_configuration,
    _source,
)
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

HOUR = dt.timedelta(hours=1)


# --- The field -------------------------------------------------------------------------


def immediate_on(source, **fields) -> ImmediateSignal:
    return ImmediateSignal(calendar_events_instance=source, calendar_identifier="XNYS", **fields)


def test_the_lifetime_is_part_of_the_strategys_identity_only_when_set() -> None:
    events = _source("calendar-events")
    unset = immediate_on(events)
    thirty_minutes = immediate_on(events, signal_lifetime=dt.timedelta(minutes=30))
    twenty_days = immediate_on(events, signal_lifetime="P20D")

    # Not set: absent from the configuration and from what MetaTables hashes, so a
    # strategy without one keeps its identities (tests/identity/test_pinned_identities.py
    # pins them).
    assert unset.signal_lifetime is None
    assert "signal_lifetime" not in unset.model_dump()
    assert "signal_lifetime" not in serialize_argument(unset)["serialized_model"]
    assert thirty_minutes.model_dump()["signal_lifetime"] == dt.timedelta(minutes=30)
    assert serialize_argument(thirty_minutes)["serialized_model"]["signal_lifetime"] == "PT30M"
    assert twenty_days.signal_lifetime == dt.timedelta(days=20)

    # Another lifetime is another strategy and another portfolio.
    strategies = (unset, thirty_minutes, twenty_days)
    assert len({compute_strategy_revision(strategy) for strategy in strategies}) == 3
    signal = LIBRARY_SIGNALS["library_fixed_weights"]
    assert (
        len(
            {
                compute_portfolio_configuration_hash(
                    _portfolio_configuration(signal(), rebalance_strategy=strategy)
                )
                for strategy in strategies
            }
        )
        == 3
    )


def test_every_strategy_has_a_lifetime() -> None:
    bars = _source("bars")
    lifetime = {"signal_lifetime": dt.timedelta(days=20)}
    strategies = [
        immediate_on(_source("calendar-events"), **lifetime),
        CalendarEventSignal(
            calendar_events_instance=_source("calendar-events"),
            calendar_identifier="XNYS",
            **lifetime,
        ),
        TimeWeighted(execution_bars_instance=bars, **lifetime),
        VolumeParticipation(execution_bars_instance=bars, total_notional=1.0, **lifetime),
        LiquidityConstrained(liquidity_source_instance=bars, total_notional=1.0, **lifetime),
        TrailingAverageDailyVolumeParticipation(
            daily_liquidity_instance=bars,
            execution_bars_instance=bars,
            total_notional=1.0,
            **lifetime,
        ),
    ]

    assert {strategy.signal_lifetime for strategy in strategies} == {dt.timedelta(days=20)}


@pytest.mark.parametrize("lifetime", [dt.timedelta(0), dt.timedelta(minutes=-30), "-P1D"])
def test_a_lifetime_must_be_positive(lifetime) -> None:
    with pytest.raises(ValidationError, match=r"(?s)signal_lifetime.*greater than 0"):
        immediate_on(_source("calendar-events"), signal_lifetime=lifetime)


def test_expired_is_a_terminal_status() -> None:
    assert "expired" in TERMINAL_EXECUTION_STATUSES


# --- Rebalances at the next observed price -----------------------------------------------


def fills(result: pd.DataFrame) -> list[tuple[pd.Timestamp, str, float]]:
    """``(time, asset, weight_after)`` of every row that traded at a price."""
    if result.empty:
        return []
    traded = result[result["execution_price"].notna()]
    return [
        (utc(row["time_index"]), row[ASSET_IDENTIFIER], pytest.approx(row["weight_after"]))
        for row in traded.sort_values(["time_index", ASSET_IDENTIFIER]).to_dict("records")
    ]


def steps(result: pd.DataFrame) -> list[tuple]:
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


AFTER_THE_CLOSE = prices(("AAPL", "2026-11-18T20:59Z", 100.0), ("AAPL", "2026-11-19T14:31Z", 100.0))
AT_THE_CLOSE = prices(("AAPL", "2026-11-18T20:59Z", 100.0), ("AAPL", "2026-11-18T21:00Z", 100.0))


@pytest.mark.parametrize(
    ("case", "strategy_class", "fields", "signal", "price_rows", "lifetime", "expected"),
    [
        (
            "after the close; Thursday's open is 17 hours later",
            ImmediateSignal,
            {},
            "2026-11-18T21:30:00Z",
            AFTER_THE_CLOSE,
            dt.timedelta(minutes=30),
            [],
        ),
        (
            "after the close, valid for a day",
            ImmediateSignal,
            {},
            "2026-11-18T21:30:00Z",
            AFTER_THE_CLOSE,
            dt.timedelta(days=1),
            [(utc("2026-11-19T14:31Z"), "AAPL", 0.5)],
        ),
        (
            "after the close, no lifetime",
            ImmediateSignal,
            {},
            "2026-11-18T21:30:00Z",
            AFTER_THE_CLOSE,
            None,
            [(utc("2026-11-19T14:31Z"), "AAPL", 0.5)],
        ),
        (
            "Tuesday's signal at Wednesday's close, 23 hours later",
            CalendarEventSignal,
            {"rebalance_event": "market_close"},
            "2026-11-17T22:00:00Z",
            AT_THE_CLOSE,
            dt.timedelta(hours=20),
            [],
        ),
        (
            "Tuesday's signal at Wednesday's close, valid for a day",
            CalendarEventSignal,
            {"rebalance_event": "market_close"},
            "2026-11-17T22:00:00Z",
            AT_THE_CLOSE,
            dt.timedelta(days=1),
            [(utc("2026-11-18T21:00Z"), "AAPL", 0.5)],
        ),
    ],
)
def test_a_signal_waiting_for_a_closed_market_past_its_lifetime_never_trades(
    case, strategy_class, fields, signal, price_rows, lifetime, expected
) -> None:
    strategy = strategy_class(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        signal_lifetime=lifetime,
        **fields,
    )
    result = run_strategy(
        strategy,
        signals=signal_frame([(signal, {"AAPL": 0.5})]),
        prices=price_rows,
        start="2026-11-17T00:00:00Z",
        end="2026-11-19T23:00:00Z",
    )

    assert fills(result) == expected, case
    if not expected:
        assert result.empty, case


def negative_cash(**fields) -> ImmediateSignal:
    return ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        execution_policy=ExecutionPolicy(negative_cash="fraction_of_nav", negative_cash_limit=0.5),
        **fields,
    )


def run(strategy, signals: pd.DataFrame, price_rows: pd.DataFrame) -> pd.DataFrame:
    return run_strategy(
        strategy,
        signals=signals,
        prices=price_rows,
        start="2026-11-18T00:00:00Z",
        end="2026-11-19T23:00:00Z",
    )


def test_an_expired_rebalance_keeps_what_it_filled_and_drops_the_rest() -> None:
    """Fully invested in AAPL; the 16:00 target is all ILLQ, valid for 1.5 hours.

    With 50% of NAV of negative cash ILLQ buys half at 16:01; the rest waits for the
    cash of AAPL's sale, halted until 18:01. At 18:01 the signal is 2 hours old: both
    orders expire. The portfolio keeps AAPL and the half of ILLQ it bought, and the
    negative cash; nothing trades after.
    """
    result = run(negative_cash(signal_lifetime=dt.timedelta(minutes=90)), SWAP, HALTED_SELL)

    assert steps(result) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.01, 1.0),
        (utc("2026-11-18T16:01Z"), "ILLQ", "partial", 0.01, 0.5),
        (utc("2026-11-18T18:01Z"), "AAPL", "expired", 0.0, 1.0),
        (utc("2026-11-18T18:01Z"), "ILLQ", "expired", 0.0, 0.5),
    ]
    expired = result[result["execution_status"] == "expired"]
    assert expired["execution_price"].isna().all()
    assert expired["executed_weight_delta"].tolist() == [0.0, 0.0]
    illiquid = state_of(result, "2026-11-18T18:01Z", "ILLQ")
    assert illiquid["held_shares"] == pytest.approx(0.01)
    assert illiquid["remaining_shares"] == 0.0
    assert illiquid["cancelled_shares"] == pytest.approx(0.01)
    assert illiquid["cancel_reason"] == "signal_lifetime"
    assert illiquid["cash"] == pytest.approx(-0.5)
    apple = state_of(result, "2026-11-18T18:01Z", "AAPL")
    assert apple["held_shares"] == pytest.approx(0.01)
    assert apple["cancelled_shares"] == pytest.approx(-0.01)

    # Without a lifetime, the same rebalance completes.
    assert [step[2] for step in steps(run(negative_cash(), SWAP, HALTED_SELL))] == [
        "complete",
        "partial",
        "complete",
        "complete",
    ]


def test_a_signal_exactly_its_lifetime_old_still_trades() -> None:
    """The 15:00 target, valid for one hour, fills at 16:00 and expires after it."""
    price_rows = prices(
        ("AAPL", "2026-11-18T14:45Z", 100.0),
        ("ILLQ", "2026-11-18T14:45Z", 50.0),
        ("ILLQ", "2026-11-18T16:00Z", 50.0),
        ("AAPL", "2026-11-18T16:00:01Z", 100.0),
    )
    result = run(
        ImmediateSignal(
            calendar_events_instance=calendar(),
            calendar_identifier="XNYS",
            signal_lifetime=HOUR,
        ),
        signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 0.5, "ILLQ": 0.3})]),
        price_rows,
    )

    assert steps(result) == [
        (utc("2026-11-18T16:00Z"), "ILLQ", "complete", 0.006, 0.3),
        (utc("2026-11-18T16:00:01Z"), "AAPL", "expired", 0.0, 0.0),
    ]


def test_a_newer_signal_too_old_to_trade_does_not_fall_back_to_the_previous_one() -> None:
    """The 20:00 target, valid for two hours, buys AAPL at 20:01; ILLQ waits.

    The 21:30 signal is after the close and is 17 hours old at Thursday's open: it never
    trades. The 20:00 target does not take its place: ILLQ's order expires at its
    next price, and the portfolio keeps the AAPL it bought.
    """
    signals = signal_frame(
        [
            ("2026-11-18T20:00:00Z", {"AAPL": 0.5, "ILLQ": 0.3}),
            ("2026-11-18T21:30:00Z", {"AAPL": 0.2, "ILLQ": 0.6}),
        ]
    )
    price_rows = prices(
        ("AAPL", "2026-11-18T19:59Z", 100.0),
        ("ILLQ", "2026-11-18T19:59Z", 50.0),
        ("AAPL", "2026-11-18T20:01Z", 100.0),
        ("AAPL", "2026-11-19T14:31Z", 100.0),
        ("ILLQ", "2026-11-19T14:45Z", 50.0),
    )

    def strategy(lifetime):
        return ImmediateSignal(
            calendar_events_instance=calendar(),
            calendar_identifier="XNYS",
            signal_lifetime=lifetime,
        )

    assert steps(run(strategy(2 * HOUR), signals, price_rows)) == [
        (utc("2026-11-18T20:01Z"), "AAPL", "complete", 0.005, 0.5),
        (utc("2026-11-19T14:45Z"), "ILLQ", "expired", 0.0, 0.0),
    ]
    # Without a lifetime the 21:30 target trades on Thursday.
    assert steps(run(strategy(None), signals, price_rows)) == [
        (utc("2026-11-18T20:01Z"), "AAPL", "complete", 0.005, 0.5),
        (utc("2026-11-19T14:31Z"), "AAPL", "complete", -0.003, 0.2),
        (utc("2026-11-19T14:45Z"), "ILLQ", "complete", 0.012, 0.6),
    ]


def test_a_resumed_run_expires_as_one_full_run_does() -> None:
    """The expiry at 18:01 falls in the third of three runs."""
    signals = PublishedTable.build(
        "signals", SWAP, index=["time_index", "signal_uid", ASSET_IDENTIFIER]
    )
    published = PublishedTable.build("prices", HALTED_SELL, index=["time_index", ASSET_IDENTIFIER])
    lifetime = dt.timedelta(minutes=90)
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=negative_cash(signal_lifetime=lifetime),
            signals=signals,
            prices=published,
            storage=storage,
        )
        first = runner.run("2026-11-18T16:30:00Z")
        second = runner.run("2026-11-18T17:30:00Z")
        third = runner.run("2026-11-18T18:30:00Z")
        fourth = runner.run("2026-11-18T19:30:00Z")
        whole = runner.persisted.reset_index()

    in_one_run = run(negative_cash(signal_lifetime=lifetime), SWAP, HALTED_SELL)
    assert len(first) == 2 and second.empty and len(third) == 2 and fourth.empty
    assert set(third["execution_status"]) == {"expired"}
    assert rounded(whole) == rounded(in_one_run)
    assert [json.loads(state) for state in whole["strategy_state"]] == [
        json.loads(state) for state in in_one_run["strategy_state"]
    ]


# --- Strategies with their own bars ------------------------------------------------------


def bar_frame(stamps: list[str], asset: str = "AAPL") -> pd.DataFrame:
    """Bars of ``asset`` with price 100 and volume 100."""
    return pd.DataFrame(
        [(utc(stamp), asset, 100.0, 100.0) for stamp in stamps],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])


BARS = bar_frame(
    [
        "2026-11-18T10:30Z",
        "2026-11-18T11:00Z",
        "2026-11-18T11:30Z",
        "2026-11-18T12:00Z",
        "2026-11-18T12:30Z",
    ]
)


def bar_strategy(strategy_class, bars: pd.DataFrame, **fields):
    source = PublishedTable.build("bars", bars, index=["time_index", ASSET_IDENTIFIER])
    if strategy_class is VolumeParticipation:
        # Each bar's capacity is 100 x 100 x 10% / 100,000: 1% of the portfolio.
        fields = {"max_percent_volume_in_bar": 0.1, "total_notional": 100_000.0, **fields}
    return strategy_class(execution_bars_instance=source, **fields)


def run_bars(
    strategy,
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    start: str = "2026-11-18T00:00Z",
    end: str = "2026-11-18T23:00Z",
    previous_state: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return strategy.build_transitions(
        start=utc(start),
        end=utc(end),
        signal_observations=signals,
        observed_inputs={"execution_bars": bars},
        previous_state=previous_state,
    )


def bar_rows(result: pd.DataFrame) -> list[tuple]:
    """``(time, asset, status, weight_before, weight_after, traded)`` of every row."""
    if result.empty:
        return []
    ordered = result.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
    return [
        (
            utc(row["time_index"]),
            row[ASSET_IDENTIFIER],
            row["execution_status"],
            pytest.approx(row["weight_before"], abs=1e-12),
            pytest.approx(row["weight_after"], abs=1e-12),
            not pd.isna(row["execution_price"]),
        )
        for row in ordered.to_dict(orient="records")
    ]


TEN = signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.05})])


@pytest.mark.parametrize(
    ("strategy_class", "expected"),
    [
        (
            VolumeParticipation,
            [
                (utc("2026-11-18T10:30Z"), "AAPL", "partial", 0.0, 0.01, True),
                # Exactly one hour old: still valid.
                (utc("2026-11-18T11:00Z"), "AAPL", "partial", 0.01, 0.02, True),
                (utc("2026-11-18T11:30Z"), "AAPL", "expired", 0.02, 0.02, False),
            ],
        ),
        (
            # Starts its clock at 10:30 and moves 1,800 / 45,000 of the way by 11:00.
            TimeWeighted,
            [
                (utc("2026-11-18T10:30Z"), "AAPL", "pending", 0.0, 0.0, False),
                (utc("2026-11-18T11:00Z"), "AAPL", "partial", 0.0, 0.002, True),
                (utc("2026-11-18T11:30Z"), "AAPL", "expired", 0.002, 0.002, False),
            ],
        ),
    ],
)
def test_an_order_filling_over_several_bars_stops_when_its_signal_expires(
    strategy_class, expected
) -> None:
    result = run_bars(bar_strategy(strategy_class, BARS, signal_lifetime=HOUR), BARS, TEN)

    assert bar_rows(result) == expected
    expired = result[result["execution_status"] == "expired"].iloc[0]
    assert expired["executed_weight_delta"] == 0.0
    assert expired["remaining_weight_delta"] == pytest.approx(0.05 - expected[-1][4])
    # Without a lifetime the order keeps filling after 11:30.
    unlimited = run_bars(bar_strategy(strategy_class, BARS), BARS, TEN)
    assert unlimited["time_index"].max() == utc("2026-11-18T12:30Z")
    assert "expired" not in set(unlimited["execution_status"])


def test_a_bar_strategy_signal_too_old_at_its_first_bar_never_trades() -> None:
    late = bar_frame(["2026-11-18T11:30Z", "2026-11-18T12:00Z"])
    strategy = bar_strategy(VolumeParticipation, late, signal_lifetime=HOUR)

    assert run_bars(strategy, late, TEN).empty


def test_a_bar_strategy_does_not_fall_back_to_the_previous_signal() -> None:
    """The 10:00 target fills 1% at 10:30 and 11:00; the 11:10 target's first bar is 14:00.

    At 14:00 the 11:10 signal is older than two hours: nothing trades, and the 10:00
    target, older still, does not resume. It ends expired, keeping its 2%.
    """
    bars = bar_frame(["2026-11-18T10:30Z", "2026-11-18T11:00Z", "2026-11-18T14:00Z"])
    signals = signal_frame(
        [("2026-11-18T10:00:00Z", {"AAPL": 0.05}), ("2026-11-18T11:10:00Z", {"AAPL": 0.03})]
    )

    expired = run_bars(
        bar_strategy(VolumeParticipation, bars, signal_lifetime=2 * HOUR), bars, signals
    )
    assert bar_rows(expired) == [
        (utc("2026-11-18T10:30Z"), "AAPL", "partial", 0.0, 0.01, True),
        (utc("2026-11-18T11:00Z"), "AAPL", "partial", 0.01, 0.02, True),
        (utc("2026-11-18T14:00Z"), "AAPL", "expired", 0.02, 0.02, False),
    ]
    assert expired.iloc[-1]["target_signal_time_index"] == utc("2026-11-18T10:00:00Z")
    # Without a lifetime the 11:10 target replaces the 10:00 one at 14:00.
    replaced = run_bars(bar_strategy(VolumeParticipation, bars), bars, signals)
    assert bar_rows(replaced)[2:] == [
        (utc("2026-11-18T14:00Z"), "AAPL", "superseded", 0.02, 0.02, False),
        (utc("2026-11-18T14:00Z"), "AAPL", "complete", 0.02, 0.03, True),
    ]


def test_a_resumed_bar_strategy_expires_as_one_full_run_does() -> None:
    strategy = bar_strategy(VolumeParticipation, BARS, signal_lifetime=HOUR)
    full = run_bars(strategy, BARS, TEN)
    first = run_bars(strategy, BARS, TEN, end="2026-11-18T11:15Z")
    second = run_bars(
        strategy,
        BARS,
        TEN,
        start="2026-11-18T11:00:00.000000001Z",
        previous_state=first,
    )
    third = run_bars(
        strategy,
        BARS,
        TEN,
        start="2026-11-18T11:30:00.000000001Z",
        previous_state=pd.concat([first, second], ignore_index=True),
    )

    assert bar_rows(pd.concat([first, second], ignore_index=True)) == bar_rows(full)
    assert set(second["execution_status"]) == {"expired"}
    assert third.empty


# --- The position ledger -----------------------------------------------------------------


def test_the_ledger_books_what_filled_and_records_the_expiry() -> None:
    """NAV $10,000. The 15:00 target, valid for an hour, buys 50 AAPL at 15:01.

    ILLQ's next price is at 16:30: its order expires there, and the ledger books no
    ILLQ shares; it records the expiry as progress.
    """
    price_rows = prices(
        ("AAPL", "2026-11-18T14:45Z", 100.0),
        ("ILLQ", "2026-11-18T14:45Z", 50.0),
        ("AAPL", "2026-11-18T15:01Z", 100.0),
        ("ILLQ", "2026-11-18T16:30Z", 50.0),
        ("ILLQ", "2026-11-18T16:45Z", 50.0),
    )
    signals = signal_frame([("2026-11-18T15:00:00Z", {"AAPL": 0.5, "ILLQ": 0.3})])

    def ledger(lifetime):
        strategy = stock_strategy(calendar(), assets=("AAPL", "ILLQ"), signal_lifetime=lifetime)
        state = run(strategy, signals, price_rows)
        return state, book(strategy, state, marks(price_rows), initial_state="2026-11-18T00:00:00Z")

    state, booked = ledger(HOUR)

    assert steps(state) == [
        (utc("2026-11-18T15:01Z"), "AAPL", "complete", 0.005, 0.5),
        (utc("2026-11-18T16:30Z"), "ILLQ", "expired", 0.0, 0.0),
    ]
    assert position_deltas(booked) == [(utc("2026-11-18T15:01Z"), "AAPL", 50.0, 100.0)]
    [illiquid] = progress(booked, "ILLQ")
    assert illiquid["execution_status"] == "expired"
    assert illiquid["weight_after"] == 0.0
    assert illiquid["remaining_weight_delta"] == pytest.approx(0.3)
    assert illiquid["strategy_state"]["cancel_reason"] == "signal_lifetime"
    [apple] = progress(booked, "AAPL")
    assert apple["execution_status"] == "complete"

    # Without a lifetime ILLQ buys its 60 shares at 16:30.
    _state, unlimited = ledger(None)
    assert position_deltas(unlimited) == [
        (utc("2026-11-18T15:01Z"), "AAPL", 50.0, 100.0),
        (utc("2026-11-18T16:30Z"), "ILLQ", 60.0, 50.0),
    ]
