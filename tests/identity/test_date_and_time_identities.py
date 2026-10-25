"""Identity payloads hash date and time values as ISO strings.

The MetaTables serializer turns ``datetime.datetime`` into an ISO string but leaves
``datetime.date`` and ``datetime.time`` as objects, which ``hash_signature`` cannot
JSON-encode.
"""

from __future__ import annotations

import datetime as dt
import json

from pydantic import Field

from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.time_index import (
    SignalWeights,
    canonical_signal_configuration,
    compute_signal_uid,
)
from msm_portfolios.time_index.base import _isoformat_dates_and_times
from tests.identity.test_pinned_identities import _signal


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
