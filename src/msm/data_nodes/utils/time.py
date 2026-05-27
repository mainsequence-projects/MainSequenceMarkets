from __future__ import annotations

from typing import Any

import pandas as pd

DATETIME64_NS_UTC = "datetime64[ns, UTC]"


def normalize_datetime64_ns_utc(values: Any) -> Any:
    """Normalize datetime-like values to pandas nanosecond UTC dtype."""

    return pd.to_datetime(values, utc=True).astype(DATETIME64_NS_UTC)


def normalize_timestamp_ns_utc(value: Any) -> pd.Timestamp:
    """Normalize a scalar datetime-like value to a UTC nanosecond Timestamp."""

    return normalize_datetime64_ns_utc(pd.Series([value])).iloc[0]


__all__ = [
    "DATETIME64_NS_UTC",
    "normalize_datetime64_ns_utc",
    "normalize_timestamp_ns_utc",
]
