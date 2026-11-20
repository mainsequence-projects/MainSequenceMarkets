"""A trade happens only at a price observed at the trade's time (issue #89, ADR 0058).

The earliest moment comes from the portfolio's calendar: the strategy's moment while
the calendar is in session, otherwise the next session start. Each asset then trades
at the first row of the portfolio's valuation source at or after that moment and
strictly after the signal that set its target. Interpolated rows never count,
assets fill independently, and a missing price makes the trade wait.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from msm_portfolios.accounting import MarketPriceValuationModel, PortfolioAccountingConfiguration
from msm_portfolios.accounting.contracts import AccountingStateView
from msm_portfolios.rebalance_strategy import (
    AccountingExecutionContext,
    AssetExecution,
    CalendarEventSignal,
    ImmediateSignal,
    TimeWeighted,
    VolumeParticipation,
    observed_prices,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.accounting import (
    PortfolioEngine,
    PortfolioEngineConfiguration,
    _new_ledger_tail,
    _validate_replay_against_existing,
)
from msm_portfolios.time_index.portfolios.calendar_events import (
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
)
from msm_portfolios.time_index.portfolios.rebalance import (
    PortfolioRebalance,
)
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
)
from tests.support.pinned_identities import _bound
from tests.support.rebalance import (
    NYSE,
    IncrementalRebalance,
    PublishedCalendarEvents,
    PublishedTable,
    book,
    calendar,
    marks,
    nyse_sessions,
    run_strategy,
    signal_frame,
    stock_strategy,
    utc,
)


# --- Calendars and prices ---------------------------------------------------------------


def london_sessions(first: str, last: str) -> list[tuple[dt.date, pd.Timestamp, pd.Timestamp]]:
    """London trading hours in UTC (winter): 08:00 to 16:30 on weekdays."""
    return [
        (day.date(), utc(f"{day.date()}T08:00:00Z"), utc(f"{day.date()}T16:30:00Z"))
        for day in pd.date_range(first, last, freq="D")
        if day.weekday() < 5
    ]


def crypto_sessions(first: str, last: str) -> list[tuple[dt.date, pd.Timestamp, pd.Timestamp]]:
    """24/7 sessions: each closes at the instant the next one opens."""
    sessions = []
    for day in pd.date_range(first, last, freq="D"):
        opens_at = utc(f"{day.date()}T00:00:00Z")
        sessions.append((day.date(), opens_at, opens_at + pd.Timedelta(days=1)))
    return sessions


def minute_bars(asset: str, sessions, *, price: float = 100.0) -> pd.DataFrame:
    """1-minute bars stamped at their end, from one minute after each open to the close."""
    rows = []
    for _local, opens_at, closes_at in sessions:
        for stamp in pd.date_range(opens_at + pd.Timedelta(minutes=1), closes_at, freq="min"):
            rows.append((stamp, asset, price))
    return pd.DataFrame(rows, columns=["time_index", ASSET_IDENTIFIER, "close"])


def daily_closes(asset: str, sessions, *, price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        [(closes_at, asset, price) for _local, _opens_at, closes_at in sessions],
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    )


def bars_at(asset: str, stamps: list[str], *, price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        [(utc(stamp), asset, price) for stamp in stamps],
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    )


AAPL_MINUTES = minute_bars("AAPL", nyse_sessions("2026-11-17", "2026-11-30"))
AAPL_DAILY = daily_closes("AAPL", nyse_sessions("2026-11-17", "2026-11-30"))
LON_MINUTES = minute_bars("LON", london_sessions("2026-11-17", "2026-11-24"))
LON_DAILY = daily_closes("LON", london_sessions("2026-11-17", "2026-11-24"))


def fills(result: pd.DataFrame) -> list[tuple[pd.Timestamp, str, float, pd.Timestamp]]:
    """Return ``(time, asset, weight_after, target signal)`` of every trade, in order."""
    if result.empty:
        return []
    traded = result[result["executed_weight_delta"].abs() > 0.0]
    return [
        (utc(row["time_index"]), row[ASSET_IDENTIFIER], row["weight_after"],
         utc(row["target_signal_time_index"]))
        for row in traded.sort_values(["time_index", ASSET_IDENTIFIER]).to_dict(orient="records")
    ]


# --- The examples tables of issue #89 ---------------------------------------------------


IMMEDIATE_EXAMPLES = [
    # signal, asset, portfolio calendar, 1-minute fill, daily-close fill
    ("2026-11-18T16:07:23Z", "AAPL", "XNYS", "2026-11-18T16:08Z", "2026-11-18T21:00Z"),
    ("2026-11-18T16:08:00Z", "AAPL", "XNYS", "2026-11-18T16:09Z", "2026-11-18T21:00Z"),
    ("2026-11-18T21:30:00Z", "AAPL", "XNYS", "2026-11-19T14:31Z", "2026-11-19T21:00Z"),
    ("2026-11-21T10:00:00Z", "AAPL", "XNYS", "2026-11-23T14:31Z", "2026-11-23T21:00Z"),
    ("2026-11-26T15:00:00Z", "AAPL", "XNYS", "2026-11-27T14:31Z", "2026-11-27T18:00Z"),
    # London's bar for 14:29-14:30 is stamped at the NYSE open: not inside the session.
    ("2026-11-21T10:00:00Z", "LON", "XNYS", "2026-11-23T14:31Z", "2026-11-23T16:30Z"),
    ("2026-11-21T10:00:00Z", "LON", "CRYPTO_24_7", "2026-11-23T08:01Z", "2026-11-23T16:30Z"),
]


@pytest.mark.parametrize(
    ("signal_time", "asset", "calendar_identifier", "minute_fill", "daily_fill"),
    IMMEDIATE_EXAMPLES,
    ids=[
        "in session",
        "signal stamped on a bar's timestamp",
        "after the close",
        "weekend",
        "thanksgiving, half day after",
        "london asset, nyse calendar",
        "london asset, 24/7 calendar",
    ],
)
def test_immediate_signal_trades_at_the_next_observed_price(
    signal_time, asset, calendar_identifier, minute_fill, daily_fill
) -> None:
    sessions = (
        NYSE if calendar_identifier == "XNYS" else crypto_sessions("2026-11-09", "2026-11-30")
    )
    strategy = ImmediateSignal(
        calendar_events_instance=calendar(calendar_identifier, sessions),
        calendar_identifier=calendar_identifier,
    )
    signals = signal_frame([(signal_time, {asset: 0.5})])
    sources = {
        "AAPL": (AAPL_MINUTES, AAPL_DAILY),
        "LON": (LON_MINUTES, LON_DAILY),
    }[asset]

    for prices, expected in zip(sources, (minute_fill, daily_fill), strict=True):
        result = run_strategy(
            strategy,
            signals=signals,
            prices=prices,
            start="2026-11-17T00:00:00Z",
            end="2026-11-30T23:00:00Z",
        )
        assert fills(result) == [(utc(expected), asset, 0.5, utc(signal_time))]
        filled = result[result["executed_weight_delta"] != 0].iloc[0]
        assert filled["execution_price"] == pytest.approx(100.0)
        assert json.loads(filled["strategy_state"])["earliest_time_index"]


@pytest.mark.parametrize(
    ("rebalance_event", "minute_fill", "daily_fill"),
    [
        ("market_close", "2026-11-18T21:00Z", "2026-11-18T21:00Z"),
        ("market_open", "2026-11-18T14:31Z", "2026-11-18T21:00Z"),
    ],
)
def test_calendar_event_signal_trades_at_the_next_observed_price(
    rebalance_event, minute_fill, daily_fill
) -> None:
    strategy = CalendarEventSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        rebalance_event=rebalance_event,
    )
    signals = signal_frame([("2026-11-17T22:00:00Z", {"AAPL": 0.5})])

    for prices, expected in ((AAPL_MINUTES, minute_fill), (AAPL_DAILY, daily_fill)):
        result = run_strategy(
            strategy,
            signals=signals,
            prices=prices,
            start="2026-11-17T00:00:00Z",
            end="2026-11-30T23:00:00Z",
        )
        assert fills(result) == [(utc(expected), "AAPL", 0.5, utc("2026-11-17T22:00:00Z"))]


# --- Observed prices only, independent fills, waiting ------------------------------------


def test_interpolated_rows_are_never_a_trade_price() -> None:
    prices = pd.concat(
        [
            bars_at("AAPL", ["2026-11-18T21:00Z"]).assign(interpolated=False),
            bars_at("AAPL", ["2026-11-19T21:00Z"], price=999.0).assign(interpolated=True),
            bars_at("AAPL", ["2026-11-20T21:00Z"], price=101.0).assign(interpolated=False),
        ]
    )
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame([("2026-11-18T21:30:00Z", {"AAPL": 0.5})]),
        prices=prices,
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    # Sized at the decision with Wednesday's 100: 0.005 shares, worth 0.505 at 101.
    assert fills(result) == [
        (utc("2026-11-20T21:00Z"), "AAPL", pytest.approx(0.505), utc("2026-11-18T21:30:00Z"))
    ]
    assert result[result["executed_weight_delta"] != 0]["execution_price"].tolist() == [101.0]


def test_assets_fill_independently_and_the_unfilled_part_is_cash() -> None:
    prices = pd.concat(
        [
            AAPL_MINUTES,
            bars_at(
                "ILLQ", ["2026-11-18T20:00Z", "2026-11-19T14:45Z", "2026-11-19T15:30Z"], price=20.0
            ),
        ]
    )
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame([("2026-11-18T21:30:00Z", {"AAPL": 0.6, "ILLQ": 0.3})]),
        prices=prices,
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    assert fills(result) == [
        (utc("2026-11-19T14:31Z"), "AAPL", 0.6, utc("2026-11-18T21:30:00Z")),
        (utc("2026-11-19T14:45Z"), "ILLQ", 0.3, utc("2026-11-18T21:30:00Z")),
    ]
    # Only the asset that fills gets a row; ILLQ keeps its weight, 0, until 14:45.
    assert result.groupby("time_index")[ASSET_IDENTIFIER].apply(list).to_dict() == {
        utc("2026-11-19T14:31Z"): ["AAPL"],
        utc("2026-11-19T14:45Z"): ["ILLQ"],
    }
    assert 1.0 - weights_as_of(result, "2026-11-19T14:40Z").sum() == pytest.approx(0.4)


def weights_as_of(result: pd.DataFrame, time_index: str) -> pd.Series:
    """Executed weights at a time: each asset's latest row at or before it."""
    upto = result[result["time_index"] <= utc(time_index)].sort_values("time_index")
    return upto.groupby(ASSET_IDENTIFIER)["weight_after"].last()


