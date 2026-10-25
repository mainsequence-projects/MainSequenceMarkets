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
    PortfoliosUpdater,
    PortfolioWeights,
    SignalWeights,
    canonical_signal_configuration,
    compute_signal_uid,
)
from msm_portfolios.time_index.base import _isoformat_dates_and_times
from msm_portfolios.time_index.portfolios.storage import (
    PortfoliosStorage,
    PortfolioWeightsStorage,
)
from tests.identity.test_pinned_identities import (
    NESTED_PORTFOLIOS,
    _bound,
    _built_updaters,
    _signal,
)

WEIGHTS_TABLE_UID = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
PORTFOLIOS_TABLE_UID = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"


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
    """MetaTables 0.1.57 hashes the ``datetime.time`` execution windows of these strategies."""

    with (
        _built_updaters() as updaters,
        _bound(PortfolioWeightsStorage, WEIGHTS_TABLE_UID),
        _bound(PortfoliosStorage, PORTFOLIOS_TABLE_UID),
    ):
        weights = PortfolioWeights(portfolio_configuration=NESTED_PORTFOLIOS[name](updaters))
        portfolios = PortfoliosUpdater(portfolio_configuration=NESTED_PORTFOLIOS[name](updaters))
        rebuilt = PortfolioWeights(portfolio_configuration=NESTED_PORTFOLIOS[name](updaters))

    assert weights.update_hash.startswith("portfolioweights_")
    assert portfolios.update_hash.startswith("portfoliosupdater_")
    assert rebuilt.update_hash == weights.update_hash
