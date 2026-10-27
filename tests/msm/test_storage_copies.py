"""Copying a time series between a core table and a provider instance (ADR 0047)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from msm import storage_copies
from msm.storage_copies import (
    TableSeriesMove,
    TimeIndexRowsCopyConfiguration,
    copy_time_index_rows,
    run_series_moves,
)

INDEX = ["time_index", "portfolio_identifier", "asset_identifier"]
DAY = [dt.datetime(2026, 1, day, tzinfo=dt.UTC) for day in (1, 2, 3)]


def _storage(name: str, index_names: list[str] = INDEX) -> type:
    return type(name, (), {"__index_names__": index_names, "__table__": SimpleNamespace(name=name)})


def _frame(rows: list[tuple[Any, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=[*INDEX, "weight"])
    return frame.set_index(INDEX)


class _Tables:
    """In-memory tables keyed by storage name; the copier appends to its output table."""

    def __init__(self, monkeypatch, **frames: pd.DataFrame) -> None:
        self.frames = dict(frames)
        self.runs: list[dict[str, Any]] = []
        self.fail = False
        tables = self

        class FakeCopy:
            def __init__(self, config, *, output_table):
                self.config, self.output_table = config, output_table

            def set_rows(self, rows):
                self.rows = rows
                return self

            def run(self, **kwargs):
                tables.runs.append({"target": self.output_table.__table__.name, "rows": len(self.rows), **kwargs})
                if tables.fail:
                    return True, None
                name = self.output_table.__table__.name
                tables.frames[name] = pd.concat([tables.frames[name], self.rows])
                return False, self.rows

        monkeypatch.setattr(storage_copies, "TimeIndexRowsCopy", FakeCopy)
        monkeypatch.setattr(
            storage_copies,
            "registered_time_index_meta_table",
            lambda storage: SimpleNamespace(uid=f"uid-{storage.__table__.name}", name=storage.__table__.name),
        )
        monkeypatch.setattr(storage_copies, "_read", self.read)

    def read(self, meta_table, key_column, keys, columns, deadline_seconds):
        frame = self.frames[meta_table.name]
        selected = frame[frame.index.get_level_values(key_column).isin(keys)]
        return selected[[]] if columns else selected


def test_copy_writes_only_missing_rows_and_fills_gaps(monkeypatch) -> None:
    core, instance = _storage("core"), _storage("instance")
    tables = _Tables(
        monkeypatch,
        core=_frame(
            [
                (DAY[0], "P1", "A", 0.5),
                (DAY[1], "P1", "A", 0.6),
                (DAY[1], "P1", "B", 0.4),
                (DAY[2], "P1", "A", 1.0),
                (DAY[0], "P2", "A", 1.0),
            ]
        ),
        # The instance already holds a later row: the earlier ones are a gap, not history to skip.
        instance=_frame([(DAY[2], "P1", "A", 1.0)]),
    )

    planned = copy_time_index_rows(core, instance, key_column="portfolio_identifier", keys=["P1"], dry_run=True)
    assert [(k.key, k.source_rows, k.target_rows, k.missing_rows) for k in planned.keys] == [("P1", 4, 1, 3)]
    assert tables.runs == [] and not planned.complete

    report = copy_time_index_rows(core, instance, key_column="portfolio_identifier", keys=["P1", "P1", ""])

    assert report.complete and report.copied_rows == 3
    assert [(k.key, k.source_rows, k.target_rows, k.missing_rows) for k in report.keys] == [("P1", 4, 4, 0)]
    assert tables.runs[0]["rows"] == 3 and tables.runs[0]["update_tree"] is False
    assert tables.runs[0]["override_update_stats"] is not None
    assert "P2" not in set(tables.frames["instance"].index.get_level_values("portfolio_identifier"))

    again = copy_time_index_rows(core, instance, key_column="portfolio_identifier", keys=["P1"])
    assert again.complete and again.copied_rows == 0 and len(tables.runs) == 1


def test_copy_refuses_mismatched_tables_and_reports_failed_writes(monkeypatch) -> None:
    core, instance = _storage("core"), _storage("instance")
    tables = _Tables(monkeypatch, core=_frame([(DAY[0], "P1", "A", 0.5)]), instance=_frame([]))

    with pytest.raises(ValueError, match="different index names"):
        copy_time_index_rows(_storage("other", ["time_index", "portfolio_identifier"]), instance, key_column="portfolio_identifier", keys=["P1"])
    with pytest.raises(ValueError, match="not an index level"):
        copy_time_index_rows(core, instance, key_column="signal_uid", keys=["S"])
    tables.fail = True
    with pytest.raises(RuntimeError, match="failed"):
        copy_time_index_rows(core, instance, key_column="portfolio_identifier", keys=["P1"])


def test_copy_identity_is_the_source_table_and_key_column() -> None:
    assert set(TimeIndexRowsCopyConfiguration.model_fields) >= {"source_table_uid", "key_column"}
    assert "keys" not in TimeIndexRowsCopyConfiguration.model_fields


def test_table_move_and_rollback_switch_writers_only_when_complete(monkeypatch) -> None:
    core, instance = _storage("core"), _storage("instance")
    tables = _Tables(
        monkeypatch,
        core=_frame([(DAY[0], "P1", "A", 0.5)]),
        instance=_frame([]),
    )
    events: list[str] = []
    move = TableSeriesMove(
        core,
        instance,
        "portfolio_identifier",
        ["P1"],
        label="curves",
        on_copied=lambda: events.append("copied"),
        on_rolled_back=lambda: events.append("rolled_back"),
    )

    assert run_series_moves([move], dry_run=True).results[0].status == "planned"
    moved = run_series_moves([move], dry_run=False)
    assert moved.succeeded and moved.results[0].status == "moved" and events == ["copied"]

    tables.frames["instance"] = pd.concat([tables.frames["instance"], _frame([(DAY[1], "P1", "A", 0.7)])])
    rolled = run_series_moves([move], rollback=True, dry_run=False)
    assert rolled.results[0].status == "rolled_back" and events == ["copied", "rolled_back"]
    assert len(tables.frames["core"]) == 2

    monkeypatch.setattr(
        storage_copies,
        "copy_time_index_rows",
        lambda *args, **kwargs: storage_copies.TimeIndexCopyReport(
            "core", "instance", "portfolio_identifier", (storage_copies.KeyCopy("P1", 2, 1, 1),), False
        ),
    )
    incomplete = run_series_moves([move], dry_run=False)
    assert incomplete.results[0].status == "incomplete" and not incomplete.succeeded
    assert events == ["copied", "rolled_back"]


def test_table_moves_forward_their_read_tuning(monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        storage_copies,
        "copy_time_index_rows",
        lambda source, target, **kwargs: seen.append(kwargs)
        or storage_copies.TimeIndexCopyReport("core", "instance", "k", (), True),
    )

    TableSeriesMove(_storage("core"), _storage("instance"), "k", ["a"], keys_per_read=3).run(
        rollback=False, dry_run=True
    )

    assert seen[0]["keys_per_read"] == 3 and seen[0]["deadline_seconds"] == 300.0


def test_run_series_moves_orders_moves_and_reports_failures() -> None:
    calls: list[tuple[str, bool]] = []

    class Move:
        def __init__(self, label: str, order: int, fail: bool = False):
            self.label, self.move_order, self.fail, self.kind = label, order, fail, "fake"

        def run(self, *, rollback, dry_run):
            calls.append((self.label, rollback))
            if self.fail:
                raise LookupError("not registered")
            return storage_copies.SeriesMoveResult("fake", self.label, status="moved")

    moves = [Move("portfolio", 1), Move("signal", 0), Move("broken", 0, fail=True)]

    report = run_series_moves(moves, dry_run=False)
    assert [label for label, _ in calls] == ["signal", "broken", "portfolio"]
    assert [result.status for result in report.results] == ["moved", "failed", "moved"]
    assert report.results[1].detail == "LookupError: not registered" and not report.succeeded

    calls.clear()
    run_series_moves(moves, rollback=True, dry_run=False)
    assert calls[0] == ("portfolio", True)
    with pytest.raises(LookupError):
        run_series_moves(moves, dry_run=False, stop_on_error=True)


def test_the_real_copier_keeps_one_identity_per_source_and_target() -> None:
    from metatables import TimeIndexMetaTable
    from msm.storage_copies import TimeIndexRowsCopy, registered_time_index_meta_table
    from msm_portfolios.time_index.contract_instances import configured_portfolio_weights_storage

    instance = configured_portfolio_weights_storage(
        instance_key="copytest", namespace="my-provider", storage_app="my_provider"
    )
    before = dict(vars(instance))
    instance._bind_meta_table(
        TimeIndexMetaTable.model_construct(
            uid="instance-uid",
            data_source_uid="00000000-0000-0000-0000-000000000001",
            identifier=instance.__metatable_identifier__,
        )
    )
    try:
        def copier(source_uid: str) -> TimeIndexRowsCopy:
            config = TimeIndexRowsCopyConfiguration(
                source_table_uid=source_uid, key_column="portfolio_identifier"
            )
            return TimeIndexRowsCopy(config, output_table=instance)

        first = copier("core-uid").set_rows(_frame([(DAY[0], "P1", "A", 0.5)]))
        assert first.update_hash == copier("core-uid").update_hash
        assert first.update_hash != copier("other-uid").update_hash
        assert len(first.update()) == 1 and first.dependencies() == {}
        assert registered_time_index_meta_table(instance).uid == "instance-uid"
    finally:
        for name in set(vars(instance)) - set(before):
            delattr(instance, name)
        for name, value in before.items():
            if vars(instance).get(name) is not value:
                setattr(instance, name, value)
