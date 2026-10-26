"""Move a time series between a Markets core table and a provider instance (ADR 0047).

A provider that moves a series into its own instance of a Markets storage
(``msm.storage_instances``, or the portfolio contract instances) copies the rows it already produced into the core table, because that history
is not recomputed, and copies the rows the instance gained back to roll the move
back. ``copy_time_index_rows`` is that copy: it reads both tables through
MetaTables, writes only the rows of the selected keys that the target lacks,
through ``TimeIndexRowsCopy`` bound to the target, and counts both sides again,
so a copy that stopped part-way, or a second pass after more rows arrived, fills
exactly the gaps.

``TableSeriesMove`` moves the rows of some keys of one table and rolls them back;
``run_series_moves`` runs a list of moves (``msm series move|rollback`` on the
command line). The portfolio and signal moves, which also update the Markets
portfolio catalog, are ``PortfolioSeriesMove`` and ``SignalSeriesMove`` in the
portfolios package's ``services.series_moves``.

The person or Job that runs a copy needs read access to the source table and
write access to the target table.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import pandas as pd

from metatables import BaseConfiguration, TimeIndexTableUpdater

DEFAULT_KEYS_PER_READ = 50
DEFAULT_READ_DEADLINE_SECONDS = 300.0

MoveStatus = Literal["planned", "moved", "rolled_back", "incomplete", "failed"]


@dataclass(frozen=True)
class KeyCopy:
    """One key of one copy: source rows, target rows and source rows the target still lacks."""

    key: str
    source_rows: int
    target_rows: int
    missing_rows: int
    copied_rows: int = 0

    @property
    def complete(self) -> bool:
        return self.missing_rows == 0

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_rows": self.source_rows,
            "target_rows": self.target_rows,
            "missing_rows": self.missing_rows,
            "copied_rows": self.copied_rows,
            "complete": self.complete,
        }


@dataclass(frozen=True)
class TimeIndexCopyReport:
    """The keys of one copy from ``source_table`` into ``target_table``."""

    source_table: str
    target_table: str
    key_column: str
    keys: tuple[KeyCopy, ...]
    dry_run: bool

    @property
    def complete(self) -> bool:
        return all(key.complete for key in self.keys)

    @property
    def copied_rows(self) -> int:
        return sum(key.copied_rows for key in self.keys)

    def summary(self) -> dict[str, Any]:
        return {
            "source_table": self.source_table,
            "target_table": self.target_table,
            "key_column": self.key_column,
            "dry_run": self.dry_run,
            "complete": self.complete,
            "copied_rows": self.copied_rows,
            "keys": [key.summary() for key in self.keys],
        }


class TimeIndexRowsCopyConfiguration(BaseConfiguration):
    """The source table and key column of a copy; the rows are runtime state."""

    source_table_uid: str
    key_column: str


class TimeIndexRowsCopy(TimeIndexTableUpdater):
    """Write the rows given with ``set_rows`` into ``output_table`` unchanged.

    Its identity is the source table and key column, so every copy from one
    source into one target shares one update record. ``copy_time_index_rows``
    runs it with empty update statistics, so rows older than the target's latest
    observation are written too: those are the gaps a second pass fills.
    """

    def __init__(
        self,
        config: TimeIndexRowsCopyConfiguration,
        *,
        output_table: type[Any],
        hash_namespace: str | None = None,
    ) -> None:
        super().__init__(config=config, output_table=output_table, hash_namespace=hash_namespace)
        self._rows = pd.DataFrame()

    def set_rows(self, rows: pd.DataFrame) -> TimeIndexRowsCopy:
        """Rows indexed by the target's index names, as ``get_df_between_dates`` returns them."""

        self._rows = rows
        return self

    def dependencies(self) -> dict[str, Any]:
        return {}

    def update(self) -> pd.DataFrame:
        return self._rows


