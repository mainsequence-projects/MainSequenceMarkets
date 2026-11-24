"""``FixedWeights``, a computed signal: its own node and table, and it publishes (#134).

A computed signal writes its producer's own ``SignalWeightsTS`` instance and publishes the
same rows to Markets' (ADR 0060, amended on 2026-11-24). Each test migrates a fresh SQLite
file and publishes through ``SignalWeightsSeries`` on MetaTables' own server code for the
local runtime (`make_sqlite_markets`). The node's own table is bound to a stand-in
registration; MetaTables writes what ``update()`` returns, and the update statistics it
answers after the write are stood in.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import TimeIndexMetaTable, UpdateStatistics, sqlalchemy_naming_convention
from msm.storage_instances import configured_time_index_instance
from msm_portfolios.api import SignalMetadata, SignalWeightsSeries
from msm_portfolios.contrib.signals import AUIDWeight, FixedWeights, FixedWeightsConfig
from msm_portfolios.time_index import SignalWeights, compute_signal_uid
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage
from tests.support.pinned_identities import _bound
from tests.support.sqlite_markets import _asset, make_sqlite_markets, serve_row_operations

UTC = dt.UTC
STATED = dt.datetime(2026, 5, 23, 12, tzinfo=UTC)


class ProducerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


def _signal_table(instance_key: str) -> type:
    return configured_time_index_instance(
        SignalWeightsStorage,
        instance_key=instance_key,
        namespace="my-app",
        storage_app="my_app",
        base=ProducerBase,
    )


@pytest.fixture
def markets(tmp_path, monkeypatch, sqlite_revisions):
    markets = make_sqlite_markets(tmp_path, monkeypatch, template=sqlite_revisions.file("head"))
    for asset in ("AAA", "BBB"):
        _asset(markets.engine, asset)
    serve_row_operations(monkeypatch, markets)
    return markets


@pytest.fixture
def signal_table():
    with _bound(_signal_table("signals"), "a0000000-0000-4000-8000-0000000000cc") as table:
        yield table


def _configuration(signal_time_index: dt.datetime) -> FixedWeightsConfig:
    return FixedWeightsConfig(
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier="AAA", weight=0.6),
            AUIDWeight(unique_identifier="BBB", weight=0.4),
        ],
        signal_time_index=signal_time_index,
    )


def _node(table: type, signal_time_index: dt.datetime = STATED, **kwargs) -> FixedWeights:
    signal = FixedWeights.from_signal_configuration(
        _configuration(signal_time_index), output_table=table, **kwargs
    )
    signal.update_statistics = _statistics()
    return signal


def _statistics(*frames: pd.DataFrame) -> SimpleNamespace:
    """The table's update statistics once it holds ``frames``' rows, as MetaTables answers."""

    progress: dict = {}
    for frame in frames:
        for time, signal_uid, asset in frame.index:
            by_asset = progress.setdefault(signal_uid, {})
            by_asset[asset] = max(time, by_asset.get(asset, time))
    return SimpleNamespace(index_progress=progress)


def _weights(frame: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], float]:
    return {
        (pd.Timestamp(time), asset): weight
        for (time, _signal, asset), weight in frame["signal_weight"].items()
    }


def test_the_node_writes_its_one_observation_and_publishes_it_once(markets, signal_table) -> None:
    signal = _node(signal_table)

    written = signal.update()
    signal.update_statistics = _statistics(written)  # MetaTables wrote them to the table
    again = signal.update()

    assert list(written.index.names) == ["time_index", "signal_uid", "asset_identifier"]
    assert _weights(written) == {(pd.Timestamp(STATED), "AAA"): 0.6, (pd.Timestamp(STATED), "BBB"): 0.4}
    assert again.empty
    (bounds,) = SignalWeightsSeries.bounds([signal.signal_uid])
    assert (bounds.first_time, bounds.last_time, bounds.row_count) == (STATED, STATED, 2)
    rows = SignalWeightsSeries.window([signal.signal_uid]).rows
    assert {row["asset_identifier"]: row["signal_weight"] for row in rows} == {
        "AAA": 0.6,
        "BBB": 0.4,
    }


def test_rows_markets_already_has_are_written_to_the_table_and_not_published_again(
    markets, signal_table
) -> None:
    """A write that failed after the publish: the next run computes the rows again."""

    signal = _node(signal_table)

    signal.update()  # published, then the table's write failed
    again = signal.update()

    assert _weights(again) == {(pd.Timestamp(STATED), "AAA"): 0.6, (pd.Timestamp(STATED), "BBB"): 0.4}
    assert SignalWeightsSeries.bounds([signal.signal_uid])[0].row_count == 2


def test_no_row_before_the_signals_last_one_is_written_or_published(markets, signal_table) -> None:
    """Markets never restates an observation, so the table takes none either: an asset new
    to the signal starts after the signal's last row, not after its own."""

    earlier, first, last = STATED, STATED + dt.timedelta(days=1), STATED + dt.timedelta(days=2)

    class Rotating(SignalWeights):
        def maximum_forward_fill(self):
            return dt.timedelta(days=1)

    signal = Rotating.from_signal_configuration({"kind": "rotating"}, output_table=signal_table)
    signal.set_signal_weights_frame(
        pd.DataFrame(
            [(first, "AAA", 1.0)], columns=["time_index", "asset_identifier", "signal_weight"]
        ).set_index(["time_index", "asset_identifier"])
    )
    signal.update_statistics = _statistics()
    written = signal.update()
    signal.update_statistics = _statistics(written)
    signal.set_signal_weights_frame(
        pd.DataFrame(
            [(earlier, "BBB", 1.0), (last, "AAA", 0.5), (last, "BBB", 0.5)],
            columns=["time_index", "asset_identifier", "signal_weight"],
        ).set_index(["time_index", "asset_identifier"])
    )

    later = signal.update()

    assert _weights(later) == {(pd.Timestamp(last), "AAA"): 0.5, (pd.Timestamp(last), "BBB"): 0.5}
    (bounds,) = SignalWeightsSeries.bounds([signal.signal_uid])
    assert (bounds.first_time, bounds.last_time, bounds.row_count) == (first, last, 3)