def test_a_halted_asset_fills_at_its_first_observed_price_after_the_halt() -> None:
    friday = nyse_sessions("2026-11-20", "2026-11-20")
    halted = minute_bars("HALT", [(friday[0][0], utc("2026-11-20T15:00Z"), friday[0][2])])
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame([("2026-11-18T21:30:00Z", {"AAPL": 0.5, "HALT": 0.5})]),
        prices=pd.concat([AAPL_MINUTES, bars_at("HALT", ["2026-11-18T20:00Z"]), halted]),
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    assert [(time, asset) for time, asset, _weight, _signal in fills(result)] == [
        (utc("2026-11-19T14:31Z"), "AAPL"),
        (utc("2026-11-20T15:01Z"), "HALT"),
    ]


def test_a_newer_signal_replaces_the_target_of_assets_not_filled_yet() -> None:
    prices = pd.concat(
        [AAPL_MINUTES, bars_at("ILLQ", ["2026-11-18T20:00Z", "2026-11-19T14:45Z"], price=20.0)]
    )
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame(
            [
                ("2026-11-18T21:30:00Z", {"AAPL": 0.6, "ILLQ": 0.3}),
                ("2026-11-19T14:40:00Z", {"AAPL": 0.2, "ILLQ": 0.7}),
            ]
        ),
        prices=prices,
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    assert fills(result) == [
        (utc("2026-11-19T14:31Z"), "AAPL", 0.6, utc("2026-11-18T21:30:00Z")),
        (utc("2026-11-19T14:41Z"), "AAPL", 0.2, utc("2026-11-19T14:40:00Z")),
        (utc("2026-11-19T14:45Z"), "ILLQ", 0.7, utc("2026-11-19T14:40:00Z")),
    ]
    assert set(result["execution_status"]) == {"complete"}


