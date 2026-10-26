"""Moving a portfolio's and a signal's series into provider instances and back (ADR 0047)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from msm.storage_copies import KeyCopy, TimeIndexCopyReport, run_series_moves
from msm_portfolios.services import series_moves
from msm_portfolios.services.series_moves import (
    PortfolioSeriesMove,
    PortfolioSeriesTables,
    SignalSeriesMove,
)

PORTFOLIO_UID = uuid.uuid4()


def _storage(name: str) -> type:
    return type(name, (), {"__table__": SimpleNamespace(name=name)})


CORE = PortfolioSeriesTables(
    values=_storage("core_values"),
    weights=_storage("core_weights"),
    rebalance_state=_storage("core_rebalance"),
    signal_weights=_storage("core_signals"),
    event_ledger=_storage("core_ledger"),
)
INSTANCES = PortfolioSeriesTables(
    values=_storage("my_values"),
    weights=_storage("my_weights"),
    rebalance_state=_storage("my_rebalance"),
    signal_weights=_storage("my_signals"),
)


class _Markets:
    """Record copies and catalog calls in the order they happen."""

    def __init__(self, monkeypatch, *, current_signal: str | None = "current-signal") -> None:
        self.events: list[tuple[Any, ...]] = []
        self.missing: dict[str, int] = {}
        from msm.api.portfolios import Portfolio
        from msm_portfolios.api.datasets import PortfolioDatasets

        def copy(source, target, *, key_column, keys, dry_run):
            self.events.append(("copy", source.__table__.name, target.__table__.name, key_column, list(keys)))
            missing = self.missing.get(target.__table__.name, 0)
            return TimeIndexCopyReport(
                source.__table__.name,
                target.__table__.name,
                key_column,
                tuple(KeyCopy(key, 3, 3 - missing, missing) for key in keys),
                dry_run,
            )

        def record(name):
            return classmethod(lambda cls, *args, **kwargs: self.events.append((name, args, kwargs)) or name)

        monkeypatch.setattr(series_moves, "copy_time_index_rows", copy)
        monkeypatch.setattr(
            series_moves,
            "registered_time_index_meta_table",
            lambda storage: SimpleNamespace(uid=f"uid-{storage.__table__.name}"),
        )
        for name in ("register", "register_signal", "unregister", "unregister_signal"):
            monkeypatch.setattr(PortfolioDatasets, name, record(name))
        monkeypatch.setattr(
            Portfolio,
            "get_by_uid",
            classmethod(
                lambda cls, uid: self.events.append(("portfolio", str(uid)))
                or SimpleNamespace(uid=uid, signal_uid=current_signal)
            ),
        )

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events if event[0] != "portfolio"]


def _move(**kwargs: Any) -> PortfolioSeriesMove:
    return PortfolioSeriesMove(
        "growth",
        INSTANCES,
        core=CORE,
        **{"portfolio_uid": PORTFOLIO_UID, **kwargs},
    )


def test_portfolio_move_copies_in_order_then_switches_then_catalogs_last(monkeypatch) -> None:
    markets = _Markets(monkeypatch)

    def switched():
        markets.events.append(("switched",))

    result = _move(signal_uids=["last-week"], with_current_signal=True, on_copied=switched).run(
        rollback=False, dry_run=False
    )

    assert result.status == "moved"
    copies = [event[1:] for event in markets.events if event[0] == "copy"]
    assert copies == [
        ("core_signals", "my_signals", "signal_uid", ["last-week", "current-signal"]),
        ("core_rebalance", "my_rebalance", "portfolio_identifier", ["growth"]),
        ("core_weights", "my_weights", "portfolio_identifier", ["growth"]),
        ("core_values", "my_values", "portfolio_identifier", ["growth"]),
    ]
    assert markets.kinds()[-3:] == ["switched", "register_signal", "register"]
    register_signal = next(event for event in markets.events if event[0] == "register_signal")
    assert register_signal[1][0] == {"signal_uid": "last-week", "signal_meta_table_uid": "uid-my_signals"}
    register = markets.events[-1]
    assert register[1][0] == {
        "portfolio_uid": str(PORTFOLIO_UID),
        "values_meta_table_uid": "uid-my_values",
        "weights_meta_table_uid": "uid-my_weights",
        "signal_meta_table_uid": "uid-my_signals",
    }
    assert register[2] == {"reconcile": True}
    assert result.catalog == ["register_signal", "register"]


def test_a_signal_moved_separately_is_not_named_by_the_catalog_row(monkeypatch) -> None:
    markets = _Markets(monkeypatch)

    _move().run(rollback=False, dry_run=False)

    assert [event[3] for event in markets.events if event[0] == "copy"] == ["portfolio_identifier"] * 3
    assert markets.events[-1][1][0]["signal_meta_table_uid"] is None
    assert "register_signal" not in markets.kinds()


def test_portfolio_rollback_copies_back_then_unregisters_then_switches(monkeypatch) -> None:
    markets = _Markets(monkeypatch)

    result = _move(
        signal_uids=["last-week"],
        with_current_signal=True,
        on_rolled_back=lambda: markets.events.append(("switched_back",)),
    ).run(rollback=True, dry_run=False)

    assert result.status == "rolled_back"
    copies = [event[1:3] for event in markets.events if event[0] == "copy"]
    assert copies[0] == ("my_signals", "core_signals")
    assert all(target.startswith("core_") for _source, target in copies)
    assert markets.kinds()[-4:] == ["unregister", "unregister_signal", "unregister_signal", "switched_back"]
    assert markets.events[-4][2] == {"portfolio_uid": PORTFOLIO_UID}


def test_an_incomplete_copy_changes_nothing_in_markets(monkeypatch) -> None:
    markets = _Markets(monkeypatch)
    markets.missing["my_weights"] = 1

    result = _move(on_copied=lambda: markets.events.append(("switched",))).run(rollback=False, dry_run=False)

    assert result.status == "incomplete"
    assert set(markets.kinds()) == {"copy"}


def test_dry_run_and_a_portfolio_without_a_markets_row(monkeypatch) -> None:
    markets = _Markets(monkeypatch)

    assert _move().run(rollback=False, dry_run=True).status == "planned"
    assert set(markets.kinds()) == {"copy"}

    markets.events.clear()
    moved = PortfolioSeriesMove(
        "unlisted", PortfolioSeriesTables(values=_storage("my_values")), core=CORE
    ).run(rollback=False, dry_run=False)
    assert moved.status == "moved" and markets.kinds() == ["copy"]
    assert ("portfolio", str(PORTFOLIO_UID)) not in markets.events

    with pytest.raises(ValueError, match="signal_weights instance"):
        PortfolioSeriesMove(
            "unlisted", PortfolioSeriesTables(values=_storage("my_values")), core=CORE, signal_uids=["s"]
        ).run(rollback=False, dry_run=True)


def test_signal_moves_bind_and_unbind_and_run_before_portfolios(monkeypatch) -> None:
    markets = _Markets(monkeypatch)
    signal_move = SignalSeriesMove(["s1", "s2", "s1"], _storage("my_signals"), core=_storage("core_signals"))

    report = run_series_moves([_move(), signal_move], dry_run=False)

    assert [result.kind for result in report.results] == ["signal", "portfolio"]
    assert markets.events[0][1:] == ("core_signals", "my_signals", "signal_uid", ["s1", "s2"])
    bound = [event[1][0]["signal_uid"] for event in markets.events if event[0] == "register_signal"]
    assert bound == ["s1", "s2"] and report.succeeded

    markets.events.clear()
    rolled = run_series_moves([_move(), signal_move], rollback=True, dry_run=False)
    assert [result.kind for result in rolled.results] == ["portfolio", "signal"]
    unbound = [event[2]["signal_uid"] for event in markets.events if event[0] == "unregister_signal"]
    assert unbound == ["s1", "s2"]
