"""Engine nodes whose output is a published series, and the reads of one (ADR 0060).

``PortfolioWeights`` and ``PortfolioValues`` are not ``TimeIndexTableUpdater``s: they
are bound to no table and MetaTables keeps no update record of them. ``run()`` computes
``update()`` and publishes the rows through the series row class
(``PortfolioWeightsSeries`` or ``PortfolioValuesSeries``); it runs nothing else. The
ledger they project is run by one joined MetaTables run
(``msm_portfolios.recipes.run_portfolios``, issue #133). A node's progress is the series
itself (``bounds`` and ``last``), and a row at or before the key's last stored time is
not published again, so running the same window twice writes nothing.

A signal is not one of them. A computed signal (``SignalWeights``) is a MetaTables node
with its producer's own table, and publishes the rows it writes there with
``publish_new_rows``; a signal whose weights arrive only by publication
(``ApplicationWeights``) reads its published series with ``PublishedSeriesReads``.

The same code runs in a producer under the ``remote`` backend and in the Markets
deployment under ``runtime``.

``get_df_between_dates`` and ``get_last_observation`` read a key's published series
with the arguments the engine passes to any time-index source, so the rebalance
strategies read a published signal the way they read prices.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from msm.settings import markets_namespace
from msm.time_index.assets.asset_indexed import asset_scope_identifier

from msm.settings import ASSET_IDENTIFIER_DIMENSION as ASSET_IDENTIFIER

TIME_INDEX = "time_index"


def series_class(resource: str) -> type:
    """The row class of published series ``resource``."""

    from msm_portfolios.api import series

    return {
        "signal-weights": series.SignalWeightsSeries,
        "portfolio-weights": series.PortfolioWeightsSeries,
        "portfolio-values": series.PortfolioValuesSeries,
    }[resource]


class PublishedSeriesReader:
    """Read published series rows as a time-index source does, for one series.

    ``dimension_filters`` select keys (by the key column) and assets; a
    ``dimension_range_map`` entry ``{"coordinate": {...}, "end_date": t,
    "end_date_operand": "<" | "<="}`` asks for the last row at or before ``t``.
    """

    def __init__(self, resource: str, *, key_column: str, asset_column: str | None) -> None:
        self.resource = resource
        self.key_column = key_column
        self.asset_column = asset_column

    @property
    def rows(self) -> type:
        return series_class(self.resource)

    def window(
        self,
        keys: Sequence[str],
        *,
        start_date: Any = None,
        end_date: Any = None,
        great_or_equal: bool = True,
        less_or_equal: bool = True,
        assets: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        kwargs: dict[str, Any] = {
            "keys": list(keys),
            "start": _datetime_or_none(start_date),
            "end": _datetime_or_none(end_date),
        }
        if assets:
            kwargs["assets"] = list(assets)
        pages: list[pd.DataFrame] = []
        offset = 0
        while True:
            page = self.rows.window(**kwargs, offset=offset, limit=9_000)
            pages.append(page.frame())
            if page.next_offset is None:
                break
            offset = page.next_offset
        frame = pd.concat(pages) if len(pages) > 1 else pages[0]
        if frame.empty:
            return frame
        times = frame.index.get_level_values(TIME_INDEX)
        keep = np.ones(len(frame), dtype=bool)
        if start_date is not None and not great_or_equal:
            keep &= times > pd.Timestamp(start_date)
        if end_date is not None and not less_or_equal:
            keep &= times < pd.Timestamp(end_date)
        return frame[keep]

    def last(
        self,
        keys: Sequence[str],
        *,
        at: Any = None,
        inclusive: bool = True,
        by: str = "asset",
        assets: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        kwargs: dict[str, Any] = {"keys": list(keys), "at": _datetime_or_none(at)}
        if self.asset_column:
            kwargs["by"] = by
            if assets:
                kwargs["assets"] = list(assets)
        kwargs["inclusive"] = inclusive
        return self.rows.last(**kwargs).frame()

    def bounds(self, key: str) -> Any:
        return self.rows.bounds([key])[0]

    def get_df_between_dates(
        self,
        start_date: Any = None,
        end_date: Any = None,
        great_or_equal: bool = True,
        less_or_equal: bool = True,
        dimension_filters: Mapping[str, Sequence[Any]] | None = None,
        dimension_range_map: Sequence[Mapping[str, Any]] | None = None,
        *,
        default_keys: Sequence[str] = (),
    ) -> pd.DataFrame:
        if dimension_range_map:
            raise NotImplementedError("Published series windows take no dimension_range_map.")
        keys, assets = self._selection(dimension_filters, default_keys)
        return self.window(
            keys,
            start_date=start_date,
            end_date=end_date,
            great_or_equal=great_or_equal,
            less_or_equal=less_or_equal,
            assets=assets,
        )

    def get_last_observation(
        self,
        dimension_filters: Mapping[str, Sequence[Any]] | None = None,
        dimension_range_map: Sequence[Mapping[str, Any]] | None = None,
        *,
        default_keys: Sequence[str] = (),
    ) -> pd.DataFrame:
        keys, assets = self._selection(dimension_filters, default_keys)
        if not dimension_range_map:
            return self.last(keys, assets=assets)
        groups: dict[tuple, list[str]] = {}
        for entry in dimension_range_map:
            coordinate = dict(entry.get("coordinate") or {})
            key = str(coordinate.get(self.key_column) or (keys[0] if len(keys) == 1 else ""))
            if not key:
                raise ValueError(f"A range map entry needs {self.key_column}.")
            operand = entry.get("end_date_operand", "<=")
            token = (key, _datetime_or_none(entry.get("end_date")), operand == "<=")
            asset = coordinate.get(self.asset_column) if self.asset_column else None
            groups.setdefault(token, [])
            if asset is not None:
                groups[token].append(str(asset))
        frames = [
            self.last([key], at=at, inclusive=inclusive, assets=group_assets or None)
            for (key, at, inclusive), group_assets in groups.items()
        ]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            from msm_portfolios.services.series import SeriesRows

            return SeriesRows(series=self.resource).frame()
        return pd.concat(frames).sort_index()

    def _selection(
        self,
        dimension_filters: Mapping[str, Sequence[Any]] | None,
        default_keys: Sequence[str],
    ) -> tuple[list[str], list[str] | None]:
        filters = dict(dimension_filters or {})
        keys = [str(value) for value in filters.pop(self.key_column, None) or default_keys]
        assets = None
        if self.asset_column and self.asset_column in filters:
            assets = [str(value) for value in filters.pop(self.asset_column)]
        if filters:
            raise ValueError(f"{self.resource} cannot filter on {sorted(filters)}.")
        if not keys:
            raise ValueError(f"Reading {self.resource} needs a {self.key_column}.")
        return keys, assets


class PublishedSeriesReads:
    """Reads of one key's published series, as a time-index source answers them.

    A subclass names its series resource (``series_resource``), its key column
    (``key_column``) and its key (``series_key``).
    """

    series_resource: ClassVar[str]
    key_column: ClassVar[str]
    asset_column: ClassVar[str | None] = ASSET_IDENTIFIER

    def series_key(self) -> str:
        raise NotImplementedError(f"{self.__class__.__name__} must implement series_key().")

    @property
    def logger(self) -> Any:
        from msm_portfolios import logger

        return logger

    @property
    def reader(self) -> PublishedSeriesReader:
        return PublishedSeriesReader(
            self.series_resource, key_column=self.key_column, asset_column=self.asset_column
        )

    def get_df_between_dates(
        self,
        start_date: Any = None,
        end_date: Any = None,
        great_or_equal: bool = True,
        less_or_equal: bool = True,
        dimension_filters: Mapping[str, Sequence[Any]] | None = None,
        dimension_range_map: Sequence[Mapping[str, Any]] | None = None,
    ) -> pd.DataFrame:
        return self.reader.get_df_between_dates(
            start_date=start_date,
            end_date=end_date,
            great_or_equal=great_or_equal,
            less_or_equal=less_or_equal,
            dimension_filters=dimension_filters,
            dimension_range_map=dimension_range_map,
            default_keys=[self.series_key()],
        )

    def get_last_observation(
        self,
        dimension_filters: Mapping[str, Sequence[Any]] | None = None,
        dimension_range_map: Sequence[Mapping[str, Any]] | None = None,
    ) -> pd.DataFrame:
        return self.reader.get_last_observation(
            dimension_filters=dimension_filters,
            dimension_range_map=dimension_range_map,
            default_keys=[self.series_key()],
        )


class PublishedSeriesNode(PublishedSeriesReads):
    """Base of the nodes that compute a published series and publish it.

    A subclass names its storage contract (``_required_output_table``), its series
    resource (``series_resource``), its key column (``key_column``) and the key it
    publishes (``series_key``), and implements ``update()``.
    """

    OFFSET_START = dt.datetime(2018, 1, 1, tzinfo=dt.UTC)

    def __init__(self, config: Any = None, *, namespace: str | None = None) -> None:
        self.config = self._validate_config(config or self.default_config())
        self.hash_namespace = markets_namespace(namespace)

    # Hooks -----------------------------------------------------------------------------

    @classmethod
    def default_config(cls) -> Any:
        return None

    @classmethod
    def _validate_config(cls, config: Any) -> Any:
        return config

    @classmethod
    def _required_output_table(cls) -> type[Any]:
        raise NotImplementedError(f"{cls.__name__} must define _required_output_table().")

    def update(self) -> pd.DataFrame:
        raise NotImplementedError(f"{self.__class__.__name__} must implement update().")

    # Run -------------------------------------------------------------------------------

    def run(self) -> Any:
        """Compute and publish the rows; the updaters the node reads are not run here."""

        return self.publish_frame(self.update())

    def publish_frame(self, frame: pd.DataFrame | None) -> Any:
        """Publish ``frame``'s rows after the key's last stored time (``publish_new_rows``)."""

        return publish_new_rows(self.reader, frame, publisher=self.__class__.__name__)

    # Frames ----------------------------------------------------------------------------

    @classmethod
    def _column_dtypes_map_for_storage(cls) -> dict[str, str]:
        from msm.time_index.utils.storage_schema import storage_column_dtypes_map

        return storage_column_dtypes_map(cls._required_output_table())

    @classmethod
    def validate_frame(cls, data_frame: pd.DataFrame) -> pd.DataFrame:
        from msm_portfolios.time_index.base import _validate_canonical_frame

        return _validate_canonical_frame(
            data_frame,
            output_table=cls._required_output_table(),
            frame_name=cls.__name__,
        )

    @classmethod
    def _asset_unique_identifier(cls, asset: Any) -> str:
        return asset_scope_identifier(asset, identity_dimension=ASSET_IDENTIFIER)

    @classmethod
    def _max_in_nested_values(cls, value: Any) -> Any:
        if isinstance(value, dict):
            found = [cls._max_in_nested_values(child) for child in value.values()]
            found = [item for item in found if item is not None]
            return max(found) if found else None
        return value


def publish_new_rows(
    series: PublishedSeriesReader, frame: pd.DataFrame | None, *, publisher: str
) -> Any:
    """Publish ``frame``'s rows of one key after the key's last stored time, oldest first.

    Markets leaves out the rows at or before that time (``publish(new_only=True)``), so
    the publisher reads nothing before it publishes. A long frame goes in several calls,
    each holding whole timestamps. Answers the last call's ``SeriesPublication`` with the
    written and skipped rows of all of them, or ``None`` when nothing was new.
    """

    from msm_portfolios import logger
    from msm_portfolios.services.series import PUBLISH_MAX_ROWS

    rows = series_rows(frame, key_column=series.key_column)
    if not rows:
        return None
    key = str(rows[0][series.key_column])
    if any(str(row[series.key_column]) != key for row in rows):
        raise ValueError(f"{publisher} publishes one {series.key_column} per run.")
    written = skipped = 0
    publication = None
    while rows:
        batch = next(iter(whole_time_batches(rows, PUBLISH_MAX_ROWS)))
        publication = series.rows.publish(key, batch, new_only=True)
        written += publication.written
        skipped += publication.skipped
        rows = rows[len(batch) :]
        if publication.last_time is not None:
            rows = [row for row in rows if row[TIME_INDEX] > publication.last_time]
    if not written:
        logger.info(f"{publisher}: nothing new to publish for {key}.")
        return None
    logger.info(f"{publisher}: published {written} rows for {key}.")
    return publication.model_copy(update={"written": written, "skipped": skipped})


def series_rows(frame: pd.DataFrame | None, *, key_column: str) -> list[dict[str, Any]]:
    """The rows of a canonical frame as JSON-ready mappings, oldest first.

    Times become timezone-aware ``datetime``s and missing values ``None``.
    """

    if frame is None or frame.empty:
        return []
    flat = frame.reset_index() if TIME_INDEX not in frame.columns else frame.copy()
    if key_column not in flat.columns:
        raise ValueError(f"Published rows need a {key_column} column.")
    flat = flat.sort_values(TIME_INDEX, kind="stable")
    rows: list[dict[str, Any]] = []
    for record in flat.to_dict(orient="records"):
        rows.append({name: _json_value(value) for name, value in record.items()})
    return rows


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return (value.tz_localize("UTC") if value.tzinfo is None else value).to_pydatetime()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


def whole_time_batches(
    rows: Sequence[dict[str, Any]], limit: int
) -> Iterable[list[dict[str, Any]]]:
    """``rows`` (oldest first) in batches of at most ``limit``, never splitting a time."""

    batch: list[dict[str, Any]] = []
    index = 0
    while index < len(rows):
        time = rows[index][TIME_INDEX]
        group = []
        while index < len(rows) and rows[index][TIME_INDEX] == time:
            group.append(rows[index])
            index += 1
        if len(group) > limit:
            raise ValueError(f"{len(group)} rows at {time} are more than one publish takes.")
        if len(batch) + len(group) > limit:
            yield batch
            batch = []
        batch.extend(group)
    if batch:
        yield batch


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime()


__all__ = [
    "PublishedSeriesNode",
    "PublishedSeriesReader",
    "PublishedSeriesReads",
    "publish_new_rows",
    "series_class",
    "series_rows",
    "whole_time_batches",
]