def test_only_a_real_row_inside_a_session_is_a_trade_price() -> None:
    """``market_open < time_index <= market_close``: a bar is stamped at its end."""
    prices = pd.concat(
        [
            bars_at("AAPL", ["2026-11-18T19:00Z"], price=100.0),  # before the signal
            bars_at("AAPL", ["2026-11-18T21:30Z"], price=998.0),  # after the close
            bars_at("AAPL", ["2026-11-19T14:30Z"], price=999.0),  # stamped at the open
            bars_at("AAPL", ["2026-11-19T14:31Z"], price=100.0),
        ]
    )
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame([("2026-11-18T20:00:00Z", {"AAPL": 0.5})]),
        prices=prices,
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    assert fills(result) == [
        (utc("2026-11-19T14:31Z"), "AAPL", 0.5, utc("2026-11-18T20:00:00Z"))
    ]
    assert result["execution_price"].tolist() == [100.0]


@pytest.mark.parametrize("column", ["open", "high", "low", "vwap", "VWAP"])
def test_a_fill_price_must_be_observed_at_its_rows_time(column) -> None:
    frame = bars_at("AAPL", ["2026-11-19T14:31Z"]).rename(columns={"close": column})
    with pytest.raises(ValueError, match="cannot be a fill price"):
        observed_prices(frame, price_column=column)
    strategy = TimeWeighted(
        execution_bars_instance=PublishedTable.build(
            "bars", frame, index=["time_index", ASSET_IDENTIFIER]
        ),
        price_column=column,
    )
    with pytest.raises(ValueError, match="cannot be a fill price"):
        strategy.build_transitions(
            start=utc("2026-11-18T00:00Z"),
            end=utc("2026-11-19T23:00Z"),
            signal_observations=signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5})]),
            observed_inputs={"execution_bars": frame.set_index(["time_index", ASSET_IDENTIFIER])},
            previous_state=None,
        )


def bar_frame(rows: list[tuple[str, str, bool]]) -> pd.DataFrame:
    """Bars with price 100 and volume 100; each row is (time, asset, interpolated)."""
    return pd.DataFrame(
        [(utc(stamp), asset, 100.0, 100.0, interpolated) for stamp, asset, interpolated in rows],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume", "interpolated"],
    ).set_index(["time_index", ASSET_IDENTIFIER])


def run_bar_strategy(strategy, bars: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    return strategy.build_transitions(
        start=utc("2026-11-18T00:00Z"),
        end=utc("2026-11-18T23:00Z"),
        signal_observations=signals,
        observed_inputs={"execution_bars": bars},
        previous_state=None,
    )


def moved(result: pd.DataFrame) -> set[tuple[pd.Timestamp, str]]:
    return {
        (utc(row["time_index"]), row[ASSET_IDENTIFIER])
        for row in result[result["executed_weight_delta"] != 0].to_dict(orient="records")
    }


def test_a_bar_strategy_skips_the_signals_own_bar_and_interpolated_bars() -> None:
    bars = bar_frame(
        [
            ("2026-11-18T10:00Z", "AAPL", False),
            ("2026-11-18T10:00Z", "MSFT", False),
            ("2026-11-18T10:30Z", "AAPL", False),
            ("2026-11-18T10:30Z", "MSFT", True),
            ("2026-11-18T11:00Z", "MSFT", False),
        ]
    )
    strategy = VolumeParticipation(
        execution_bars_instance=PublishedTable.build(
            "bars", bars, index=["time_index", ASSET_IDENTIFIER]
        ),
        max_percent_volume_in_bar=1.0,
        total_notional=100_000.0,
    )
    result = run_bar_strategy(
        strategy,
        bars,
        signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5, "MSFT": 0.5})]),
    )

    # The 10:00 bars carry the signal's own time; MSFT's 10:30 row is interpolated.
    assert moved(result) == {
        (utc("2026-11-18T10:30Z"), "AAPL"),
        (utc("2026-11-18T11:00Z"), "MSFT"),
    }