def test_a_run_writes_the_signals_metadata_only_when_it_is_new(
    markets, signal_table, monkeypatch
) -> None:
    writes: list[str] = []
    for name in ("create", "update", "upsert"):
        original = getattr(SignalMetadata, name).__func__

        def spy(cls, *args, _original=original, _name=name, **kwargs):
            writes.append(_name)
            return _original(cls, *args, **kwargs)

        monkeypatch.setattr(SignalMetadata, name, classmethod(spy))
    signal = _node(signal_table)

    written = signal.update()
    signal.update_statistics = _statistics(written)
    signal.update()

    # The first run creates the row (#136), before the table's rows that reference it;
    # the second finds it unchanged.
    assert writes == ["create"]
    (row,) = SignalMetadata.filter(signal_uid=signal.signal_uid)
    assert row.signal_description == signal.get_explanation()


def test_its_first_observation_is_read_from_its_tables_statistics(
    signal_table, monkeypatch
) -> None:
    signal = _node(signal_table)
    reads: list[str] = []

    def get_data_updates(self, **_kwargs):
        reads.append(self.uid)
        return UpdateStatistics(
            index_min={
                signal.signal_uid: {"AAA": STATED + dt.timedelta(hours=1), "BBB": STATED},
                "another-signal": {"AAA": STATED - dt.timedelta(days=9)},
            }
        )

    monkeypatch.setattr(TimeIndexMetaTable, "get_data_updates", get_data_updates)

    assert signal.first_observation_time() == pd.Timestamp(STATED)
    assert reads == ["a0000000-0000-4000-8000-0000000000cc"]
    other = _node(signal_table, STATED + dt.timedelta(days=1))
    assert other.first_observation_time() is None


def test_the_node_writes_only_a_producers_own_signal_table() -> None:
    with pytest.raises(ValueError, match="own SignalWeightsTS instance"):
        FixedWeights.from_signal_configuration(
            _configuration(STATED), output_table=SignalWeightsStorage
        )


def test_the_identity_is_the_configuration_not_the_table_or_namespace(signal_table) -> None:
    with _bound(_signal_table("elsewhere"), "a0000000-0000-4000-8000-0000000000dd") as other:
        elsewhere = _node(other, namespace="another-namespace")
    here = _node(signal_table)
    stated = object.__new__(FixedWeights)
    stated.signal_configuration = _configuration(STATED)

    assert here.signal_uid == elsewhere.signal_uid == compute_signal_uid(stated)
    assert here.update_hash != elsewhere.update_hash


def test_the_time_is_part_of_the_identity_and_must_be_timezone_aware(signal_table) -> None:
    def uid(signal_time_index: dt.datetime) -> str:
        return _node(signal_table, signal_time_index).signal_uid

    assert uid(STATED) != uid(STATED + dt.timedelta(days=1))
    with pytest.raises(ValidationError, match="signal_time_index must be timezone-aware"):
        _configuration(STATED.replace(tzinfo=None))
