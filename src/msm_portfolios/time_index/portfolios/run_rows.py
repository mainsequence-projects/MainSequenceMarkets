"""The rows one portfolio run has read, for the nodes after it (issue #139).

``run_portfolios`` runs inside ``run_rows()``. In it a node that read a table's rows keeps
them for the nodes of the same run that need the same rows:

- the rebalance keeps the valuation source's rows it read (``ValuationRows``), from the
  ledger's initial state on, and the ledger books with them;
- the ledger keeps its rows (the stored ledger and the tail it wrote) and the rebalance
  state it read, and the weights and values project them.

A node that finds nothing kept reads the table itself, as outside a run. Nothing outlives
the block, so a node run again later reads again.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from msm.settings import ASSET_IDENTIFIER_DIMENSION


@dataclass(frozen=True)
class ValuationRows:
    """The valuation source's rows a rebalance read: of ``assets`` (every asset when
    ``None``), from ``start`` on, to ``end`` (to the source's last row when ``None``)."""

    source: Any
    start: pd.Timestamp
    end: pd.Timestamp | None
    assets: frozenset[str] | None
    frame: pd.DataFrame

    def rows(
        self, source: Any, *, start: Any, end: Any, assets: Iterable[str] = ()
    ) -> pd.DataFrame | None:
        """The rows of ``assets`` from ``start`` to ``end``, both included, as a read of
        ``source`` would answer them; ``None`` when this read does not hold them all."""

        wanted = [str(asset) for asset in assets]
        low, high = window_bound(start), window_bound(end)
        if source is not self.source or low < self.start:
            return None
        if self.end is not None and high > self.end:
            return None
        if self.assets is not None and not set(wanted) <= self.assets:
            return None
        return rows_between(self.frame, start=start, end=end, assets=wanted)


@dataclass
class _RunRows:
    valuations: dict[str, ValuationRows] = field(default_factory=dict)
    ledgers: dict[str, pd.DataFrame] = field(default_factory=dict)
    rebalance_states: dict[str, pd.DataFrame] = field(default_factory=dict)


_rows: ContextVar[_RunRows | None] = ContextVar("msm_portfolios_run_rows", default=None)


@contextmanager
def run_rows() -> Iterator[None]:
    """Keep the rows a portfolio run reads for its later nodes until the block ends.

    A block inside another shares its rows.
    """

    if _rows.get() is not None:
        yield
        return
    token = _rows.set(_RunRows())
    try:
        yield
    finally:
        _rows.reset(token)


def held_rows() -> _RunRows | None:
    """The rows kept by the ``run_rows`` block in force, or ``None`` outside one."""

    return _rows.get()


def window_bound(value: Any) -> pd.Timestamp:
    """``value`` as MetaTables compares a window's bound: in UTC, to the microsecond.

    The client sends a bound as seconds and the API reads them back to the microsecond, so
    an incremental window that starts 1 ns after its last row includes that row.
    """

    timestamp = pd.Timestamp(value)
    timestamp = (
        timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    )
    return timestamp.round("us")


def rows_between(
    frame: pd.DataFrame | None, *, start: Any, end: Any, assets: Iterable[str] = ()
) -> pd.DataFrame:
    """The rows of ``frame`` from ``start`` to ``end``, both included, as a window read
    compares them (``window_bound``); of ``assets`` when any are given."""

    if frame is None:
        return pd.DataFrame()
    if frame.empty:
        return frame
    names = [name for name in frame.index.names if name is not None]

    def values(name: str) -> pd.Index:
        if name in names:
            return frame.index.get_level_values(name)
        return pd.Index(frame[name])

    times = pd.to_datetime(values("time_index"), utc=True)
    keep = np.ones(len(frame), dtype=bool)
    if start is not None:
        keep &= times >= window_bound(start)
    if end is not None:
        keep &= times <= window_bound(end)
    wanted = [str(asset) for asset in assets]
    if wanted:
        keep &= values(ASSET_IDENTIFIER_DIMENSION).astype(str).isin(wanted)
    return frame[keep]


__all__ = ["ValuationRows", "held_rows", "rows_between", "run_rows", "window_bound"]