def test_a_bar_strategy_moves_an_asset_only_at_its_own_observed_bar() -> None:
    bars = bar_frame(
        [
            ("2026-11-18T10:30Z", "AAPL", False),
            ("2026-11-18T10:30Z", "MSFT", False),
            ("2026-11-18T11:00Z", "AAPL", False),
            ("2026-11-18T11:30Z", "AAPL", False),
            ("2026-11-18T11:30Z", "MSFT", False),
        ]
    )
    strategy = TimeWeighted(
        execution_bars_instance=PublishedTable.build(
            "bars", bars, index=["time_index", ASSET_IDENTIFIER]
        )
    )
    result = run_bar_strategy(
        strategy,
        bars,
        signal_frame([("2026-11-18T10:00:00Z", {"AAPL": 0.5, "MSFT": 0.5})]),
    )

    # TimeWeighted starts its clock at 10:30. At 11:00 only AAPL has a bar.
    assert moved(result) == {
        (utc("2026-11-18T11:00Z"), "AAPL"),
        (utc("2026-11-18T11:30Z"), "AAPL"),
        (utc("2026-11-18T11:30Z"), "MSFT"),
    }
    at_eleven = result[result["time_index"] == utc("2026-11-18T11:00Z")].set_index(
        ASSET_IDENTIFIER
    )
    assert at_eleven.loc["AAPL", "execution_price"] == 100.0
    assert pd.isna(at_eleven.loc["MSFT", "execution_price"])


# --- The calendar ------------------------------------------------------------------------


def test_the_calendar_is_a_required_dependency_that_publishes_opens_and_closes() -> None:
    events = calendar()
    with pytest.raises(ValidationError, match="calendar_events_instance"):
        ImmediateSignal(calendar_identifier="XNYS")
    with pytest.raises(ValidationError, match="calendar_identifier"):
        ImmediateSignal(calendar_events_instance=events)

    close_only = object.__new__(PortfolioCalendarEvents)
    close_only.config = PortfolioCalendarEventsConfiguration(
        calendar_identifier="XNYS",
        event_types=("market_close",),
    )
    for strategy_class in (ImmediateSignal, CalendarEventSignal):
        with pytest.raises(ValidationError, match="publishes both market_open and market_close"):
            strategy_class(calendar_events_instance=close_only, calendar_identifier="XNYS")

    one_type = PublishedCalendarEvents.build(
        calendar_identifier="XNYS",
        sessions=NYSE,
        published_until="2026-11-30T23:00:00Z",
        event_types=("market_close",),
    )
    with pytest.raises(ValueError, match="two market_close events in a row"):
        run_strategy(
            ImmediateSignal(calendar_events_instance=one_type, calendar_identifier="XNYS"),
            signals=signal_frame([("2026-11-18T16:07:00Z", {"AAPL": 0.5})]),
            prices=AAPL_MINUTES,
            start="2026-11-17T00:00:00Z",
            end="2026-11-30T23:00:00Z",
        )
    with pytest.raises(ValueError, match="no published market_open or market_close"):
        run_strategy(
            ImmediateSignal(calendar_events_instance=events, calendar_identifier="XLON"),
            signals=signal_frame([("2026-11-18T16:07:00Z", {"AAPL": 0.5})]),
            prices=AAPL_MINUTES,
            start="2026-11-17T00:00:00Z",
            end="2026-11-30T23:00:00Z",
        )


def test_every_strategy_states_the_fill_rule_in_its_identity() -> None:
    strategy = ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS")

    assert strategy.model_dump(exclude={"calendar_events_instance"}) == {
        "timing_mode": "signal_time",
        "fill_rule": "next_observed_price",
        "completion_tolerance": 1e-12,
        "target_succession": "supersede_active",
        "calendar_identifier": "XNYS",
        "session_label": "regular",
        "signal_selection": "latest_at_or_before_event",
        "execution_policy": {
            "sizing": "at_decision",
            "negative_cash": "not_allowed",
            "negative_cash_limit": 0.0,
            "sells_before_buys": True,
            "cash_shortfall_allocation": "pro_rata",
            "uncovered_buys": "cut_and_cancel",
            "calendar_gating": "portfolio_calendar",
        },
    }
    assert "fill_rule" in TimeWeighted.model_fields


# --- Incremental runs of PortfolioRebalance ----------------------------------------------


def written_fills(frame: pd.DataFrame) -> set[tuple[pd.Timestamp, str]]:
    flat = frame.reset_index()
    traded = flat[flat["executed_weight_delta"] != 0]
    return {(utc(row["time_index"]), row[ASSET_IDENTIFIER]) for row in traded.to_dict("records")}


