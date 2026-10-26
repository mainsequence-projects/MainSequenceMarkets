"""Move a portfolio's or a signal's series into a provider's instances, and back (ADR 0047).

A provider that starts writing a portfolio into its own contract instances
(``msm_portfolios.time_index.contract_instances``) first copies the history
already in the core Markets tables, because portfolio and signal history is not
recomputed, and then records the instances in the Markets portfolio catalog.
``PortfolioSeriesMove`` and ``SignalSeriesMove`` describe one such move;
``msm.storage_copies.run_series_moves`` runs a list of them (signals before
portfolios; portfolios first on a rollback).

One portfolio move:

1. copies, per key, the signal weights of the signals that move with it, then
   its rebalance state, weights, values and event ledger (``copy_time_index_rows``);
2. stops as ``incomplete`` if any key still lacks rows in the instance;
3. calls ``on_copied``, where the provider points its updaters at the instances;
4. binds the moved signals that are not the portfolio's current one
   (``PortfolioDatasets.register_signal``);
5. writes the catalog row last (``PortfolioDatasets.register``), which also binds
   the current signal when it moved with the portfolio.

A rollback copies the rows the instances gained back into the core tables,
removes the catalog row (``PortfolioDatasets.unregister``), clears the moved
signals' bindings (``unregister_signal``), then calls ``on_rolled_back``. The
instance rows stay. Calendar events are not copied: the engine rebuilds them
from the persisted calendar.

The operator needs ``data_viewer`` on the tables it reads, write access to the
tables it writes, and the write-policy resource ``portfolio-datasets`` for the
catalog calls; the Markets workload needs ``data_viewer`` on the instances for
``register`` to verify them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from typing import Any, ClassVar

from msm.storage_copies import (
    SeriesMoveResult,
    copy_time_index_rows,
    finish_move,
    registered_time_index_meta_table,
)
from msm_portfolios.time_index.contract_instances import (
    PORTFOLIO_EVENT_LEDGER_CONTRACT,
    PORTFOLIO_REBALANCE_STATE_CONTRACT,
    PORTFOLIO_WEIGHTS_CONTRACT,
    PORTFOLIOS_CONTRACT,
    SIGNAL_WEIGHTS_CONTRACT,
    portfolio_storage_contract,
)

# (slot, contract) in copy order, after the signal weights: rebalance state
# before the weights and values computed from it.
_PORTFOLIO_SLOTS = (
    ("rebalance_state", PORTFOLIO_REBALANCE_STATE_CONTRACT),
    ("weights", PORTFOLIO_WEIGHTS_CONTRACT),
    ("values", PORTFOLIOS_CONTRACT),
    ("event_ledger", PORTFOLIO_EVENT_LEDGER_CONTRACT),
)


@dataclass(frozen=True)
class PortfolioSeriesTables:
    """The tables of one portfolio's series: a provider's instances, or the core tables.

    A slot left ``None`` is not copied.
    """

    values: type[Any] | None = None
    weights: type[Any] | None = None
    rebalance_state: type[Any] | None = None
    signal_weights: type[Any] | None = None
    event_ledger: type[Any] | None = None

    @classmethod
    def core(cls) -> PortfolioSeriesTables:
        """The Markets core storages of every slot."""

        return cls(
            values=portfolio_storage_contract(PORTFOLIOS_CONTRACT).core_storage,
            weights=portfolio_storage_contract(PORTFOLIO_WEIGHTS_CONTRACT).core_storage,
            rebalance_state=portfolio_storage_contract(
                PORTFOLIO_REBALANCE_STATE_CONTRACT
            ).core_storage,
            signal_weights=portfolio_storage_contract(SIGNAL_WEIGHTS_CONTRACT).core_storage,
            event_ledger=portfolio_storage_contract(PORTFOLIO_EVENT_LEDGER_CONTRACT).core_storage,
        )

    def slots(self) -> dict[str, type[Any]]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if getattr(self, item.name) is not None
        }


@dataclass
class SignalSeriesMove:
    """Move the weights of ``signal_uids`` into a provider's signal weights instance, or back.

    A move binds each signal to the instance (``register_signal``) once its rows
    are complete; a rollback clears each binding (``unregister_signal``).
    """

    move_order: ClassVar[int] = 0
    kind: ClassVar[str] = "signal"

    signal_uids: Sequence[str]
    instance: type[Any]
    label: str = ""
    register: bool = True
    on_copied: Callable[[], Any] | None = None
    on_rolled_back: Callable[[], Any] | None = None
    core: type[Any] | None = None

    def run(self, *, rollback: bool, dry_run: bool) -> SeriesMoveResult:
        signal_uids = _unique(self.signal_uids)
        core = self.core or portfolio_storage_contract(SIGNAL_WEIGHTS_CONTRACT).core_storage
        result = SeriesMoveResult(self.kind, self.label or ", ".join(signal_uids))
        source, target = (self.instance, core) if rollback else (core, self.instance)
        result.copies.append(
            copy_time_index_rows(
                source, target, key_column="signal_uid", keys=signal_uids, dry_run=dry_run
            )
        )

        def catalog() -> list[Any]:
            if not self.register:
                return []
            if rollback:
                return _unbind_signals(signal_uids)
            return _bind_signals(signal_uids, self.instance)

        return finish_move(
            result,
            rollback=rollback,
            dry_run=dry_run,
            after_copy=self.on_rolled_back if rollback else self.on_copied,
            catalog=catalog,
            catalog_first=rollback,
        )


@dataclass
class PortfolioSeriesMove:
    """Move one portfolio's series into a provider's instances, or back.

    ``portfolio_identifier`` keys the portfolio tables. ``portfolio_uid`` names
    its Markets Portfolio, whose catalog row is written on a move and removed on
    a rollback; without it no catalog call is made. ``signal_uids`` are the
    signals that move with the portfolio (for example every weekly signal of a
    producer whose signal uid changes each run); ``with_current_signal`` adds the
    Portfolio row's current signal. A signal that another ``SignalSeriesMove``
    moves stays out of ``signal_uids``.
    """

    move_order: ClassVar[int] = 1
    kind: ClassVar[str] = "portfolio"

    portfolio_identifier: str
    instances: PortfolioSeriesTables
    portfolio_uid: uuid.UUID | str | None = None
    signal_uids: Sequence[str] = ()
    with_current_signal: bool = False
    label: str = ""
    register: bool = True
    on_copied: Callable[[], Any] | None = None
    on_rolled_back: Callable[[], Any] | None = None
    core: PortfolioSeriesTables | None = None

    def run(self, *, rollback: bool, dry_run: bool) -> SeriesMoveResult:
        core = self.core or PortfolioSeriesTables.core()
        current_signal = self._current_signal_uid()
        with_current = [current_signal] if self.with_current_signal and current_signal else []
        signal_uids = _unique([*self.signal_uids, *with_current])
        result = SeriesMoveResult(self.kind, self.label or self.portfolio_identifier)
        instances = self.instances.slots()
        core_tables = core.slots()
        copies: list[tuple[type[Any], type[Any], str, list[str]]] = []
        if signal_uids:
            if "signal_weights" not in instances:
                raise ValueError("signal_uids need a signal_weights instance.")
            signal_tables = (core_tables["signal_weights"], instances["signal_weights"])
            copies.append((*signal_tables, "signal_uid", signal_uids))
        for slot, contract in _PORTFOLIO_SLOTS:
            if slot in instances:
                copies.append(
                    (
                        core_tables[slot],
                        instances[slot],
                        portfolio_storage_contract(contract).dimension,
                        [self.portfolio_identifier],
                    )
                )
        if rollback:
            copies = [(target, source, column, keys) for source, target, column, keys in copies]
        for source, target, column, keys in copies:
            result.copies.append(
                copy_time_index_rows(source, target, key_column=column, keys=keys, dry_run=dry_run)
            )

        def catalog() -> list[Any]:
            if not self.register:
                return []
            if rollback:
                calls: list[Any] = []
                if self.portfolio_uid is not None:
                    calls.append(_unregister_portfolio(self.portfolio_uid))
                return [*calls, *_unbind_signals(signal_uids)]
            calls = _bind_signals(
                [uid for uid in signal_uids if uid != current_signal],
                instances.get("signal_weights"),
            )
            if self.portfolio_uid is not None and "values" in instances:
                calls.append(
                    _register_portfolio(
                        self.portfolio_uid,
                        values=instances["values"],
                        weights=instances.get("weights"),
                        signal_weights=(
                            instances.get("signal_weights")
                            if current_signal and current_signal in signal_uids
                            else None
                        ),
                    )
                )
            return calls

        return finish_move(
            result,
            rollback=rollback,
            dry_run=dry_run,
            after_copy=self.on_rolled_back if rollback else self.on_copied,
            catalog=catalog,
            catalog_first=rollback,
        )

    def _current_signal_uid(self) -> str | None:
        if self.portfolio_uid is None:
            return None
        from msm.api.portfolios import Portfolio

        portfolio = Portfolio.get_by_uid(self.portfolio_uid)
        if portfolio is None:
            raise LookupError(f"Portfolio {self.portfolio_uid!s} was not found")
        signal_uid = getattr(portfolio, "signal_uid", None)
        return str(signal_uid) if signal_uid else None


def _bind_signals(signal_uids: Sequence[str], instance: type[Any] | None) -> list[Any]:
    if not signal_uids:
        return []
    if instance is None:
        raise ValueError("Binding signals needs a signal_weights instance.")
    from msm_portfolios.api.datasets import PortfolioDatasets

    table_uid = str(registered_time_index_meta_table(instance).uid)
    return [
        PortfolioDatasets.register_signal(
            {"signal_uid": signal_uid, "signal_meta_table_uid": table_uid}
        )
        for signal_uid in signal_uids
    ]


def _unbind_signals(signal_uids: Sequence[str]) -> list[Any]:
    from msm_portfolios.api.datasets import PortfolioDatasets

    return [PortfolioDatasets.unregister_signal(signal_uid=uid) for uid in signal_uids]


def _register_portfolio(
    portfolio_uid: uuid.UUID | str,
    *,
    values: type[Any],
    weights: type[Any] | None,
    signal_weights: type[Any] | None,
) -> Any:
    from msm_portfolios.api.datasets import PortfolioDatasets

    def table_uid(storage: type[Any] | None) -> str | None:
        return None if storage is None else str(registered_time_index_meta_table(storage).uid)

    return PortfolioDatasets.register(
        {
            "portfolio_uid": str(portfolio_uid),
            "values_meta_table_uid": table_uid(values),
            "weights_meta_table_uid": table_uid(weights),
            "signal_meta_table_uid": table_uid(signal_weights),
        },
        reconcile=True,
    )


def _unregister_portfolio(portfolio_uid: uuid.UUID | str) -> Any:
    from msm_portfolios.api.datasets import PortfolioDatasets

    return PortfolioDatasets.unregister(portfolio_uid=portfolio_uid)


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


__all__ = [
    "PortfolioSeriesMove",
    "PortfolioSeriesTables",
    "SignalSeriesMove",
]
