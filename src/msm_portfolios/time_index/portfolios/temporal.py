"""Observation-driven temporal alignment for portfolio execution and valuation."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import product
from typing import Any

import pandas as pd

from ..constants import ASSET_IDENTIFIER


def utc_index(values: Iterable[Any], *, name: str = "time_index") -> pd.DatetimeIndex:
    """Return sorted, unique UTC timestamps without manufacturing observations."""
    index = pd.DatetimeIndex(pd.to_datetime(list(values), utc=True), name=name)
    return index.unique().sort_values()


def normalize_asset_observations(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Normalize an asset-indexed source frame to the canonical two-level index."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy().reset_index()
    required = {"time_index", ASSET_IDENTIFIER}
    missing = sorted(required - set(normalized.columns))
    if missing:
        raise ValueError(
            "Asset-indexed observations are missing required columns: " + ", ".join(missing)
        )
    normalized["time_index"] = pd.to_datetime(normalized["time_index"], utc=True)
    normalized[ASSET_IDENTIFIER] = normalized[ASSET_IDENTIFIER].map(str)
    return normalized.set_index(["time_index", ASSET_IDENTIFIER]).sort_index()


def fetch_asset_observations(
    source: Any,
    *,
    start: Any,
    end: Any,
    asset_identifiers: Iterable[str],
    extra_dimension_filters: dict[str, list[Any]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch window rows plus set-based seeds for complete identity coordinates."""
    assets = list(dict.fromkeys(str(value) for value in asset_identifiers))
    if not assets:
        return pd.DataFrame(), pd.DataFrame()

    extra_filters = {
        dimension: list(values) for dimension, values in (extra_dimension_filters or {}).items()
    }
    if ASSET_IDENTIFIER in extra_filters:
        raise ValueError(
            f"{ASSET_IDENTIFIER!r} must be supplied through asset_identifiers, "
            "not extra_dimension_filters."
        )
    dimension_filters = {ASSET_IDENTIFIER: assets, **extra_filters}
    window = normalize_asset_observations(
        source.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters=dimension_filters,
        )
    )

    extra_dimensions = list(extra_filters)
    extra_coordinates = (
        [
            dict(zip(extra_dimensions, values, strict=True))
            for values in product(*(extra_filters[name] for name in extra_dimensions))
        ]
        if extra_dimensions
        else [{}]
    )
    range_map = [
        {
            "coordinate": {
                **extra_coordinate,
                ASSET_IDENTIFIER: asset_identifier,
            },
            "end_date": pd.Timestamp(start).to_pydatetime(),
            "end_date_operand": "<",
        }
        for extra_coordinate in extra_coordinates
        for asset_identifier in assets
    ]
    if not range_map:
        return window, pd.DataFrame()

    get_last_observation = getattr(source, "get_last_observation", None)
    if callable(get_last_observation):
        seed = normalize_asset_observations(
            get_last_observation(
                dimension_filters=dimension_filters,
                dimension_range_map=range_map,
            )
        )
    else:
        seed_candidates = normalize_asset_observations(
            source.get_df_between_dates(
                end_date=start,
                less_or_equal=False,
                dimension_filters=dimension_filters,
            )
        )
        seed = _latest_per_asset(seed_candidates)

    if not seed.empty:
        seed = seed[seed.index.get_level_values(ASSET_IDENTIFIER).astype(str).isin(assets)]
        seed = _latest_per_asset(seed)
    return window, seed


def align_asset_observations(
    observations: pd.DataFrame,
    *,
    target_index: pd.DatetimeIndex,
    asset_identifiers: Iterable[str],
    value_columns: Iterable[str],
    maximum_staleness: Any,
    fail_on_missing_values: bool,
    required_coordinates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Select the latest eligible observation per asset at explicit target times."""
    targets = utc_index(target_index)
    assets = list(dict.fromkeys(str(value) for value in asset_identifiers))
    columns = list(value_columns)
    if len(targets) == 0 or not assets:
        return pd.DataFrame()

    required = (
        pd.DataFrame(True, index=targets, columns=assets)
        if required_coordinates is None
        else required_coordinates.reindex(index=targets, columns=assets).fillna(False).astype(bool)
    )

    normalized = normalize_asset_observations(observations)
    missing_columns = sorted(set(columns) - set(normalized.columns))
    if missing_columns:
        raise ValueError(
            "Valuation source is missing required columns: " + ", ".join(missing_columns)
        )

    available_assets = set(normalized.index.get_level_values(ASSET_IDENTIFIER).astype(str).unique())
    absent_assets = sorted(set(assets) - available_assets)
    absent_required_assets = [asset for asset in absent_assets if required[asset].any()]
    if absent_required_assets and fail_on_missing_values:
        raise ValueError(
            "Valuation source is missing required assets: " + ", ".join(absent_required_assets)
        )

    flat = normalized.reset_index()
    result_parts: dict[str, pd.DataFrame] = {}
    observation_times: pd.DataFrame | None = None
    for column in columns:
        pivot = flat.pivot_table(
            index="time_index",
            columns=ASSET_IDENTIFIER,
            values=column,
            aggfunc="last",
        ).reindex(columns=assets)
        source_times = pd.DataFrame(
            {asset: pivot.index.where(pivot[asset].notna()) for asset in pivot.columns},
            index=pivot.index,
        )
        combined = pivot.index.union(targets).sort_values()
        result_parts[column] = pivot.reindex(combined).ffill().reindex(targets)
        if observation_times is None:
            observation_times = source_times.reindex(combined).ffill().reindex(targets)

    assert observation_times is not None
    target_matrix = pd.DataFrame(
        {asset: targets for asset in assets},
        index=targets,
    )
    ages = target_matrix - observation_times
    stale = ages > pd.Timedelta(maximum_staleness)
    missing = observation_times.isna() | stale
    missing_required = missing & required
    if missing_required.any().any() and fail_on_missing_values:
        details = [
            f"{asset}@{timestamp.isoformat()}"
            for timestamp, row in missing_required.iterrows()
            for asset, is_missing in row.items()
            if bool(is_missing)
        ]
        raise ValueError(
            "No sufficiently fresh valuation observation for " + ", ".join(details[:10])
        )

    for values in result_parts.values():
        values[missing] = pd.NA

    stacked_parts = []
    for column, values in result_parts.items():
        series = values.stack().rename(column)
        stacked_parts.append(series)
    aligned = pd.concat(stacked_parts, axis=1)
    aligned.index.names = ["time_index", ASSET_IDENTIFIER]
    return aligned.sort_index()


def _latest_per_asset(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    flat = frame.reset_index().sort_values("time_index")
    return (
        flat.groupby(ASSET_IDENTIFIER, as_index=False, sort=False)
        .tail(1)
        .set_index(["time_index", ASSET_IDENTIFIER])
        .sort_index()
    )


__all__ = [
    "align_asset_observations",
    "fetch_asset_observations",
    "normalize_asset_observations",
    "utc_index",
]