def test_incremental_runs_wait_for_the_next_price_and_fill_assets_across_runs() -> None:
    signals = PublishedTable.build(
        "signals",
        signal_frame(
            [
                ("2026-11-18T21:30:00Z", {"AAPL": 0.6, "ILLQ": 0.3}),
                ("2026-11-19T15:00:30Z", {"AAPL": 0.5, "ILLQ": 0.3}),
            ]
        ),
        index=["time_index", "signal_uid", ASSET_IDENTIFIER],
    )
    prices = PublishedTable.build(
        "prices",
        pd.concat(
            [AAPL_MINUTES, bars_at("ILLQ", ["2026-11-18T20:00Z", "2026-11-19T14:45Z"], price=20.0)]
        ),
        index=["time_index", ASSET_IDENTIFIER],
    )
    strategy = ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
    )
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=strategy, signals=signals, prices=prices, storage=storage
        )
        after_close = runner.run("2026-11-18T21:35:00Z")
        before_open = runner.run("2026-11-19T10:00:00Z")
        open_without_a_price = runner.run("2026-11-19T14:30:30Z")
        first_price = runner.run("2026-11-19T14:35:00Z")
        illiquid_price = runner.run("2026-11-19T14:50:00Z")
        next_signal = runner.run("2026-11-19T15:05:00Z")
        rerun = runner.run("2026-11-19T15:06:00Z")

    assert after_close.empty
    assert before_open.empty
    assert open_without_a_price.empty
    # Only AAPL fills; ILLQ waits for its price and gets no row.
    assert set(first_price.index.get_level_values(ASSET_IDENTIFIER)) == {"AAPL"}
    assert written_fills(first_price) == {(utc("2026-11-19T14:31Z"), "AAPL")}
    # ILLQ's target comes from the signal that set it, which is before this window.
    assert written_fills(illiquid_price) == {(utc("2026-11-19T14:45Z"), "ILLQ")}
    # The window starts after the 14:45 fill, past the 14:30 open: the open is read
    # as the event in force, so the 15:00:30 signal is in session. AAPL's weight
    # comes from its 14:31 row, which is not at the latest time.
    assert written_fills(next_signal) == {(utc("2026-11-19T15:01Z"), "AAPL")}
    moved = next_signal.reset_index().set_index(ASSET_IDENTIFIER)
    assert moved.loc["AAPL", "weight_before"] == pytest.approx(0.6)
    assert moved.loc["AAPL", "weight_after"] == pytest.approx(0.5)
    assert rerun.empty


def test_a_waiting_asset_looks_for_its_price_from_its_own_earliest_moment() -> None:
    """ILLQ's 14:30:30 bar is published after AAPL's 14:31 fill was recorded.

    The next window starts after 14:31; ILLQ still fills at 14:30:30, its next
    observed price from its target's earliest moment, the 14:30 open.
    """
    signals = PublishedTable.build(
        "signals",
        signal_frame([("2026-11-18T21:30:00Z", {"AAPL": 0.6, "ILLQ": 0.3})]),
        index=["time_index", "signal_uid", ASSET_IDENTIFIER],
    )
    slow_bar = bars_at("ILLQ", ["2026-11-19T14:30:30Z"], price=20.0).assign(
        published_at=utc("2026-11-19T14:38:00Z")
    )
    wednesday = bars_at("ILLQ", ["2026-11-18T20:00Z"], price=20.0)
    prices = PublishedTable.build(
        "prices",
        pd.concat(
            [
                AAPL_MINUTES.assign(published_at=AAPL_MINUTES["time_index"]),
                wednesday.assign(published_at=wednesday["time_index"]),
                slow_bar,
            ]
        ),
        index=["time_index", ASSET_IDENTIFIER],
    )
    strategy = ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS")
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=strategy, signals=signals, prices=prices, storage=storage
        )
        before_the_slow_bar = runner.run("2026-11-19T14:35:00Z")
        after_the_slow_bar = runner.run("2026-11-19T14:40:00Z")

    assert written_fills(before_the_slow_bar) == {(utc("2026-11-19T14:31Z"), "AAPL")}
    assert written_fills(after_the_slow_bar) == {(utc("2026-11-19T14:30:30Z"), "ILLQ")}


def test_a_signal_stamped_at_the_last_fill_time_trades_on_a_later_run() -> None:
    """The 16:08:00 signal cannot fill at the 16:08 bar, which fills the older target.

    The next window starts 1 ns after that fill; the signal is still selected.
    """
    signals = PublishedTable.build(
        "signals",
        signal_frame(
            [
                ("2026-11-18T16:07:23Z", {"AAPL": 0.5}),
                ("2026-11-18T16:08:00Z", {"AAPL": 0.3}),
            ]
        ),
        index=["time_index", "signal_uid", ASSET_IDENTIFIER],
    )
    prices = PublishedTable.build(
        "prices", AAPL_MINUTES, index=["time_index", ASSET_IDENTIFIER]
    )
    strategy = ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS")
    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        runner = IncrementalRebalance(
            strategy=strategy, signals=signals, prices=prices, storage=storage
        )
        first = runner.run("2026-11-18T16:08:30Z")
        second = runner.run("2026-11-18T16:09:30Z")

    assert written_fills(first) == {(utc("2026-11-18T16:08Z"), "AAPL")}
    assert written_fills(second) == {(utc("2026-11-18T16:09Z"), "AAPL")}
    filled = second.reset_index().set_index(ASSET_IDENTIFIER)
    assert filled.loc["AAPL", "weight_after"] == pytest.approx(0.3)
    assert utc(filled.loc["AAPL", "target_signal_time_index"]) == utc("2026-11-18T16:08:00Z")


