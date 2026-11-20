"""``ApplicationWeights`` publishes an application's weights to Markets (ADR 0060).

Each test migrates a fresh SQLite file and publishes through ``SignalWeightsSeries`` on
MetaTables' own server code for the local runtime (`make_sqlite_markets`). The rules
(whole sets, dropped assets closed at 0, nothing restated) run in Markets.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from msm_portfolios.api import SignalWeightsSeries
from msm_portfolios.contrib.signals import ApplicationWeights, ApplicationWeightsConfig
from msm_portfolios.time_index import SIGNAL_UID, SignalWeights
from tests.msm.repositories.test_sqlite_snapshot_writes import _asset, make_sqlite_markets

UTC = dt.UTC


@pytest.fixture
def markets(tmp_path, monkeypatch):
    markets = make_sqlite_markets(tmp_path, monkeypatch)
    for asset in ("AAA", "BBB", "CCC"):
        _asset(markets.engine, asset)
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **_kwargs: SimpleNamespace(context=markets.context),
    )
    return markets


def _signal(*, provider="provider-a", key="1") -> ApplicationWeights:
    return ApplicationWeights.from_signal_configuration(
        ApplicationWeightsConfig(provider=provider, key=key)
    )


def _at(day: int) -> dt.datetime:
    return dt.datetime(2026, 1, day, 21, tzinfo=UTC)


def _weights_at(signal: ApplicationWeights, time: dt.datetime) -> dict[str, float]:
    rows = SignalWeightsSeries.window([signal.signal_uid], start=time, end=time).rows
    return {row["asset_identifier"]: row["signal_weight"] for row in rows}


def _row_count(signal: ApplicationWeights) -> int:
    return SignalWeightsSeries.bounds([signal.signal_uid])[0].row_count


def test_identity_is_the_configuration_not_the_weights(markets) -> None:
    first = _signal()
    first.publish({_at(1): {"AAA": 1.0}})
    second = _signal()
    second.publish({_at(2): {"BBB": 1.0}})

    assert first.signal_uid == second.signal_uid
    assert _signal(provider="provider-b").signal_uid != first.signal_uid
    assert _signal(key="2").signal_uid != first.signal_uid


def test_signal_has_no_dependencies_and_forward_fills_until_the_next_observation() -> None:
    signal = object.__new__(ApplicationWeights)

    assert signal.dependencies() == {}
    assert signal.maximum_forward_fill() >= dt.timedelta(days=365 * 99)
    assert ApplicationWeights.computes_weights is False


def test_weights_are_stored_as_given_keyed_by_unique_identifier(markets) -> None:
    signal = _signal()
    signal.publish({_at(1): {"AAA": 0.7, "BBB": -0.4}})

    assert _weights_at(signal, _at(1)) == {"AAA": 0.7, "BBB": -0.4}
    frame = SignalWeightsSeries.window([signal.signal_uid]).frame()
    assert set(frame.index.get_level_values(SIGNAL_UID)) == {signal.signal_uid}


def test_an_asset_the_previous_observation_held_is_written_at_zero(markets) -> None:
    signal = _signal()
    signal.publish({_at(1): {"AAA": 0.5, "BBB": 0.5}})
    signal.publish({_at(2): {"BBB": 0.6, "CCC": 0.4}})

    assert _weights_at(signal, _at(2)) == {"AAA": 0.0, "BBB": 0.6, "CCC": 0.4}
    assert signal.get_asset_list() == ["AAA", "BBB", "CCC"]


def test_several_observations_are_one_call_and_each_is_a_whole_set(markets) -> None:
    signal = _signal()
    publication = signal.publish({_at(3): {"CCC": 1.0}, _at(1): {"AAA": 1.0}, _at(2): {"BBB": 1.0}})

    assert publication.written == 5
    assert _weights_at(signal, _at(1)) == {"AAA": 1.0}
    assert _weights_at(signal, _at(2)) == {"AAA": 0.0, "BBB": 1.0}
    assert _weights_at(signal, _at(3)) == {"BBB": 0.0, "CCC": 1.0}


def test_an_empty_observation_with_nothing_held_is_refused(markets) -> None:
    with pytest.raises(ValueError, match="nothing to close"):
        _signal().publish({_at(1): {}})


def test_observations_at_or_before_the_last_stored_time_are_refused(markets) -> None:
    signal = _signal()
    signal.publish({_at(2): {"AAA": 1.0}})

    with pytest.raises(ValueError, match="never restated"):
        signal.publish({_at(1): {"BBB": 1.0}, _at(3): {"BBB": 1.0}})
    with pytest.raises(ValueError, match="never restated"):
        signal.publish({_at(2): {"BBB": 1.0}, _at(3): {"BBB": 1.0}})
    assert _row_count(signal) == 1


def test_times_are_utc_and_must_carry_a_timezone(markets) -> None:
    signal = _signal()
    new_york = dt.timezone(dt.timedelta(hours=-5))
    signal.publish({dt.datetime(2026, 1, 1, 16, tzinfo=new_york): {"AAA": 1.0}})

    assert _weights_at(signal, _at(1)) == {"AAA": 1.0}
    with pytest.raises(ValueError, match="no timezone"):
        signal.publish({dt.datetime(2026, 1, 5): {"AAA": 1.0}})


def test_an_unknown_asset_refuses_the_whole_call(markets) -> None:
    signal = _signal()
    with pytest.raises(LookupError, match="TYPO"):
        signal.publish({_at(1): {"AAA": 1.0}, _at(2): {"TYPO": 1.0}})

    assert _row_count(signal) == 0


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), "0.5", True, None])
def test_weights_must_be_finite_numbers(markets, weight) -> None:
    signal = _signal()
    with pytest.raises((TypeError, ValueError)):
        signal.publish({_at(1): {"AAA": weight}})
    assert _row_count(signal) == 0


def test_publish_needs_an_observation(markets) -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        _signal().publish({})


def test_a_run_calculates_nothing(markets) -> None:
    assert _signal().update().empty


def test_published_weights_forward_fill_into_portfolio_events(markets) -> None:
    signal = _signal()
    signal.publish({_at(1): {"AAA": 0.6, "BBB": 0.4}})
    signal.publish({_at(10): {"BBB": 1.0}})

    events = pd.DatetimeIndex([_at(5), dt.datetime(2026, 12, 1, 21, tzinfo=UTC)], name="time_index")
    weights = SignalWeights.interpolate_index(signal, events)

    assert weights.loc[events[0], "AAA"] == pytest.approx(0.6)
    assert weights.loc[events[0], "BBB"] == pytest.approx(0.4)
    assert weights.loc[events[1], "AAA"] == pytest.approx(0.0)
    assert weights.loc[events[1], "BBB"] == pytest.approx(1.0)