def copy_time_index_rows(
    source: type[Any],
    target: type[Any],
    *,
    key_column: str,
    keys: Iterable[str],
    dry_run: bool = False,
    keys_per_read: int = DEFAULT_KEYS_PER_READ,
    deadline_seconds: float = DEFAULT_READ_DEADLINE_SECONDS,
) -> TimeIndexCopyReport:
    """Copy the rows of ``keys`` that ``target`` lacks from ``source``, then count both sides.

    ``source`` and ``target`` are time-index storage classes of one contract
    (same index names and columns), for example a core Markets storage and a
    provider instance of it; both must be registered MetaTables. A row is
    identified by the full index (``time_index``, ``key_column`` and any other
    index level), so the copy never overwrites a row the target already holds.
    ``dry_run`` only counts.
    """

    from metatables import UpdateStatistics

    if keys_per_read <= 0:
        raise ValueError("keys_per_read must be positive.")
    wanted = list(dict.fromkeys(str(key) for key in keys if str(key or "").strip()))
    source_table = registered_time_index_meta_table(source)
    target_table = registered_time_index_meta_table(target)
    index_names = list(target.__index_names__)
    if key_column not in index_names:
        raise ValueError(f"{key_column!r} is not an index level of {target.__table__.name}.")
    if list(source.__index_names__) != index_names:
        raise ValueError(
            f"{source.__table__.name} and {target.__table__.name} have different index names."
        )

    results: list[KeyCopy] = []
    for start in range(0, len(wanted), keys_per_read):
        batch = wanted[start : start + keys_per_read]
        rows = _read(source_table, key_column, batch, None, deadline_seconds)
        held = _read(target_table, key_column, batch, index_names, deadline_seconds).index
        missing = rows.loc[~rows.index.isin(held)] if len(rows) else rows
        copied = _rows_per_key(missing, key_column)
        if not dry_run and len(missing):
            copier = TimeIndexRowsCopy(
                TimeIndexRowsCopyConfiguration(
                    source_table_uid=str(source_table.uid), key_column=key_column
                ),
                output_table=target,
            ).set_rows(missing)
            outcome = copier.run(
                update_tree=False, override_update_stats=UpdateStatistics.return_empty()
            )
            if isinstance(outcome, tuple) and outcome and outcome[0]:
                raise RuntimeError(
                    f"Copying {key_column} rows from {source.__table__.name} into "
                    f"{target.__table__.name} failed."
                )
            held = _read(target_table, key_column, batch, index_names, deadline_seconds).index
        still_missing = rows.loc[~rows.index.isin(held)] if len(rows) else rows
        source_counts = _rows_per_key(rows, key_column)
        target_counts = _index_rows_per_key(held, key_column)
        missing_counts = _rows_per_key(still_missing, key_column)
        for key in batch:
            results.append(
                KeyCopy(
                    key=key,
                    source_rows=source_counts.get(key, 0),
                    target_rows=target_counts.get(key, 0),
                    missing_rows=missing_counts.get(key, 0),
                    copied_rows=0 if dry_run else copied.get(key, 0),
                )
            )
    return TimeIndexCopyReport(
        source_table=source.__table__.name,
        target_table=target.__table__.name,
        key_column=key_column,
        keys=tuple(results),
        dry_run=dry_run,
    )


def registered_time_index_meta_table(storage: type[Any]) -> Any:
    """The registered ``TimeIndexMetaTable`` of a storage class; raises when it is not migrated."""

    bound = getattr(storage, "get_time_index_meta_table", lambda: None)()
    if bound is not None:
        return bound
    from metatables import TimeIndexMetaTable

    name = storage.__table__.name
    matches = list(TimeIndexMetaTable.filter(physical_table_name__in=[name], timeout=60) or [])
    if len(matches) != 1:
        raise LookupError(
            f"{name} is {'not' if not matches else 'ambiguously'} registered in this "
            "Environment's MetaTables catalog; run the migration that creates it first."
        )
    return matches[0]


def _read(
    meta_table: Any,
    key_column: str,
    keys: Sequence[str],
    columns: Sequence[str] | None,
    deadline_seconds: float,
) -> pd.DataFrame:
    from metatables import TimeIndexTableRef

    frame = TimeIndexTableRef.from_meta_table(meta_table).get_df_between_dates(
        dimension_filters={key_column: list(keys)},
        columns=list(columns) if columns else None,
        deadline_seconds=deadline_seconds,
    )
    return pd.DataFrame() if frame is None else frame


def _rows_per_key(frame: pd.DataFrame, key_column: str) -> dict[str, int]:
    if frame is None or not len(frame):
        return {}
    return _index_rows_per_key(frame.index, key_column)


def _index_rows_per_key(index: pd.Index, key_column: str) -> dict[str, int]:
    if not len(index):
        return {}
    counts = index.get_level_values(key_column).astype(str).value_counts()
    return {str(key): int(count) for key, count in counts.items()}


@dataclass
class SeriesMoveResult:
    """What one move or rollback did: its copies, catalog calls and final status."""

    kind: str
    label: str
    copies: list[TimeIndexCopyReport] = field(default_factory=list)
    catalog: list[Any] = field(default_factory=list)
    status: MoveStatus = "planned"
    detail: str = ""

    @property
    def complete(self) -> bool:
        return all(copy.complete for copy in self.copies)

    def summary(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "complete": self.complete,
            "detail": self.detail,
            "copies": [copy.summary() for copy in self.copies],
            "catalog": [_json_state(item) for item in self.catalog],
        }


