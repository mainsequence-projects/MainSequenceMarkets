"""A calendar-reading strategy must use the calendar on the portfolio's row (ADR 0056)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from msm.api.calendars import Calendar
from msm_portfolios.rebalance_strategy import CalendarEventSignal, ImmediateSignal, TimeWeighted
from msm_portfolios.time_index.portfolios import PortfolioValues

STORED = {
    "NYSE": SimpleNamespace(uid="nyse-uid", unique_identifier="NYSE"),
    "CustomNYSE": SimpleNamespace(uid="custom-uid", unique_identifier="CustomNYSE"),
}


@pytest.fixture(autouse=True)
def stored_calendars(monkeypatch) -> None:
    monkeypatch.setattr(Calendar, "get_by_unique_identifier", STORED.get)
    monkeypatch.setattr(
        Calendar,
        "get_by_uid",
        lambda uid: next((row for row in STORED.values() if row.uid == uid), None),
    )


def check(strategy, *, calendar_uid) -> None:
    updater = SimpleNamespace(
        portfolio_build_configuration=SimpleNamespace(
            backtesting_weights_configuration=SimpleNamespace(rebalance_strategy_instance=strategy)
        )
    )
    portfolio = SimpleNamespace(unique_identifier="P", calendar_uid=calendar_uid)
    PortfolioValues._require_strategy_calendar(updater, portfolio)


def calendar_event_signal(identifier: str) -> CalendarEventSignal:
    return CalendarEventSignal.model_construct(calendar_identifier=identifier)


def test_the_strategy_on_the_portfolios_calendar_is_accepted() -> None:
    check(calendar_event_signal("CustomNYSE"), calendar_uid="custom-uid")


def test_a_strategy_on_another_calendar_is_refused_and_both_are_named() -> None:
    with pytest.raises(ValueError) as raised:
        check(calendar_event_signal("CustomNYSE"), calendar_uid="nyse-uid")

    message = str(raised.value)
    assert "Portfolio 'P' has calendar 'NYSE' on its row" in message
    assert "its rebalance strategy uses calendar 'CustomNYSE'" in message


def test_a_strategy_calendar_that_is_not_stored_is_refused() -> None:
    with pytest.raises(ValueError, match="uses calendar 'MISSING'"):
        check(calendar_event_signal("MISSING"), calendar_uid="nyse-uid")


def test_a_portfolio_without_a_calendar_is_refused() -> None:
    with pytest.raises(ValueError, match="has no calendar on its row"):
        check(calendar_event_signal("NYSE"), calendar_uid=None)


def test_an_immediate_signal_on_another_calendar_is_refused() -> None:
    check(ImmediateSignal.model_construct(calendar_identifier="NYSE"), calendar_uid="nyse-uid")

    with pytest.raises(ValueError) as raised:
        check(
            ImmediateSignal.model_construct(calendar_identifier="CustomNYSE"),
            calendar_uid="nyse-uid",
        )

    assert "its rebalance strategy uses calendar 'CustomNYSE'" in str(raised.value)
    assert "Its ImmediateSignal must use the calendar" in str(raised.value)


def test_strategies_that_read_no_calendar_are_not_checked(monkeypatch) -> None:
    monkeypatch.setattr(
        Calendar,
        "get_by_unique_identifier",
        lambda _identifier: pytest.fail("only a calendar-reading strategy is checked"),
    )

    check(TimeWeighted.model_construct(), calendar_uid="nyse-uid")
