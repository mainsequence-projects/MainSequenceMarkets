"""Identity payloads hash date and time values as ISO strings.

The MetaTables serializer turns ``datetime.datetime`` into an ISO string but leaves
``datetime.date`` and ``datetime.time`` as objects, which ``hash_signature`` cannot
JSON-encode.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import Field

from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.time_index import (
    PortfolioWeights,
    SignalWeights,
    canonical_signal_configuration,
    compute_signal_uid,
)
from msm_portfolios.time_index.base import _isoformat_dates_and_times
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalanceStateStorage
from msm_portfolios.time_index.portfolios.storage import PortfolioEventLedgerStorage
from tests.support.pinned_identities import (
    NESTED_PORTFOLIOS,
    _bound,
    _built_updaters,
    _signal,
)

REBALANCE_TABLE_UID = "3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6a"
LEDGER_TABLE_UID = "3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6b"


class SessionSignalConfiguration(PortfolioConfigBaseModel):
    """A signal configuration declared by an application, with a date and a time."""

    start_date: dt.date = Field(dt.date(2026, 1, 2), description="First trading date.")
    session_open: dt.time = Field(dt.time(9, 30), description="Daily session open.")


class SessionSignal(SignalWeights):
    """A signal declared by an application, outside ms-markets."""


def test_dates_and_times_become_iso_strings_and_datetimes_stay_as_they_are() -> None:
    moment = dt.datetime(2026, 1, 2, 9, 30, tzinfo=dt.UTC)

    assert _isoformat_dates_and_times(
        {"window": [dt.date(2026, 1, 2), (dt.time(9, 30),)], "moment": moment}
    ) == {"window": ["2026-01-02", ("09:30:00",)], "moment": moment}


def test_signal_configurations_with_dates_and_times_get_a_signal_uid() -> None:
    signal = _signal(SessionSignal, SessionSignalConfiguration())

    canonical = json.dumps(canonical_signal_configuration(signal))
    assert '"start_date": "2026-01-02"' in canonical
    assert '"session_open": "09:30:00"' in canonical
    assert compute_signal_uid(signal) == compute_signal_uid(
        _signal(SessionSignal, SessionSignalConfiguration())
    )


@pytest.mark.parametrize(
    "name",
    [
        "time_weighted_rebalance",
        "volume_participation_rebalance",
        "trailing_average_daily_volume_rebalance",
    ],
)
def test_portfolio_updaters_with_execution_windows_get_a_stable_update_hash(name: str) -> None:
    """MetaTables 0.1.57 hashes the ``datetime.time`` execution windows of these strategies.

    The rebalance state is the updater that carries them (ADR 0060: the weights and
    values nodes publish to Markets and have no update hash).
    """

    def rebalance(updaters):
        weights = PortfolioWeights()
        weights.set_portfolio_configuration(
            NESTED_PORTFOLIOS[name](updaters), portfolio_identifier="pinned-portfolio"
        )
        return weights.portfolio_rebalance

    with (
        _built_updaters() as updaters,
        # Every storage the updaters touch is bound, so nothing reaches a MetaTables backend.
        _bound(PortfolioRebalanceStateStorage, REBALANCE_TABLE_UID),
        _bound(PortfolioEventLedgerStorage, LEDGER_TABLE_UID),
    ):
        first = rebalance(updaters)
        rebuilt = rebalance(updaters)

    assert first.update_hash.startswith("portfoliorebalance_")
    assert rebuilt.update_hash == first.update_hash
