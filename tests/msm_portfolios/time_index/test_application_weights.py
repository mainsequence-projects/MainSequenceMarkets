from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
from metatables import TimeIndexTableUpdater

from msm.api.assets import Asset
from msm_portfolios.contrib.signals import ApplicationWeights, ApplicationWeightsConfig
from msm_portfolios.time_index import ASSET_IDENTIFIER, SIGNAL_UID, SignalWeights
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage

UTC = dt.UTC
KNOWN_ASSETS = {"AAA", "BBB", "CCC"}
INDEX = ["time_index", SIGNAL_UID, ASSET_IDENTIFIER]


class SignalStore:
    """In-memory SignalWeightsTS: persists what update() returns, as the runner does."""

    def __init__(self) -> None:
        self.frame = pd.DataFrame(
            {"signal_weight": pd.Series(dtype=float)},
            index=pd.MultiIndex.from_arrays([[], [], []], names=INDEX),
        )
        self.runs = 0

    def last_observation(self, _updater, *, dimension_filters=None, **_kwargs):
        flat = self.frame.reset_index()
        flat = flat[flat[SIGNAL_UID].isin(dimension_filters[SIGNAL_UID])]
        last = flat.sort_values("time_index").groupby(ASSET_IDENTIFIER).tail(1)
        return last.set_index(INDEX)

    def run(self, signal: ApplicationWeights):
        def _run(*, update_tree: bool = True) -> None:
            assert update_tree is False
            self.runs += 1
            signal.update_statistics = SimpleNamespace(max_time_index_value=None)
            written = signal.update()
            self.frame = pd.concat([self.frame, written]).sort_index()

        return _run

    def weights_at(self, time: dt.datetime) -> dict[str, float]:
        flat = self.frame.reset_index()
        rows = flat[flat["time_index"] == pd.Timestamp(time)]
        return dict(zip(rows[ASSET_IDENTIFIER], rows["signal_weight"], strict=True))


@pytest.fixture
def store(monkeypatch) -> SignalStore:
    store = SignalStore()
    monkeypatch.setattr(TimeIndexTableUpdater, "get_last_observation", store.last_observation)
    monkeypatch.setattr(
        Asset,
        "get_many_by_unique_identifier",
        classmethod(
            lambda cls, identifiers: {
                identifier: object() for identifier in identifiers if identifier in KNOWN_ASSETS
            }
        ),
    )
    monkeypatch.setattr(
        "msm_portfolios.time_index.signals.weights.emit_signal_metadata",
        lambda **_kwargs: None,
    )
    return store


def _signal(store: SignalStore, *, provider="provider-a", key="1") -> ApplicationWeights:
    signal = object.__new__(ApplicationWeights)
    signal.signal_configuration = ApplicationWeightsConfig(provider=provider, key=key)
    signal.use_canonical_signal_weights = True
    signal.canonical_signal_weights_node = signal
    signal._output_table = SignalWeightsStorage
    signal.run = store.run(signal)
    return signal


def _at(day: int) -> dt.datetime:
    return dt.datetime(2026, 1, day, 21, tzinfo=UTC)


def test_identity_is_the_configuration_not_the_weights(store) -> None:
    first = _signal(store)
    first.publish({_at(1): {"AAA": 1.0}})
    second = _signal(store)
    second.publish({_at(2): {"BBB": 1.0}})

    assert first.signal_uid == second.signal_uid
    assert _signal(store, provider="provider-b").signal_uid != first.signal_uid
    assert _signal(store, key="2").signal_uid != first.signal_uid


def test_signal_has_no_dependencies_and_forward_fills_until_the_next_observation() -> None:
    signal = object.__new__(ApplicationWeights)

    assert signal.dependencies() == {}
    assert signal.maximum_forward_fill() >= dt.timedelta(days=365 * 99)


def test_weights_are_stored_as_given_keyed_by_unique_identifier(store) -> None:
    signal = _signal(store)
    signal.publish({_at(1): {"AAA": 0.7, "BBB": -0.4}})

    assert store.weights_at(_at(1)) == {"AAA": 0.7, "BBB": -0.4}
    assert set(store.frame.index.get_level_values(SIGNAL_UID)) == {signal.signal_uid}


def test_an_asset_the_previous_observation_held_is_written_at_zero(store) -> None:
    signal = _signal(store)
    signal.publish({_at(1): {"AAA": 0.5, "BBB": 0.5}})
    signal.publish({_at(2): {"BBB": 0.6, "CCC": 0.4}})

    assert store.weights_at(_at(2)) == {"AAA": 0.0, "BBB": 0.6, "CCC": 0.4}
    assert signal.get_asset_list() == ["AAA", "BBB", "CCC"]


