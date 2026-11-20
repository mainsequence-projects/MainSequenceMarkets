"""Publish history from an application's own table, and assign managers (ADR 0060, decision 9).

Both run only when a person runs them (``msm series publish``, ``msm registry
assign-manager``); nothing here runs by itself.

``publish_series_history`` reads an application's own instance of ``SignalWeightsTS``,
``PortfolioWeightsTS`` or ``PortfoliosTS`` with the operator's own MetaTables access,
publishes its rows key by key through the series row class
(``SignalWeightsSeries.publish`` and the two portfolio series), and compares the
series' ``bounds`` in Markets with the source. It changes nothing in the source; the
application drops its table in a later revision of its own, once the publish is verified.
Publishing the same history again writes nothing.

``assign_managers`` sets ``managed_by`` on ``Portfolio`` and ``SignalMetadata`` rows,
for example the rows created before ADR 0060, which accept no publish until they have a
manager. Through the Markets API only an Organization admin may assign one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

SeriesResource = Literal["signal-weights", "portfolio-weights", "portfolio-values"]


@dataclass(frozen=True)
class SeriesHistoryPublish:
    """Publish ``keys`` of ``source`` (an application's own instance) to ``series``.

    ``source`` is the storage class bound to the application's table, for example the
    one its former ``configured_*_storage`` factory built; ``series`` names the Markets
    series of the same contract. With no ``keys``, every key of the source is published.
    """

    source: type[Any]
    series: SeriesResource
    keys: Sequence[str] = ()
    label: str = ""


@dataclass(frozen=True)
class KeyPublication:
    """One key: rows in the source, rows written and skipped, and the series in Markets."""

    key: str
    source_rows: int
    written: int
    skipped: int
    source_first: Any
    source_last: Any
    markets_first: Any
    markets_last: Any
    markets_rows: int
    error: str = ""

    @property
    def verified(self) -> bool:
        """Markets holds the source's span and at least its rows.

        Signal weights may hold more: Markets closes a dropped asset at ``0``.
        """

        return (
            not self.error
            and _same_time(self.source_first, self.markets_first)
            and _same_time(self.source_last, self.markets_last)
            and self.markets_rows >= self.source_rows
        )

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_rows": self.source_rows,
            "written": self.written,
            "skipped": self.skipped,
            "source_first": _iso(self.source_first),
            "source_last": _iso(self.source_last),
            "markets_first": _iso(self.markets_first),
            "markets_last": _iso(self.markets_last),
            "markets_rows": self.markets_rows,
            "verified": self.verified,
            "error": self.error,
        }


@dataclass
class SeriesHistoryReport:
    """Every key of every ``SeriesHistoryPublish`` of one run."""

    dry_run: bool
    results: list[tuple[str, KeyPublication]] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        if self.dry_run:
            return all(not key.error for _, key in self.results)
        return all(key.verified for _, key in self.results)

    def summary(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "succeeded": self.succeeded,
            "results": [{"label": label, **key.summary()} for label, key in self.results],
        }


def publish_series_history(
    publishes: Iterable[SeriesHistoryPublish],
    *,
    dry_run: bool = True,
    deadline_seconds: float = 300.0,
) -> SeriesHistoryReport:
    """Publish each key's history, oldest first, then compare it with Markets.

    ``dry_run`` reads and compares only. A key whose publish fails is reported with its
    error and the others continue.
    """

    from msm.storage_copies import registered_time_index_meta_table
    from msm_portfolios.services.series import PUBLISH_MAX_ROWS, SERIES
    from msm_portfolios.series_nodes import (
        series_class,
        series_rows,
        whole_time_batches,
    )

    report = SeriesHistoryReport(dry_run=dry_run)
    for publish in publishes:
        spec = SERIES[publish.series]
        rows_class = series_class(publish.series)
        meta_table = registered_time_index_meta_table(publish.source)
        keys = list(dict.fromkeys(str(key) for key in publish.keys)) or _source_keys(
            meta_table, spec.key, deadline_seconds
        )
        label = publish.label or f"{publish.source.__table__.name} -> {publish.series}"
        for key in keys:
            frame = _read_key(meta_table, spec.key, key, deadline_seconds)
            # An application's table may carry columns beyond the contract; only the
            # series' own columns are published.
            rows = [
                {name: value for name, value in row.items() if name in spec.dtypes}
                for row in series_rows(frame, key_column=spec.key)
            ]
            times = [row["time_index"] for row in rows]
            written = skipped = 0
            error = ""
            if not dry_run:
                try:
                    for batch in whole_time_batches(rows, PUBLISH_MAX_ROWS):
                        publication = rows_class.publish(key, batch)
                        written += publication.written
                        skipped += publication.skipped
                except Exception as exc:  # noqa: BLE001 - one key's failure is reported
                    error = f"{type(exc).__name__}: {exc}"
            (bounds,) = rows_class.bounds([key])
            report.results.append(
                (
                    label,
                    KeyPublication(
                        key=key,
                        source_rows=len(rows),
                        written=written,
                        skipped=skipped,
                        source_first=min(times) if times else None,
                        source_last=max(times) if times else None,
                        markets_first=bounds.first_time,
                        markets_last=bounds.last_time,
                        markets_rows=bounds.row_count,
                        error=error,
                    ),
                )
            )
    return report


@dataclass(frozen=True)
class ManagerAssignment:
    """One registry row given a manager, or why it was not."""

    kind: Literal["portfolio", "signal"]
    key: str
    uid: str | None
    previous: str | None
    managed_by: str
    assigned: bool
    detail: str = ""


def assign_managers(
    managed_by: str,
    *,
    portfolios: Sequence[str] = (),
    signals: Sequence[str] = (),
    unmanaged: bool = False,
    dry_run: bool = True,
) -> list[ManagerAssignment]:
    """Make ``managed_by`` the manager of the named portfolios and signals.

    ``portfolios`` are ``Portfolio.unique_identifier`` values and ``signals``
    ``SignalMetadata.signal_uid`` values; ``unmanaged`` adds every row of both that has no
    manager. ``dry_run`` lists the rows and changes nothing.
    """

    from msm.api.managers import validate_principal
    from msm.api.portfolios import Portfolio
    from msm_portfolios.api import SignalMetadata

    principal = validate_principal(managed_by)
    targets: list[tuple[str, type, str, str]] = [
        ("portfolio", Portfolio, "unique_identifier", key) for key in portfolios
    ] + [("signal", SignalMetadata, "signal_uid", key) for key in signals]
    found: dict[tuple[str, str], Any] = {}
    for kind, rows, column, key in targets:
        matches = rows.filter(limit=1, **{column: key})
        found[(kind, key)] = matches[0] if matches else None
    if unmanaged:
        for kind, rows, column in (
            ("portfolio", Portfolio, "unique_identifier"),
            ("signal", SignalMetadata, "signal_uid"),
        ):
            for row in _rows_without_manager(rows):
                found.setdefault((kind, str(getattr(row, column))), row)
    assignments: list[ManagerAssignment] = []
    for (kind, key), row in found.items():
        if row is None:
            assignments.append(
                ManagerAssignment(kind, key, None, None, principal, False, "not found")
            )
            continue
        rows = Portfolio if kind == "portfolio" else SignalMetadata
        assigned = False
        detail = "dry run" if dry_run else ""
        if not dry_run:
            rows.assign_manager(row.uid, principal)
            assigned = True
        assignments.append(
            ManagerAssignment(kind, key, str(row.uid), row.managed_by, principal, assigned, detail)
        )
    return assignments


def _rows_without_manager(rows: type) -> list[Any]:
    found: list[Any] = []
    offset = 0
    while True:
        page = rows.filter(limit=500, offset=offset)
        found.extend(row for row in page if not row.managed_by)
        if len(page) < 500:
            return found
        offset += 500


def _source_keys(meta_table: Any, key_column: str, deadline_seconds: float) -> list[str]:
    frame = _read_columns(meta_table, None, None, [key_column], deadline_seconds)
    if frame.empty:
        return []
    values = (
        frame.index.get_level_values(key_column)
        if key_column in frame.index.names
        else frame[key_column]
    )
    return sorted({str(value) for value in values})


def _read_key(meta_table: Any, key_column: str, key: str, deadline_seconds: float) -> pd.DataFrame:
    return _read_columns(meta_table, key_column, [key], None, deadline_seconds)


def _read_columns(
    meta_table: Any,
    key_column: str | None,
    keys: Sequence[str] | None,
    columns: Sequence[str] | None,
    deadline_seconds: float,
) -> pd.DataFrame:
    from metatables import TimeIndexTableRef

    frame = TimeIndexTableRef.from_meta_table(meta_table).get_df_between_dates(
        dimension_filters={key_column: list(keys)} if key_column and keys else None,
        columns=list(columns) if columns else None,
        deadline_seconds=deadline_seconds,
    )
    return pd.DataFrame() if frame is None else frame


def _same_time(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return pd.Timestamp(left) == pd.Timestamp(right)


def _iso(value: Any) -> str | None:
    return None if value is None else pd.Timestamp(value).isoformat()


__all__ = [
    "KeyPublication",
    "ManagerAssignment",
    "SeriesHistoryPublish",
    "SeriesHistoryReport",
    "assign_managers",
    "publish_series_history",
]
