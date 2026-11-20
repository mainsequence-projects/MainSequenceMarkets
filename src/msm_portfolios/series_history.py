"""Publish history from an application's own table (ADR 0060, decision 9).

It runs only when a person runs it (``msm series publish``); nothing here runs by itself.

A ``SeriesHistoryPublish`` reads an application's own instance of ``SignalWeightsTS``,
``PortfolioWeightsTS`` or ``PortfoliosTS`` with the operator's own MetaTables access,
publishes its rows key by key through the series row class
(``SignalWeightsSeries.publish`` and the two portfolio series), and compares the
series' ``bounds`` in Markets with the source. It changes nothing in the source; the
application drops its table in a revision of its own, once the publish is verified.
Publishing the same history again writes nothing.

``msm.storage_copies.run_series_publishes`` runs the publishes an operator callable
returns and builds the report; it knows no series. Managers are assigned with
``msm.api.managers.assign_managers`` (``msm registry assign-manager``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from msm.storage_copies import KeyPublication

SeriesResource = Literal["signal-weights", "portfolio-weights", "portfolio-values"]


@dataclass(frozen=True)
class SeriesHistoryPublish:
    """Publish ``keys`` of ``source`` (an application's own instance) to ``series``.

    ``source`` is the storage class bound to the application's table; ``series`` names the
    Markets series of the same contract. With no ``keys``, every key of the source is
    published.
    """

    source: type[Any]
    series: SeriesResource
    keys: Sequence[str] = ()
    label: str = ""
    deadline_seconds: float = 300.0

    def run(self, *, dry_run: bool = True) -> list[tuple[str, KeyPublication]]:
        """Publish each key's history, oldest first, then compare it with Markets.

        ``dry_run`` reads and compares only. A key whose publish fails is reported with
        its error and the others continue.
        """

        from msm.storage_copies import registered_time_index_meta_table
        from msm_portfolios.services.series import PUBLISH_MAX_ROWS, SERIES
        from msm_portfolios.series_nodes import (
            series_class,
            series_rows,
            whole_time_batches,
        )

        spec = SERIES[self.series]
        rows_class = series_class(self.series)
        meta_table = registered_time_index_meta_table(self.source)
        keys = list(dict.fromkeys(str(key) for key in self.keys)) or _source_keys(
            meta_table, spec.key, self.deadline_seconds
        )
        label = self.label or f"{self.source.__table__.name} -> {self.series}"
        results: list[tuple[str, KeyPublication]] = []
        for key in keys:
            frame = _read_key(meta_table, spec.key, key, self.deadline_seconds)
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
            results.append(
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
        return results


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


__all__ = ["SeriesHistoryPublish"]