@dataclass
class SeriesMoveReport:
    """Every move of one ``run_series_moves`` call."""

    rollback: bool
    dry_run: bool
    results: list[SeriesMoveResult] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        done = "planned" if self.dry_run else ("rolled_back" if self.rollback else "moved")
        return all(result.status == done for result in self.results)

    def summary(self) -> dict[str, Any]:
        return {
            "rollback": self.rollback,
            "dry_run": self.dry_run,
            "succeeded": self.succeeded,
            "results": [result.summary() for result in self.results],
        }


@dataclass
class TableSeriesMove:
    """Move the rows of ``keys`` from a core table into a provider instance, or roll them back.

    ``on_copied`` runs once every key is complete; the provider points its
    updaters at the instance there. On a rollback the rows
    the instance gained are copied back and ``on_rolled_back`` points the
    updaters at the core table again. Series bound elsewhere (a pricing
    market-data set binding, an Index dataset catalog row) are re-bound by the
    provider in those callbacks.
    """

    move_order: ClassVar[int] = 0

    core: type[Any]
    instance: type[Any]
    key_column: str
    keys: Sequence[str]
    label: str = ""
    on_copied: Callable[[], Any] | None = None
    on_rolled_back: Callable[[], Any] | None = None

    def run(self, *, rollback: bool, dry_run: bool) -> SeriesMoveResult:
        result = SeriesMoveResult("table", self.label or self.instance.__table__.name)
        source, target = (self.instance, self.core) if rollback else (self.core, self.instance)
        result.copies.append(
            copy_time_index_rows(
                source, target, key_column=self.key_column, keys=self.keys, dry_run=dry_run
            )
        )
        return finish_move(
            result,
            rollback=rollback,
            dry_run=dry_run,
            after_copy=self.on_rolled_back if rollback else self.on_copied,
        )


def finish_move(
    result: SeriesMoveResult,
    *,
    rollback: bool,
    dry_run: bool,
    after_copy: Callable[[], Any] | None = None,
    catalog: Callable[[], Iterable[Any]] | None = None,
    catalog_first: bool = False,
) -> SeriesMoveResult:
    """Set a move's status once its copies ran; on success run its callback and catalog calls.

    A move runs ``after_copy`` then ``catalog`` (the catalog row is written
    last); a rollback (``catalog_first``) removes the catalog row first, so
    Markets reads the core tables again before the provider's updaters do.
    """

    if dry_run:
        result.status = "planned"
        return result
    if not result.complete:
        result.status = "incomplete"
        result.detail = "rows are still missing in the target after the copy"
        return result
    steps = [catalog, after_copy] if catalog_first else [after_copy, catalog]
    for step in steps:
        if step is None:
            continue
        produced = step()
        if step is catalog:
            result.catalog.extend(produced or ())
    result.status = "rolled_back" if rollback else "moved"
    return result


def run_series_moves(
    moves: Iterable[Any],
    *,
    rollback: bool = False,
    dry_run: bool = True,
    stop_on_error: bool = False,
    emit: Callable[[str], None] | None = None,
) -> SeriesMoveReport:
    """Run moves (``TableSeriesMove`` and the portfolio and signal moves) in dependency order.

    A move runs signals before portfolios, so a catalog row never names a signal
    table that does not hold the signal yet; a rollback runs portfolios first.
    One failed move is reported and the others continue unless ``stop_on_error``.
    """

    ordered = sorted(moves, key=lambda move: move.move_order, reverse=rollback)
    report = SeriesMoveReport(rollback=rollback, dry_run=dry_run)
    for move in ordered:
        try:
            result = move.run(rollback=rollback, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - one move's failure is reported, others continue
            if stop_on_error:
                raise
            result = SeriesMoveResult(
                getattr(move, "kind", "table"),
                getattr(move, "label", "") or type(move).__name__,
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        report.results.append(result)
        if emit is not None:
            emit(f"{result.kind} {result.label}: {result.status} {result.detail}".rstrip())
    return report


def _json_state(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else value


__all__ = [
    "DEFAULT_KEYS_PER_READ",
    "KeyCopy",
    "SeriesMoveReport",
    "SeriesMoveResult",
    "TableSeriesMove",
    "TimeIndexCopyReport",
    "TimeIndexRowsCopy",
    "TimeIndexRowsCopyConfiguration",
    "copy_time_index_rows",
    "finish_move",
    "registered_time_index_meta_table",
    "run_series_moves",
]