def test_several_observations_are_one_write_and_each_is_a_whole_set(store) -> None:
    signal = _signal(store)
    signal.publish(
        {
            _at(3): {"CCC": 1.0},
            _at(1): {"AAA": 1.0},
            _at(2): {"BBB": 1.0},
        }
    )

    assert store.runs == 1
    assert store.weights_at(_at(1)) == {"AAA": 1.0}
    assert store.weights_at(_at(2)) == {"AAA": 0.0, "BBB": 1.0}
    assert store.weights_at(_at(3)) == {"BBB": 0.0, "CCC": 1.0}


def test_an_empty_observation_closes_every_held_asset(store) -> None:
    signal = _signal(store)
    signal.publish({_at(1): {"AAA": 0.5, "BBB": 0.5}})
    signal.publish({_at(2): {}})

    assert store.weights_at(_at(2)) == {"AAA": 0.0, "BBB": 0.0}


def test_an_empty_observation_with_nothing_held_is_refused(store) -> None:
    with pytest.raises(ValueError, match="nothing to close"):
        _signal(store).publish({_at(1): {}})


def test_observations_at_or_before_the_last_stored_time_are_refused(store) -> None:
    signal = _signal(store)
    signal.publish({_at(2): {"AAA": 1.0}})

    for time in (_at(1), _at(2)):
        with pytest.raises(ValueError, match="never restated"):
            signal.publish({time: {"BBB": 1.0}, _at(3): {"BBB": 1.0}})
    assert store.runs == 3
    assert set(store.frame.index.get_level_values("time_index")) == {pd.Timestamp(_at(2))}


def test_times_are_utc_and_must_carry_a_timezone(store) -> None:
    signal = _signal(store)
    new_york = dt.timezone(dt.timedelta(hours=-5))
    signal.publish({dt.datetime(2026, 1, 1, 16, tzinfo=new_york): {"AAA": 1.0}})

    assert store.weights_at(_at(1)) == {"AAA": 1.0}
    with pytest.raises(ValueError, match="no timezone"):
        signal.publish({dt.datetime(2026, 1, 5): {"AAA": 1.0}})


def test_an_unknown_asset_refuses_the_whole_call(store) -> None:
    signal = _signal(store)
    with pytest.raises(LookupError, match="TYPO"):
        signal.publish({_at(1): {"AAA": 1.0}, _at(2): {"TYPO": 1.0}})

    assert store.runs == 0
    assert store.frame.empty


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), "0.5", True, None])
def test_weights_must_be_finite_numbers(store, weight) -> None:
    with pytest.raises((TypeError, ValueError)):
        _signal(store).publish({_at(1): {"AAA": weight}})
    assert store.runs == 0


def test_publish_needs_an_observation(store) -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        _signal(store).publish({})


def test_rows_the_update_would_filter_out_are_refused_not_dropped(store) -> None:
    signal = _signal(store)
    signal._pending_observations = [(pd.Timestamp(_at(2)), {"AAA": 1.0})]
    signal.update_statistics = SimpleNamespace(
        max_time_index_value=_at(3),
        filter_df_by_latest_value=lambda frame: frame.iloc[0:0],
    )

    with pytest.raises(ValueError, match="would not be written"):
        signal.update()


def test_an_idle_run_writes_nothing(store) -> None:
    signal = _signal(store)
    signal.update_statistics = SimpleNamespace(max_time_index_value=None)

    assert signal.update().empty


def test_published_weights_forward_fill_into_portfolio_events(store) -> None:
    signal = _signal(store)
    signal.publish({_at(1): {"AAA": 0.6, "BBB": 0.4}})
    signal.publish({_at(10): {"BBB": 1.0}})

    class Reader:
        def get_df_between_dates(self, *, start_date, end_date, dimension_filters, **_kwargs):
            times = store.frame.index.get_level_values("time_index")
            return store.frame[(times >= start_date) & (times <= end_date)]

        def get_last_observation(self, *, dimension_range_map):
            end = pd.Timestamp(dimension_range_map[0]["end_date"])
            flat = store.frame.reset_index()
            flat = flat[flat["time_index"] < end]
            return flat.sort_values("time_index").groupby(ASSET_IDENTIFIER).tail(1).set_index(INDEX)

    events = pd.DatetimeIndex([_at(5), dt.datetime(2026, 12, 1, 21, tzinfo=UTC)], name="time_index")
    weights = SignalWeights.interpolate_index(signal, events, signal_weights_node=Reader())

    assert weights.loc[events[0], "AAA"] == pytest.approx(0.6)
    assert weights.loc[events[0], "BBB"] == pytest.approx(0.4)
    assert weights.loc[events[1], "AAA"] == pytest.approx(0.0)
    assert weights.loc[events[1], "BBB"] == pytest.approx(1.0)
