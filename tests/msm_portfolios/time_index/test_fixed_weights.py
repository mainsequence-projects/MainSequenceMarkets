"""``FixedWeights`` publishes its weights once, at the time its configuration states (#134).

The test migrates a fresh SQLite file and publishes through ``SignalWeightsSeries`` on
MetaTables' own server code for the local runtime (`make_sqlite_markets`).
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from msm_portfolios.api import SignalWeightsSeries
from msm_portfolios.contrib.signals import AUIDWeight, FixedWeights, FixedWeightsConfig
from tests.support.sqlite_markets import _asset, make_sqlite_markets, serve_row_operations

UTC = dt.UTC
STATED = dt.datetime(2026, 5, 23, 12, tzinfo=UTC)


@pytest.fixture
def markets(tmp_path, monkeypatch, sqlite_revisions):
    markets = make_sqlite_markets(tmp_path, monkeypatch, template=sqlite_revisions.file("head"))
    for asset in ("AAA", "BBB"):
        _asset(markets.engine, asset)
    serve_row_operations(monkeypatch, markets)
    return markets


def _configuration(signal_time_index: dt.datetime) -> FixedWeightsConfig:
    return FixedWeightsConfig(
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier="AAA", weight=0.6),
            AUIDWeight(unique_identifier="BBB", weight=0.4),
        ],
        signal_time_index=signal_time_index,
    )


def test_the_one_observation_is_at_the_stated_time_and_is_published_once(markets) -> None:
    signal = FixedWeights.from_signal_configuration(_configuration(STATED))

    signal.run()
    signal.run()

    (bounds,) = SignalWeightsSeries.bounds([signal.signal_uid])
    assert (bounds.first_time, bounds.last_time, bounds.row_count) == (STATED, STATED, 2)
    rows = SignalWeightsSeries.window([signal.signal_uid]).rows
    assert {row["asset_identifier"]: row["signal_weight"] for row in rows} == {
        "AAA": 0.6,
        "BBB": 0.4,
    }


def test_a_run_writes_the_signals_metadata_only_when_it_is_new(markets, monkeypatch) -> None:
    from msm_portfolios.api import SignalMetadata

    writes: list[str] = []
    for name in ("create", "update", "upsert"):
        original = getattr(SignalMetadata, name).__func__

        def spy(cls, *args, _original=original, _name=name, **kwargs):
            writes.append(_name)
            return _original(cls, *args, **kwargs)

        monkeypatch.setattr(SignalMetadata, name, classmethod(spy))
    signal = FixedWeights.from_signal_configuration(_configuration(STATED))

    signal.run()
    signal.run()

    # The first run creates the row (#136); the second finds it unchanged.
    assert writes == ["create"]
    (row,) = SignalMetadata.filter(signal_uid=signal.signal_uid)
    assert row.signal_description == signal.get_explanation()


def test_the_time_is_part_of_the_identity_and_must_be_timezone_aware() -> None:
    def uid(signal_time_index: dt.datetime) -> str:
        return FixedWeights.from_signal_configuration(
            _configuration(signal_time_index)
        ).signal_uid

    assert uid(STATED) != uid(STATED + dt.timedelta(days=1))
    with pytest.raises(ValidationError, match="signal_time_index must be timezone-aware"):
        _configuration(STATED.replace(tzinfo=None))
