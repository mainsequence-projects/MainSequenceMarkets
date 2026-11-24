"""Observation-driven reads of a portfolio's asset inputs, with each asset's last row before."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import product
from typing import Any

import pandas as pd

from ..constants import ASSET_IDENTIFIER


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


def strictly_before(start: Any) -> tuple[Any, str]:
    """Return ``(end_date, end_date_operand)`` that selects rows strictly before ``start``.

    Stored times have microsecond precision, while an incremental window starts
    1 ns after its last row. ``to_pydatetime`` would drop that nanosecond, and
    ``< floor`` would then miss a row stamped exactly at the last row's time.
    "Strictly before" such a start is "at or before" its microsecond floor.
    """
    boundary = pd.Timestamp(start)
    floor = boundary.floor("us")
    return floor.to_pydatetime(), "<=" if floor != boundary else "<"


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
    seed_end, seed_operand = strictly_before(start)
    range_map = [
        {
            "coordinate": {
                **extra_coordinate,
                ASSET_IDENTIFIER: asset_identifier,
            },
            "end_date": seed_end,
            "end_date_operand": seed_operand,
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
                end_date=seed_end,
                less_or_equal=seed_operand == "<=",
                dimension_filters=dimension_filters,
            )
        )
        seed = _latest_per_asset(seed_candidates)

    if not seed.empty:
        seed = seed[seed.index.get_level_values(ASSET_IDENTIFIER).astype(str).isin(assets)]
        seed = _latest_per_asset(seed)
    return window, seed


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
    "fetch_asset_observations",
    "normalize_asset_observations",
    "strictly_before",
]