def test_a_new_target_that_repeats_a_weight_still_fills_at_the_next_price() -> None:
    """The ledger resizes the position at that fill; the weight does not change."""
    result = run_strategy(
        ImmediateSignal(calendar_events_instance=calendar(), calendar_identifier="XNYS"),
        signals=signal_frame(
            [
                ("2026-11-18T16:07:23Z", {"AAPL": 0.5}),
                ("2026-11-18T17:00:30Z", {"AAPL": 0.5}),
            ]
        ),
        prices=AAPL_MINUTES,
        start="2026-11-17T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    priced = result[result["execution_price"].notna()]
    assert [utc(value) for value in priced["time_index"]] == [
        utc("2026-11-18T16:08Z"),
        utc("2026-11-18T17:01Z"),
    ]
    assert priced["executed_weight_delta"].tolist() == pytest.approx([0.5, 0.0])


def test_portfolio_rebalance_depends_on_the_valuation_source_it_trades_at() -> None:
    signal = PublishedTable.build("signal", signal_frame([]), index=["time_index"])
    prices = PublishedTable.build("prices", AAPL_DAILY, index=["time_index", ASSET_IDENTIFIER])
    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = object()
    node.signal_weights = signal
    node.valuation_source = prices
    node.fx_source = None
    events = calendar()
    node.rebalance_strategy = ImmediateSignal(
        calendar_events_instance=events, calendar_identifier="XNYS"
    )
    assert node.dependencies() == {
        "valuation_source": prices,
        "calendar_events": events,
    }

    node.rebalance_strategy = TimeWeighted(execution_bars_instance=prices)
    assert node.dependencies() == {"execution_bars": prices}


# --- The ledger books the recorded fills ---------------------------------------------------


def executions(ledger: pd.DataFrame) -> list[tuple[pd.Timestamp, str, float, float]]:
    deltas = ledger[ledger["record_kind"] == "position_delta"]
    return [
        (utc(row["time_index"]), row["asset_identifier"], row["quantity_delta"], row["price"])
        for row in deltas.sort_values(["time_index", "asset_identifier"]).to_dict("records")
    ]


def ledger_for(
    strategy,
    *,
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    start: str,
    end: str,
    staleness: dt.timedelta = dt.timedelta(days=1),
) -> pd.DataFrame:
    """Record the fills from ``prices``, then book them with the same prices as marks."""
    state = run_strategy(strategy, signals=signals, prices=prices, start=start, end=end)
    return book(strategy, state, marks(prices), initial_state=start, valuation_staleness=staleness)


@pytest.mark.parametrize(
    ("case", "signal", "decision_bar", "fill_bar", "strategy_fields"),
    [
        (
            "in session: the 16:07:00 bar",
            "2026-11-18T16:07:23Z",
            "2026-11-18T16:07Z",
            "2026-11-18T16:08Z",
            {},
        ),
        (
            "saturday: friday's close",
            "2026-11-21T10:00:00Z",
            "2026-11-20T21:00Z",
            "2026-11-23T14:31Z",
            {},
        ),
        (
            "at the close: the bar before 21:00, never the 21:00 close it fills at",
            "2026-11-17T22:00:00Z",
            "2026-11-18T20:59Z",
            "2026-11-18T21:00Z",
            {"strategy_class": CalendarEventSignal, "rebalance_event": "market_close"},
        ),
    ],
)
def test_share_counts_are_fixed_at_the_decision_and_filled_at_the_next_price(
    case, signal, decision_bar, fill_bar, strategy_fields
) -> None:
    """Shares = weight x NAV / price, with the last prices before the earliest moment.

    Friday's close is 65.5 hours old at Monday's open: it is still the last observed
    price, and the default one-day staleness only marks it.
    """
    prices = pd.concat(
        [
            bars_at("AAPL", ["2026-11-17T21:00Z"], price=30.0),
            bars_at("AAPL", [decision_bar], price=40.0),
            bars_at("AAPL", [fill_bar], price=50.0),
        ]
    )
    ledger = ledger_for(
        stock_strategy(calendar(), **strategy_fields),
        signals=signal_frame([(signal, {"AAPL": 0.5})]),
        prices=prices,
        start="2026-11-17T22:00:00Z",
        end="2026-11-30T23:00:00Z",
    )

    # 0.5 x 10,000 / 40 = 125 shares, bought at the fill's own price, 50.
    assert executions(ledger) == [(utc(fill_bar), "AAPL", 125.0, 50.0)], case
    progress = ledger[ledger["record_kind"] == "execution_progress"].iloc[0]
    # The weight the fill reaches comes from the fill: 125 x 50 / 10,000.
    assert json.loads(progress["extension_payload"])["weight_after"] == pytest.approx(0.625)


def test_the_ledger_books_exactly_the_recorded_fills_without_its_own_mark() -> None:
    """A weekend signal fills at Monday's 1-minute prices; the ledger holds daily closes.

    Every asset of the rebalance is sized at the decision, Monday's open, from the
    same NAV and Friday's closes. ILLQ fills later, at its own price, with the
    count fixed then; the ledger looks up no mark for a fill.
    """
    events = calendar()
    strategy = stock_strategy(events, assets=("AAPL", "ILLQ"))
    monday = nyse_sessions("2026-11-23", "2026-11-23")
    state = run_strategy(
        strategy,
        signals=signal_frame([("2026-11-21T10:00:00Z", {"AAPL": 0.6, "ILLQ": 0.3})]),
        prices=pd.concat(
            [
                bars_at("AAPL", ["2026-11-20T21:00Z"], price=49.0),
                bars_at("ILLQ", ["2026-11-20T21:00Z"], price=19.0),
                minute_bars("AAPL", monday, price=50.0),
                bars_at("ILLQ", ["2026-11-23T14:45Z"], price=20.0),
            ]
        ),
        start="2026-11-20T00:00:00Z",
        end="2026-11-23T23:00:00Z",
    )
    daily = marks(
        pd.concat(
            [
                bars_at("AAPL", ["2026-11-20T21:00Z"], price=49.0),
                bars_at("ILLQ", ["2026-11-20T21:00Z"], price=19.0),
                bars_at("AAPL", ["2026-11-23T21:00Z"], price=51.0),
                bars_at("ILLQ", ["2026-11-23T21:00Z"], price=21.0),
            ]
        )
    )

    ledger = book(strategy, state, daily, initial_state="2026-11-20T00:00:00Z")

    # Decision NAV 10,000 (cash). AAPL: 0.6 x 10,000 / 49 = 122.4 -> 122, bought at
    # 14:31 at 50. ILLQ: 0.3 x 10,000 / 19 = 157.9 -> 157, bought at 14:45 at 20.
    assert executions(ledger) == [
        (utc("2026-11-23T14:31Z"), "AAPL", 122.0, 50.0),
        (utc("2026-11-23T14:45Z"), "ILLQ", 157.0, 20.0),
    ]


def held_aapl(quantity: float) -> AccountingStateView:
    empty = pd.DataFrame()
    return AccountingStateView(
        positions=pd.DataFrame(
            [
                {
                    "position_identifier": "AAPL",
                    "asset_identifier": "AAPL",
                    "balance_role": "instrument",
                    "quantity": quantity,
                    "quantity_unit": "shares",
                }
            ]
        ),
        cash=empty,
        obligations=empty,
        lifecycle_state=empty,
        execution_progress=empty,
        state_identifier="state",
    )


def test_a_halted_holding_is_valued_at_its_last_price_and_marked_stale() -> None:
    """Past maximum_staleness the price is marked stale, never refused (ADR 0058)."""
    model = MarketPriceValuationModel()
    observations = marks(bars_at("AAPL", ["2026-11-19T14:35Z"], price=50.0))

    fresh = model.value(
        state=held_aapl(10.0),
        time_index=utc("2026-11-19T21:00Z"),
        valuation_asset_identifier="USD",
        valuation_observations=observations,
        fx_observations=pd.DataFrame(),
    )
    halted = model.value(
        state=held_aapl(10.0),
        time_index=utc("2026-11-23T21:00Z"),
        valuation_asset_identifier="USD",
        valuation_observations=observations,
        fx_observations=pd.DataFrame(),
    )

    assert fresh.nav == halted.nav == pytest.approx(500.0)
    assert fresh.stale_sources == ()
    assert halted.stale_sources == ("valuation:AAPL",)
    assert json.loads(halted.valuation_references)[0]["stale"] == "true"
    with pytest.raises(ValueError, match="Missing fresh valuation observations for: AAPL"):
        MarketPriceValuationModel(fail_on_missing_values=True).value(
            state=held_aapl(10.0),
            time_index=utc("2026-11-23T21:00Z"),
            valuation_asset_identifier="USD",
            valuation_observations=observations,
            fx_observations=pd.DataFrame(),
        )
    with pytest.raises(ValueError, match="No observed valuation price at or before"):
        model.value(
            state=held_aapl(10.0),
            time_index=utc("2026-11-19T14:00Z"),
            valuation_asset_identifier="USD",
            valuation_observations=observations,
            fx_observations=pd.DataFrame(),
        )


def test_the_ledger_shows_a_stale_valuation_in_its_references() -> None:
    events = calendar()
    strategy = stock_strategy(events)
    prices = bars_at("AAPL", ["2026-11-18T21:00Z", "2026-11-19T14:31Z"], price=50.0)
    state = run_strategy(
        strategy,
        signals=signal_frame([("2026-11-18T21:30:00Z", {"AAPL": 0.5})]),
        prices=prices,
        start="2026-11-18T00:00:00Z",
        end="2026-11-30T23:00:00Z",
    )
    ledger = PortfolioEngine.calculate_backtest(
        portfolio_identifier="halted",
        accounting_configuration=PortfolioAccountingConfiguration(
            initial_nav=10_000.0,
            initial_state_time_index="2026-11-18T00:00:00Z",
            position_valuation_model_instance=MarketPriceValuationModel(),
        ),
        valuation_asset_identifier="USD",
        rebalance_strategy=strategy,
        rebalance_state=state,
        valuation_observations=marks(prices),
        valuation_times=("2026-11-23T21:00:00Z",),
    ).ledger

    summary = ledger[
        (ledger["record_kind"] == "valuation_summary")
        & (pd.to_datetime(ledger["time_index"], utc=True) == utc("2026-11-23T21:00Z"))
    ].iloc[0]
    assert summary["nav_after"] == pytest.approx(10_000.0)
    assert '"stale":"true"' in summary["valuation_references"]
    assert json.loads(summary["extension_payload"]) == {"stale_sources": ["valuation:AAPL"]}
    fresh = ledger[
        (ledger["record_kind"] == "valuation_summary")
        & (pd.to_datetime(ledger["time_index"], utc=True) == utc("2026-11-19T14:31Z"))
    ].iloc[0]
    assert pd.isna(fresh["extension_payload"])


def test_the_ledger_refuses_a_price_observed_at_another_time_than_its_fill() -> None:
    model = stock_strategy(calendar()).execution_model_instance
    fill_time = utc("2026-11-19T14:31Z")
    empty = pd.DataFrame()
    context = AccountingExecutionContext(
        time_index=fill_time,
        event_source="valuation_source",
        rebalance_intent_id="intent",
        signal_time_index=utc("2026-11-18T21:30Z"),
        signal_target_weights={"AAPL": 0.5},
        desired_weights={"AAPL": 0.5},
        weight_before={},
        asset_executions={
            "AAPL": AssetExecution(
                weight_after=0.5,
                execution_price=50.0,
                price_time_index=fill_time + pd.Timedelta(minutes=1),
            )
        },
        state=AccountingStateView(
            positions=empty,
            cash=empty,
            obligations=empty,
            lifecycle_state=empty,
            execution_progress=empty,
            state_identifier="state",
        ),
        available_balances=empty,
        pre_execution_nav=10_000.0,
        valuation_asset_identifier="USD",
        valuation_references="",
        valuation_observations=empty,
        fx_observations=empty,
        event_observations={},
        strategy_revision="revision",
        completion_tolerance=1e-12,
    )

    with pytest.raises(ValueError, match="a fill is booked at its price's own time"):
        model.simulate(context, cost_models=())


def test_the_ledger_replays_unchanged_and_adds_only_new_fills() -> None:
    events = calendar()
    strategy = stock_strategy(events)
    prices = minute_bars("AAPL", nyse_sessions("2026-11-18", "2026-11-20"), price=50.0)
    signals = signal_frame(
        [
            ("2026-11-18T21:30:00Z", {"AAPL": 0.6}),
            ("2026-11-19T22:00:00Z", {"AAPL": 0.2}),
        ]
    )
    valuations = marks(prices)

    def ledger_at(run_time: str) -> pd.DataFrame:
        events.published_until = utc(run_time)
        visible = prices[prices["time_index"] <= utc(run_time)]
        state = run_strategy(
            strategy,
            signals=signals,
            prices=visible,
            start="2026-11-18T00:00:00Z",
            end=run_time,
        )
        return book(
            strategy,
            state,
            valuations[valuations["time_index"] <= utc(run_time)],
            initial_state="2026-11-18T00:00:00Z",
        )

    first = ledger_at("2026-11-19T21:30:00Z")
    replay = ledger_at("2026-11-19T21:30:00Z")
    later = ledger_at("2026-11-20T15:00:00Z")

    pd.testing.assert_frame_equal(first, replay)
    assert _new_ledger_tail(first, replay).empty
    _validate_replay_against_existing(first, later)
    tail = _new_ledger_tail(first, later)
    assert executions(first) == [(utc("2026-11-19T14:31Z"), "AAPL", 120.0, 50.0)]
    assert executions(tail) == [(utc("2026-11-20T14:31Z"), "AAPL", -80.0, 50.0)]


def test_the_ledger_update_reads_the_recorded_rebalance_state() -> None:
    events = calendar()
    strategy = stock_strategy(events)
    prices = minute_bars("AAPL", nyse_sessions("2026-11-11", "2026-11-12"), price=50.0)
    state = run_strategy(
        strategy,
        signals=signal_frame([("2026-11-11T22:00:00Z", {"AAPL": 0.5})]),
        prices=prices,
        start="2026-11-11T00:00:00Z",
        end="2026-11-12T23:00:00Z",
    ).assign(portfolio_identifier="recorded-fills")
    rebalance = PublishedTable.build(
        "portfolio-rebalance",
        state,
        index=["time_index", "portfolio_identifier", "rebalance_intent_id", ASSET_IDENTIFIER],
    )
    valuations = PublishedTable.build(
        "valuations",
        marks(prices),
        index=["time_index", ASSET_IDENTIFIER],
    )
    node = object.__new__(PortfolioEngine)
    node.config = PortfolioEngineConfiguration(
        portfolio_identifier="recorded-fills",
        valuation_asset_identifier="USD",
        accounting_configuration=PortfolioAccountingConfiguration(
            initial_nav=10_000.0,
            initial_state_time_index="2026-11-11T00:00:00Z",
            position_valuation_model_instance=MarketPriceValuationModel(
                valuation_source=valuations
            ),
        ),
        portfolio_rebalance_instance=rebalance,
        rebalance_strategy_instance=strategy,
    )
    node._retirement_boundary = lambda _portfolio_identifier: None
    node.get_df_between_dates = lambda **_kwargs: pd.DataFrame()

    assert node.dependencies() == {
        "portfolio_rebalance": rebalance,
        "valuation.valuations": valuations,
    }
    with _bound(PortfolioEventLedgerStorage, str(uuid.uuid4())) as storage:
        node.output_table = storage
        ledger = node.update().reset_index()

    assert executions(ledger) == [(utc("2026-11-12T14:31Z"), "AAPL", 100.0, 50.0)]
