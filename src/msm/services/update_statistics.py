"""Rebuild the update statistics MetaTables stores for a time-index table (MetaTables#117).

A delete sent as compiled SQL statements leaves the progress MetaTables stores for each
time-index table (``index_stats``) as it was: the deleted coordinates keep their last time
index until the next insert into the table rebuilds it. An updater run filters the rows
it publishes by that progress (``UpdateStatistics.filter_df_by_latest_value``), so rows
published again for a deleted coordinate, at or before its stale last time, are dropped
without an error: a portfolio re-created under the same identifier, or an account whose
connector publishes its orders again, would resume from the deleted series.

``TimeIndexMetaTable.delete_after_date`` rebuilds the table's statistics from its rows
and replaces the stored ones. With a cutoff later than any row it deletes nothing.
``set-last-update-index-time`` would not do: it merges into the stored statistics and
keeps the deleted entries. Remove this module once MetaTables#117 is fixed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger

logger = _mainsequence_logger.bind(sub_application="markets", component="update_statistics")

STATISTICS_REFRESH_CUTOFF = "9999-12-31T00:00:00+00:00"
"""A ``delete_after_date`` cutoff later than any stored row, so the rebuild deletes
nothing, not even rows written under a deleted identifier since the delete."""


def refresh_update_statistics(
    model: type[Any],
    *,
    dimension_filters: Mapping[str, Sequence[Any]] | None = None,
    timeout: Any = None,
) -> None:
    """Rebuild the stored update statistics of ``model``'s table from its rows.

    ``dimension_filters`` scopes the call to the deleted coordinates; the rebuild itself
    covers the whole table. Each call locks the table and scans it whole under MetaTables'
    statement timeout. Raises when the table is not attached or MetaTables refuses.
    """

    meta_table = model.get_time_index_meta_table()
    if meta_table is None:
        raise RuntimeError(f"{model.__name__} is not attached to a backend TimeIndexMetaTable.")
    meta_table.delete_after_date(
        STATISTICS_REFRESH_CUTOFF,
        dimension_filters={key: list(values) for key, values in dimension_filters.items()}
        if dimension_filters
        else None,
        timeout=timeout,
    )


def refresh_portfolio_dataset_statistics(
    deleted_rows: Mapping[str, Mapping[str, int]],
    *,
    timeout: Any = None,
) -> dict[str, list[str]]:
    """Rebuild the statistics of each portfolio dataset table that lost rows.

    ``deleted_rows`` maps each deleted portfolio's ``unique_identifier`` to the rows it
    lost per dataset key (`msm.portfolio_datasets`). Each table that lost rows gets one
    call, scoped to the identifiers that lost rows there. A failure, such as the rebuild
    exceeding MetaTables' statement timeout on a large table, does not undo the delete:
    it is logged, and the answer lists per identifier the dataset keys whose statistics
    were not refreshed.
    """

    from msm.portfolio_datasets import portfolio_dataset_tables

    not_refreshed: dict[str, list[str]] = {identifier: [] for identifier in deleted_rows}
    if not deleted_rows:
        return not_refreshed
    for table in portfolio_dataset_tables():
        identifiers = [
            identifier for identifier, rows in deleted_rows.items() if rows.get(table.key, 0) > 0
        ]
        if not identifiers:
            continue
        try:
            refresh_update_statistics(
                table.model,
                dimension_filters={"portfolio_identifier": identifiers},
                timeout=timeout,
            )
        except Exception:
            logger.exception(
                "MetaTables could not refresh a portfolio dataset table's update statistics",
                dataset=table.key,
                portfolio_identifiers=identifiers,
            )
            for identifier in identifiers:
                not_refreshed[identifier].append(table.key)
    return not_refreshed


def statistics_not_refreshed_text(keys: Sequence[str]) -> str:
    """The sentence a delete's ``detail`` adds when some statistics were not refreshed."""

    return (
        "MetaTables could not refresh the stored update statistics of "
        f"{', '.join(keys)}; see statistics_not_refreshed."
    )


__all__ = [
    "STATISTICS_REFRESH_CUTOFF",
    "refresh_portfolio_dataset_statistics",
    "refresh_update_statistics",
    "statistics_not_refreshed_text",
]
