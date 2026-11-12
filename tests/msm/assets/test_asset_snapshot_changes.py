"""Asset-snapshot publishes write only rows that change a snapshot (MainSequenceMarkets#62).

``changed_asset_snapshots`` runs its lookup on a migrated SQLite DataSource through
MetaTables' own SQLite backend, as ``test_sqlite_snapshot_writes`` does. Each row is
compared with the snapshot in effect at its own ``time_index``.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from msm.time_index.assets import snapshots as snapshot_module
from msm.time_index.assets.snapshots import changed_asset_snapshots
from tests.msm.repositories.test_sqlite_snapshot_writes import _asset, _insert, make_sqlite_markets

T1 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
T3 = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)


@pytest.fixture
def markets(tmp_path, monkeypatch):
    markets = make_sqlite_markets(tmp_path, monkeypatch)
    for identifier in ("A", "B"):
        _asset(markets.engine, identifier)
    return markets


def _store(markets, time_index, asset_identifier="A", **values) -> None:
    _insert(
        markets.engine,
        "ms_markets__assetsnapshotsts",
        time_index=time_index,
        asset_identifier=asset_identifier,
        **{"name": None, "ticker": None, "exchange_code": None, "asset_ticker_group_id": None, **values},
    )


def _row(time_index, asset_identifier="A", **values) -> dict:
    return {"time_index": time_index, "asset_identifier": asset_identifier, **values}


def _changed(markets, rows):
    return changed_asset_snapshots(rows, repository_context=markets.context)


def test_a_row_equal_to_the_latest_snapshot_is_skipped(markets) -> None:
    _store(markets, T1, name="Acme", ticker="ACME", exchange_code="US", asset_ticker_group_id="G")
    unchanged = _row(T2, name="Acme", ticker="ACME", exchange_code="US", asset_ticker_group_id="G")
    renamed = _row(T2, "B", name="Beta")

    assert _changed(markets, [unchanged, renamed]) == [renamed]


@pytest.mark.parametrize("column", ["name", "ticker", "exchange_code", "asset_ticker_group_id"])
def test_every_value_column_is_compared(markets, column) -> None:
    stored = {"name": "Acme", "ticker": "ACME", "exchange_code": "US", "asset_ticker_group_id": "G"}
    _store(markets, T1, **stored)
    row = _row(T2, **{**stored, column: "changed"})

    assert _changed(markets, [row]) == [row]


def test_none_and_an_empty_string_are_equal(markets) -> None:
    _store(markets, T1, name="Acme")

    assert _changed(markets, [_row(T2, name="Acme", ticker=None), _row(T3, name="Acme", ticker="")]) == []


def test_a_backdated_row_is_compared_with_the_snapshot_in_effect_at_its_date(markets) -> None:
    _store(markets, T1, name="Old")
    _store(markets, T3, name="New")
    # The latest snapshot is "New", but "Old" was in effect at T2: this is a change.
    backdated_change = _row(T2, name="New")
    backdated_repeat = _row(T2, "A", name="Old")

    assert _changed(markets, [backdated_change]) == [backdated_change]
    assert _changed(markets, [backdated_repeat]) == []


def test_a_row_before_any_stored_snapshot_is_written(markets) -> None:
    _store(markets, T2, name="Acme")
    first = _row(T1, name="Acme")

    assert _changed(markets, [first]) == [first]


def test_rows_of_one_asset_are_compared_in_time_order(markets) -> None:
    latest = _row(T3, name="Y")
    earliest = _row(T1, name="X")
    repeat = _row(T2, name="X")

    # Written rows come back in input order.
    assert _changed(markets, [latest, earliest, repeat]) == [latest, earliest]


def test_a_stored_snapshot_between_two_rows_is_in_effect_for_the_later_one(markets) -> None:
    _store(markets, T2, name="Y")
    earlier = _row(T1, name="X")
    later = _row(T3, name="Y")

    assert _changed(markets, [earlier, later]) == [earlier]


def test_a_stored_key_repeated_with_the_same_values_is_skipped(markets) -> None:
    _store(markets, T1, name="Acme", ticker="ACME")

    assert _changed(markets, [_row(T1, name="Acme", ticker="ACME")]) == []


def test_a_stored_key_repeated_with_other_values_is_refused(markets) -> None:
    _store(markets, T1, name="Acme", ticker="ACME")

    with pytest.raises(ValueError, match=r"already exist with different values .*\(2026-11-01T00:00:00\+00:00, A\)"):
        _changed(markets, [_row(T1, name="Acme", ticker="ACME2")])


def test_a_key_repeated_in_the_batch_is_written_once(markets) -> None:
    row = _row(T1, name="Acme")

    assert _changed(markets, [row, dict(row)]) == [row]
    with pytest.raises(ValueError, match="repeat .* with different values"):
        _changed(markets, [row, _row(T1, name="Other")])


def test_rows_are_looked_up_in_batches(markets, monkeypatch) -> None:
    monkeypatch.setattr(snapshot_module, "_SNAPSHOT_LOOKUP_BATCH", 2)
    _store(markets, T1, name="A1")
    _store(markets, T1, "B", name="B1")
    rows = [_row(T2, name="A1"), _row(T2, "B", name="B1"), _row(T3, name="A3"), _row(T3, "B", name="B1")]

    assert _changed(markets, rows) == [rows[2]]
    assert sum("snapshot_input" in sql for sql in markets.statements) == 2


def test_publish_writes_only_changed_rows_and_counts_the_rest(markets, monkeypatch) -> None:
    from msm.api.assets import AssetSnapshotPublication, AssetSnapshots

    _store(markets, T1, name="Acme")
    runs = []

    class RecordingUpdater:
        def set_snapshots(self, rows):
            runs.append(rows)
            return self

        def run(self):
            return False, None

    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime", lambda **kwargs: SimpleNamespace(context=markets.context)
    )
    monkeypatch.setattr("msm.time_index.assets.AssetSnapshot", RecordingUpdater)

    unchanged = AssetSnapshots.publish([_row(T2, name="Acme"), _row(T2, name="Acme")])
    changed = AssetSnapshots.publish([_row(T2, name="Acme"), _row(T2, "B", name="Beta")])

    assert unchanged == AssetSnapshotPublication(written=0, skipped=2)
    assert changed == AssetSnapshotPublication(written=1, skipped=1)
    assert runs == [[_row(T2, "B", name="Beta")]]
